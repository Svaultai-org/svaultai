import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/memory_title_identity.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';

const _token = 'synthetic-memory-session';
const _base = 'https://synthetic.invalid';
const _title = 'QA Duplicate Memory';
const _rows = <Map<String, dynamic>>[
  {
    'id': 'first',
    'title': _title,
    'value': 'first dummy value',
    'memory_type': 'note'
  },
  {
    'id': 'second',
    'title': _title,
    'value': 'second dummy value',
    'memory_type': 'note'
  },
];

Future<Map<String, dynamic>> _envelope(Map<String, dynamic> row) async {
  final key =
      await hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).memoryKey();
  return {
    'memory_id': row['id'],
    'memory_type': 'note',
    'payload_ciphertext': hierarchy.b64urlEncode(
      await hierarchy.aesGcmWrap(key, utf8.encode(jsonEncode(row))),
    ),
  };
}

class _PageClient extends VaultAIClient {
  final List<Map<String, dynamic>> rows =
      _rows.map(Map<String, dynamic>.from).toList();
  final List<String?> editedIds = [];

  _PageClient() : super(baseUrl: _base);

  @override
  Future<Map<String, dynamic>> listZkMemories(
          {required String authToken, int limit = 200}) async =>
      {
        'items': rows,
        'counts': {'note': rows.length},
      };

  @override
  Future<void> upsertZkMemory(
      {required String authToken,
      required Map<String, dynamic> data,
      String? memoryId}) async {
    editedIds.add(memoryId);
    final index = rows.indexWhere((row) => row['id'] == memoryId);
    if (index >= 0) rows[index] = {...data, 'id': memoryId};
  }
}

Widget _app(Widget child, {Locale locale = const Locale('en')}) => MaterialApp(
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: child),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    st.SessionTermination.instance.reset();
    ZkActiveMvk.set(
      mvk: SecretKey(List.generate(32, (index) => index)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
  });
  tearDown(() {
    ZkActiveMvk.clear();
    st.SessionTermination.instance.reset();
  });

  test('title collisions are case/whitespace-insensitive but identity-scoped',
      () {
    expect(
        memoryTitleConflicts(
            title: '  qa duplicate   memory ', memories: _rows),
        isTrue);
    expect(
        memoryTitleConflicts(
            title: _title, memories: [_rows.first], editingMemoryId: 'first'),
        isFalse);
    expect(
        memoryTitleConflicts(
            title: _title, memories: _rows, editingMemoryId: 'first'),
        isTrue);
    expect(memoryTitleConflicts(title: 'A different title', memories: _rows),
        isFalse);
  });

  test('duplicate-title retrieval is ambiguous, not proof that nothing exists',
      () {
    const entries = [
      VaultLocalContentEntry(id: 'first', label: _title),
      VaultLocalContentEntry(id: 'second', label: _title),
    ];
    expect(
        resolveVaultLocalContentMatch(query: _title, entries: entries), isNull);
    expect(memoryQueryIsAmbiguous(query: _title, entries: entries), isTrue);
    expect(
        memoryQueryIsAmbiguous(
            query: 'Missing synthetic item', entries: entries),
        isFalse);
  });

  test('a stronger exact match is not falsely called ambiguous', () {
    expect(
        memoryQueryIsAmbiguous(query: 'Memory One', entries: const [
          VaultLocalContentEntry(id: 'first', label: 'Memory One'),
          VaultLocalContentEntry(id: 'second', label: 'Memory'),
        ]),
        isFalse);
  });

  test('literal Unicode and emoji titles remain exact local memory matches',
      () {
    for (final title in ['東京', 'ملاحظتي 🔒', '🔒', 'Café']) {
      final command =
          parseVaultLocalContentCommand('What do you remember about $title?');
      expect(command?.query, title);
      final match = resolveMemoryLocalContentMatch(query: title, entries: [
        VaultLocalContentEntry(id: 'selected', label: title),
        const VaultLocalContentEntry(id: 'other', label: 'Other memory'),
      ]);
      expect(match?.entry.id, 'selected');
    }
  });

  test('same natural Save phrase creates once and warns without a second write',
      () async {
    const phrase = 'Save my favorite city as Paris';
    final command = parseVaultLocalMemorySaveCommand(phrase)!;
    final saved = <Map<String, dynamic>>[];
    final methods = <String>[];
    await http.runWithClient(() async {
      const client = VaultAIClient(baseUrl: _base);
      await client.upsertZkMemory(
          authToken: _token, data: command.toMemoryData());
      final firstCiphertext = saved.single['payload_ciphertext'];
      await expectLater(
        client.upsertZkMemory(authToken: _token, data: command.toMemoryData()),
        throwsA(isA<MemoryTitleConflictException>()),
      );
      expect(saved.single['payload_ciphertext'], firstCiphertext);
    },
        () => MockClient((request) async {
              methods.add(request.method);
              if (request.method == 'GET')
                return http.Response(jsonEncode(saved), 200);
              final body = jsonDecode(request.body) as Map<String, dynamic>;
              saved.add({
                'memory_id': body['memory_id'],
                'memory_type': body['memory_type'],
                'payload_ciphertext': body['payload_ciphertext'],
              });
              return http.Response('{"memory_id":"1"}', 200);
            }));
    expect(methods, ['GET', 'POST', 'GET']);
    expect(saved, hasLength(1));
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<bool> _tryLocalMemorySaveCommand(');
    final end =
        source.indexOf('Future<bool> _tryLocalVaultContentCommand(', start);
    final handler = source.substring(start, end);
    expect(handler, contains('memoryTitleConflicts('));
    expect(handler, isNot(contains('memoryId: existingId')));
  });

  for (final terminate in [false, true]) {
    test('changed memory access during preflight never sends POST ($terminate)',
        () async {
      final started = Completer<void>();
      final pending = Completer<http.Response>();
      final methods = <String>[];
      await http.runWithClient(() async {
        final saving = const VaultAIClient(baseUrl: _base).upsertZkMemory(
          authToken: _token,
          data: {'title': 'New memory', 'value': 'dummy value'},
        );
        await started.future;
        if (terminate) {
          await st.SessionTermination.instance
              .handle(st.SessionTerminationCode.revoked);
        } else {
          ZkActiveMvk.clear();
        }
        pending.complete(http.Response('[]', 200));
        await expectLater(saving, throwsA(isA<StateError>()));
      },
          () => MockClient((request) {
                methods.add(request.method);
                started.complete();
                return pending.future;
              }));
      expect(methods, ['GET']);
    });
  }

  test('a changed key cannot return old decrypted inventory', () async {
    final envelope = await _envelope(_rows.first);
    final started = Completer<void>();
    final pending = Completer<http.Response>();
    await http.runWithClient(() async {
      final listing =
          const VaultAIClient(baseUrl: _base).listZkMemories(authToken: _token);
      await started.future;
      ZkActiveMvk.set(
        mvk: SecretKey(List.filled(32, 99)),
        vaultId: 'different-synthetic-vault',
        vaultHandle: 'different-synthetic-handle',
      );
      pending.complete(http.Response(jsonEncode([envelope]), 200));
      await expectLater(listing, throwsA(isA<StateError>()));
    },
        () => MockClient((_) {
              started.complete();
              return pending.future;
            }));
  });

  testWidgets('localized same-title card recall carries the selected row ID',
      (tester) async {
    final client = _PageClient();
    Map<String, dynamic>? selected;
    String? localizedQuestion;
    var oldPromptCalls = 0;
    await tester.binding.setSurfaceSize(const Size(1000, 1300));
    await tester.pumpWidget(_app(
        MemoryPage(
          client: client,
          authToken: _token,
          vaultName: 'synthetic-vault',
          isMobile: false,
          onOpenMemory: (row, prompt) {
            selected = row;
            localizedQuestion = prompt;
          },
          onAskVaultAI: (_) => oldPromptCalls++,
        ),
        locale: const Locale('fr')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('memory_row_card_second')));
    await tester.pumpAndSettle();
    expect(selected?['id'], 'second');
    expect(memoryLocalReply(selected!), contains('second dummy value'));
    expect(memoryLocalReply(selected!), isNot(contains('first dummy value')));
    expect(localizedQuestion, isNot('What do you remember about $_title?'));
    expect(oldPromptCalls, 0);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.binding.setSurfaceSize(null);
  });

  test('duplicate CREATE is rejected before any ciphertext write', () async {
    final existing = await _envelope(_rows.first);
    final methods = <String>[];
    await http.runWithClient(() async {
      await expectLater(
        const VaultAIClient(baseUrl: _base).upsertZkMemory(
          authToken: _token,
          data: {
            'title': _title,
            'value': 'new dummy value',
            'memory_type': 'note'
          },
        ),
        throwsA(isA<MemoryTitleConflictException>()),
      );
    },
        () => MockClient((request) async {
              methods.add(request.method);
              return http.Response(jsonEncode([existing]), 200);
            }));
    expect(methods, ['GET']);
  });

  test('selected edit preserves its ID, replacement flag and encrypted body',
      () async {
    final existing = await _envelope(_rows.first);
    final writes = <Map<String, dynamic>>[];
    await http.runWithClient(() async {
      await const VaultAIClient(baseUrl: _base).upsertZkMemory(
        authToken: _token,
        memoryId: 'first',
        data: {
          'title': 'Renamed unique memory',
          'value': 'changed dummy value',
          'memory_type': 'note'
        },
      );
    },
        () => MockClient((request) async {
              if (request.method == 'GET')
                return http.Response(jsonEncode([existing]), 200);
              writes.add(jsonDecode(request.body) as Map<String, dynamic>);
              return http.Response('{"memory_id":"1"}', 200);
            }));
    expect(writes, hasLength(1));
    expect(writes.single['memory_id'], 'first');
    expect(writes.single['replace_existing'], isTrue);
    expect(writes.single.containsKey('title'), isFalse);
    expect(writes.single.containsKey('value'), isFalse);
    final key =
        await hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).memoryKey();
    final clear = jsonDecode(utf8.decode(await hierarchy.aesGcmUnwrap(
      key,
      hierarchy.b64urlDecode(writes.single['payload_ciphertext'] as String),
    ))) as Map;
    expect(clear['title'], 'Renamed unique memory');
    expect(clear['value'], 'changed dummy value');
  });

  test('renaming selected edit into another title does not issue POST',
      () async {
    final other =
        await _envelope({..._rows.last, 'title': 'Other existing title'});
    final methods = <String>[];
    await http.runWithClient(() async {
      await expectLater(
          const VaultAIClient(baseUrl: _base).upsertZkMemory(
            authToken: _token,
            memoryId: 'first',
            data: {'title': 'Other existing title', 'value': 'new dummy value'},
          ),
          throwsA(isA<MemoryTitleConflictException>()));
    },
        () => MockClient((request) async {
              methods.add(request.method);
              return http.Response(jsonEncode([other]), 200);
            }));
    expect(methods, ['GET']);
  });

  test('stale preflight race maps server409 to the same safe title warning',
      () async {
    final methods = <String>[];
    await http.runWithClient(() async {
      await expectLater(
          const VaultAIClient(baseUrl: _base).upsertZkMemory(
            authToken: _token,
            data: {'title': 'New title', 'value': 'dummy value'},
          ),
          throwsA(isA<MemoryTitleConflictException>()));
    },
        () => MockClient((request) async {
              methods.add(request.method);
              return request.method == 'GET'
                  ? http.Response('[]', 200)
                  : http.Response('{"detail":"memory_title_conflict"}', 409);
            }));
    expect(methods, ['GET', 'POST']);
  });

  test('proposal CREATE cannot silently replace a saved title either',
      () async {
    final existing = await _envelope(_rows.first);
    final methods = <String>[];
    await http.runWithClient(() async {
      await expectLater(
          const VaultAIClient(baseUrl: _base).tryZkFinalizeMemoryProposal(
            baseUrl: _base,
            authToken: _token,
            memoryType: 'note',
            memoryKey: _title,
            memoryValue: 'different dummy value',
          ),
          throwsA(isA<MemoryTitleConflictException>()));
    },
        () => MockClient((request) async {
              methods.add(request.method);
              return http.Response(jsonEncode([existing]), 200);
            }));
    expect(methods, ['GET']);
  });

  test('inventory preserves equal-title records and reports unopened envelopes',
      () async {
    final envelopes = [
      await _envelope(_rows.first),
      await _envelope(_rows.last),
      {
        'memory_id': 'unreadable',
        'memory_type': 'note',
        'payload_ciphertext': 'AA'
      }
    ];
    await http.runWithClient(() async {
      final inventory = await const VaultAIClient(baseUrl: _base)
          .listZkMemories(authToken: _token, limit: 0);
      final items = inventory['items'] as List;
      expect(items, hasLength(2));
      expect(items.map((row) => row['id']).toList(), ['first', 'second']);
      expect(items.map((row) => row['value']).toList(),
          ['first dummy value', 'second dummy value']);
      expect(inventory['counts'], {'note': 2});
      expect(inventory['unavailable_count'], 1);
    },
        () =>
            MockClient((_) async => http.Response(jsonEncode(envelopes), 200)));
  });

  testWidgets('duplicate editor warning retains the unsaved values',
      (tester) async {
    Map<String, dynamic>? result;
    await tester.pumpWidget(_app(Builder(
        builder: (context) => FilledButton(
              onPressed: () async {
                result = await showMemoryEditorDialog(context,
                    existingMemories: _rows);
              },
              child: const Text('Open editor'),
            ))));
    await tester.tap(find.text('Open editor'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), _title);
    await tester.enterText(
        find.byKey(const Key('memory_dialog_value')), 'unsaved synthetic text');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(result, isNull);
    expect(find.text(kMemoryTitleConflictMessage), findsOneWidget);
    expect(find.text('New memory'), findsOneWidget);
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('memory_dialog_value')))
            .controller!
            .text,
        'unsaved synthetic text');
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
  });

  testWidgets('equal-title cards stay separate and edit the selected identity',
      (tester) async {
    final client = _PageClient();
    await tester.binding.setSurfaceSize(const Size(1000, 1300));
    await tester.pumpWidget(_app(MemoryPage(
      client: client,
      authToken: _token,
      vaultName: 'synthetic-vault',
      isMobile: false,
    )));
    await tester.pumpAndSettle();
    expect(find.text(_title), findsNWidgets(2));
    await tester.tap(find.byKey(const Key('memory_row_reveal_first')));
    await tester.pumpAndSettle();
    expect(find.textContaining('first dummy value'), findsWidgets);
    expect(find.textContaining('second dummy value'), findsNothing);
    await tester.tap(find.byKey(const Key('memory_row_edit_first')));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), 'First renamed uniquely');
    await tester.enterText(find.byKey(const Key('memory_dialog_value')),
        'edited first dummy value');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.editedIds, ['first']);
    expect(client.rows.last['value'], 'second dummy value');
    expect(find.text('First renamed uniquely'), findsOneWidget);
    expect(find.text(_title), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.binding.setSurfaceSize(null);
  });
}
