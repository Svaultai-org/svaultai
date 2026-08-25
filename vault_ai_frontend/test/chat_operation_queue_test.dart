import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_operation_queue.dart';

void main() {
  group('chat mutation ordering barrier', () {
    test(
      'credential save reaches terminal persistence before lookup starts',
      () async {
        final queue = ChatOperationQueue();
        final events = <String>[];
        final credentials = <String, String>{};

        final save = queue.enqueue<void>(
          kind: ChatOperationKind.mutation,
          operation: () async {
            events.add('save_started');
            await Future<void>.delayed(const Duration(milliseconds: 15));
            credentials['nord vpn'] = 'stored';
            events.add('save_persisted');
          },
        );
        final lookup = queue.enqueue<String?>(
          kind: ChatOperationKind.read,
          operation: () async {
            events.add('lookup_started');
            return credentials['nord vpn'];
          },
        );

        expect(queue.hasPendingMutation, isTrue);
        expect(await lookup, 'stored');
        await save;
        expect(events, <String>[
          'save_started',
          'save_persisted',
          'lookup_started',
        ]);
        expect(queue.isBusy, isFalse);
      },
    );

    test(
      'memory save then recall and file save then find see committed state',
      () async {
        final queue = ChatOperationQueue();
        final vault = <String, String>{};

        Future<void> save(String key, String value, int delayMs) {
          return queue.enqueue<void>(
            kind: ChatOperationKind.mutation,
            operation: () async {
              await Future<void>.delayed(Duration(milliseconds: delayMs));
              vault[key] = value;
            },
          );
        }

        Future<String?> find(String key) => queue.enqueue<String?>(
          kind: ChatOperationKind.read,
          operation: () async => vault[key],
        );

        unawaited(save('memory:conference', 'September', 12));
        final recalled = find('memory:conference');
        unawaited(save('file:passport', 'present', 4));
        final found = find('file:passport');

        expect(await recalled, 'September');
        expect(await found, 'present');
        await queue.settled;
      },
    );

    test(
      'credential, memory, and file deletes finish before dependent reads',
      () async {
        final queue = ChatOperationQueue();
        final vault = <String, String>{
          'credential:nord': 'present',
          'memory:trip': 'present',
          'file:tax': 'present',
        };

        for (final key in vault.keys.toList(growable: false)) {
          unawaited(
            queue.enqueue<void>(
              kind: ChatOperationKind.mutation,
              operation: () async {
                await Future<void>.delayed(const Duration(milliseconds: 3));
                vault.remove(key);
              },
            ),
          );
          final value = queue.enqueue<String?>(
            kind: ChatOperationKind.read,
            operation: () async => vault[key],
          );
          expect(
            await value,
            isNull,
            reason: '$key must not be read pre-delete',
          );
        }
        await queue.settled;
      },
    );

    test(
      'a failed mutation releases the next lookup at terminal failure',
      () async {
        final queue = ChatOperationQueue();
        final events = <String>[];
        final failed = queue.enqueue<void>(
          kind: ChatOperationKind.mutation,
          operation: () async {
            events.add('mutation_started');
            await Future<void>.delayed(const Duration(milliseconds: 2));
            events.add('mutation_failed');
            throw StateError('expected');
          },
        );
        final lookup = queue.enqueue<void>(
          kind: ChatOperationKind.read,
          operation: () async => events.add('lookup_started'),
        );

        await expectLater(failed, throwsStateError);
        await lookup;
        expect(events, <String>[
          'mutation_started',
          'mutation_failed',
          'lookup_started',
        ]);
        expect(queue.hasPendingMutation, isFalse);
      },
    );

    test(
      '20-command mixed stress preserves FIFO and loses no operation',
      () async {
        final traces = <ChatOperationTrace>[];
        final queue = ChatOperationQueue(
          nowMicros: () => 42,
          onTrace: traces.add,
        );
        final state = <String, int>{};
        final observed = <int>[];
        final futures = <Future<void>>[];

        for (var pair = 0; pair < 10; pair++) {
          futures.add(
            queue.enqueue<void>(
              kind: ChatOperationKind.mutation,
              operation: () async {
                await Future<void>.delayed(
                  Duration(milliseconds: (9 - pair) % 4),
                );
                state['item_$pair'] = pair;
              },
            ),
          );
          futures.add(
            queue.enqueue<void>(
              kind: ChatOperationKind.read,
              operation: () async {
                observed.add(state['item_$pair'] ?? -1);
              },
            ),
          );
        }

        await Future.wait(futures);
        expect(observed, List<int>.generate(10, (index) => index));
        expect(
          traces.where((trace) => trace.phase == ChatOperationPhase.enqueued),
          hasLength(20),
        );
        expect(
          traces
              .where((trace) => trace.phase == ChatOperationPhase.enqueued)
              .map((trace) => trace.operationId)
              .toSet(),
          hasLength(20),
        );
        expect(
          traces.where(
            (trace) => trace.phase == ChatOperationPhase.terminalSuccess,
          ),
          hasLength(20),
        );
        expect(queue.pendingCount, 0);
      },
    );
  });

  group('mutation classification', () {
    test('covers authoritative credential, memory, and file mutations', () {
      for (final command in <String>[
        'save it',
        'Remember my conference is in September',
        'delete my Nord VPN login',
        'forget my conference memory',
        'remove tax.pdf from my vault',
        'update my Nord VPN credential',
        'rename my passport document',
      ]) {
        expect(
          isAuthoritativeVaultMutationCommand(command),
          isTrue,
          reason: command,
        );
      }
      expect(
        isAuthoritativeVaultMutationCommand(
          'review selected candidates',
          hasPrivateBackendCommand: true,
        ),
        isTrue,
      );
      expect(
        isAuthoritativeVaultMutationCommand('', hasAttachments: true),
        isTrue,
      );
    });

    test('ordinary lookups remain reads', () {
      for (final command in <String>[
        'what is my nord vpn login',
        'recall my conference memory',
        'find tax.pdf',
      ]) {
        expect(
          isAuthoritativeVaultMutationCommand(command),
          isFalse,
          reason: command,
        );
      }
    });
  });

  test('production chat entry points share the ordering barrier', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('final ChatOperationQueue _chatOperationQueue'));
    expect(source, contains('operation: _send'));
    expect(source, contains('await _send();'));
    expect(
      source,
      contains('await _saveGeneratedLoginAuthoritatively('),
    );
    expect(source, contains('enabled: !_chatOperationBusy'));
    expect(source, contains('operation: () => _saveMemoryProposalFromCard'));
    expect(source, contains('requestId: chatRequestId'));
    expect(source, contains('mutationRunner: (operation)'));
  });
}
