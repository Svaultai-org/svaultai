
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/perf/chat_send_state.dart';
import 'package:vault_ai_frontend/perf/frontend_cache.dart';
import 'package:vault_ai_frontend/perf/perf_trace.dart';


void main() {

  setUp(() {
    FrontendCache.instance.invalidateAll();
    PerfTrace.instance.resetForTests();
    PerfTrace.instance.setEnabledForTests(true);
  });


  group('Part 1 — chat user-bubble immediacy', () {
    test(
      'user bubble state fires synchronously on onUserSendClicked',
      () {
        final ctrl = ChatSendController();
        expect(ctrl.value.phase, ChatSendPhase.idle);
        ctrl.onUserSendClicked('what is my vault?');
        expect(
          ctrl.value.phase, ChatSendPhase.userBubbleShown,
          reason:
              'the user bubble MUST appear synchronously on send-'
              'click, before any network call is fired',
        );
      },
    );

    test('preview is sanitised — sensitive input never previewed',
        () {
      final ctrl = ChatSendController();
      ctrl.onUserSendClicked('my seed phrase is x');
      expect(
        ctrl.value.userMessagePreview, isEmpty,
        reason:
            'the visible preview must never leak seed / pin / '
            'password text',
      );
    });

    test('long input is truncated in preview', () {
      final ctrl = ChatSendController();
      ctrl.onUserSendClicked('a' * 200);
      expect(
        ctrl.value.userMessagePreview!.length,
        lessThanOrEqualTo(61),
      );
    });
  });


  group('Part 2 — thinking indicator immediacy', () {
    test('thinking phase fires under 100ms', () {
      final ctrl = ChatSendController();
      final t0 = DateTime.now();
      ctrl.onUserSendClicked('what plan am I on?');
      ctrl.onAssistantThinking();
      final elapsed = DateTime.now().difference(t0).inMilliseconds;
      expect(ctrl.value.phase, ChatSendPhase.thinking);
      expect(
        elapsed, lessThan(100),
        reason:
            'the thinking indicator MUST paint under 100ms so the '
            'user feels the app is responsive',
      );
    });

    test('elapsedMsSinceSend advances monotonically', () {
      final ctrl = ChatSendController();
      var t = DateTime(2026, 7, 8, 12, 0, 0);
      ctrl.nowClock = () => t;
      ctrl.onUserSendClicked('hi');
      t = t.add(const Duration(milliseconds: 40));
      ctrl.onAssistantThinking();
      t = t.add(const Duration(milliseconds: 400));
      ctrl.onAssistantFirstResponse();
      expect(ctrl.value.phase, ChatSendPhase.streaming);
      expect(ctrl.value.elapsedMsSinceSend, greaterThanOrEqualTo(440));
      t = t.add(const Duration(milliseconds: 200));
      ctrl.onAssistantDone();
      expect(ctrl.value.phase, ChatSendPhase.done);
      expect(ctrl.value.elapsedMsSinceSend, greaterThanOrEqualTo(640));
    });

    test('error state carries a code, not a raw message', () {
      final ctrl = ChatSendController();
      ctrl.onUserSendClicked('hi');
      ctrl.onAssistantError('backend_timeout');
      expect(ctrl.value.phase, ChatSendPhase.error);
      expect(ctrl.value.errorCode, equals('backend_timeout'));
    });
  });


  group('Part 3 — frontend cache basics', () {
    test('get / put round-trip', () {
      final c = FrontendCache.instance;
      c.put('storage:quota:v1', {'used': 100, 'limit': 1000});
      final v = c.get<Map<String, Object?>>('storage:quota:v1');
      expect(v, isNotNull);
      expect(v!['used'], 100);
    });

    test('cache respects TTL', () {
      final c = FrontendCache.instance;
      var now = DateTime(2026, 7, 8, 12, 0, 0);
      c.nowClock = () => now;
      c.put('storage:quota:v1', 1, ttl: const Duration(seconds: 10));
      expect(c.get<int>('storage:quota:v1'), 1);
      now = now.add(const Duration(seconds: 11));
      expect(c.get<int>('storage:quota:v1'), isNull);
    });

    test('has() honours TTL', () {
      final c = FrontendCache.instance;
      var now = DateTime(2026, 7, 8, 12, 0, 0);
      c.nowClock = () => now;
      c.put('k', 1, ttl: const Duration(seconds: 5));
      expect(c.has('k'), isTrue);
      now = now.add(const Duration(seconds: 6));
      expect(c.has('k'), isFalse);
    });
  });


  group('Part 4 — cache refuses secrets', () {
    test('sensitive-looking key is refused', () {
      final c = FrontendCache.instance;
      for (final k in <String>[
        'crypto:seed_phrase',
        'user:pin_verifier',
        'session_token',
        'crypto:private_key',
        'auth:bearer',
        'x:api_key',
        'stored:mnemonic',
      ]) {
        expect(
          () => c.put(k, 'anything'),
          throwsA(isA<SensitiveDataCachedException>()),
          reason: 'key "$k" must be refused',
        );
      }
    });

    test('sensitive-looking value is refused', () {
      final c = FrontendCache.instance;
      for (final v in <String>[
        'my seed phrase is banana',
        'private key: 0xabc',
        'view key hidden',
      ]) {
        expect(
          () => c.put('safe:key', v),
          throwsA(isA<SensitiveDataCachedException>()),
        );
      }
    });
  });


  group('Part 5 — cache clears on logout / vault switch', () {
    test('clearCacheOnLogout empties everything', () {
      final c = FrontendCache.instance;
      c.put('storage:quota:v1', 1);
      c.put('faq:envelope:x', 'y');
      expect(c.size(), 2);
      clearCacheOnLogout();
      expect(c.size(), 0);
    });

    test('clearCacheOnVaultSwitch clears when vault changes', () {
      final c = FrontendCache.instance;
      c.put('storage:quota:v1', 1);
      clearCacheOnVaultSwitch('vault-A', 'vault-B');
      expect(c.size(), 0);
    });

    test('clearCacheOnVaultSwitch is a no-op when vault is the same',
        () {
      final c = FrontendCache.instance;
      c.put('storage:quota:v1', 1);
      clearCacheOnVaultSwitch('vault-A', 'vault-A');
      expect(c.size(), 1);
    });

    test('invalidatePrefix drops only matching keys', () {
      final c = FrontendCache.instance;
      c.put('crypto:balance:eth', 1);
      c.put('crypto:balance:sol', 2);
      c.put('storage:quota:v1', 3);
      c.invalidatePrefix('crypto:balance:');
      expect(c.get<int>('crypto:balance:eth'), isNull);
      expect(c.get<int>('crypto:balance:sol'), isNull);
      expect(c.get<int>('storage:quota:v1'), 3);
    });
  });


  group('Part 6 — perf trace instrumentation', () {
    test('recordRequest counts and duplicateCount reports excess',
        () {
      final t = PerfTrace.instance;
      t.recordRequest(kRequestCryptoBalance);
      expect(t.duplicateCount(kRequestCryptoBalance), 0);
      t.recordRequest(kRequestCryptoBalance);
      expect(t.duplicateCount(kRequestCryptoBalance), 1);
      t.recordRequest(kRequestCryptoBalance);
      expect(t.duplicateCount(kRequestCryptoBalance), 2);
    });

    test('span records elapsed time', () {
      final t = PerfTrace.instance;
      final result = t.span<int>(kSpanScreenOpenSettings, () => 42);
      expect(result, 42);
      expect(t.spans().length, 1);
      expect(t.spans().first.name, kSpanScreenOpenSettings);
    });

    test('spanAsync awaits and records', () async {
      final t = PerfTrace.instance;
      final f = t.spanAsync<int>(
        kSpanScreenOpenCryptoVault,
        () async {
          await Future<void>.delayed(
            const Duration(milliseconds: 5),
          );
          return 7;
        },
      );
      expect(await f, 7);
      expect(t.spans().length, 1);
    });

    test('refuses sensitive span names', () {
      final t = PerfTrace.instance;
      for (final name in <String>[
        'trace.pin.attempt',
        'trace.seed',
        'trace.mnemonic',
        'trace.private_key',
        'trace.session_token',
      ]) {
        expect(
          () => t.recordRequest(name),
          throwsA(isA<UnsafePerfSpanNameException>()),
          reason: '$name must be refused',
        );
      }
    });

    test('when disabled, span still returns the body result', () {
      final t = PerfTrace.instance;
      t.setEnabledForTests(false);
      final v = t.span<int>('any_name', () => 99);
      expect(v, 99);
      expect(t.spans().length, 0);
    });
  });


  group('Part 7 — no fake performance in production', () {
    test('cache never surfaces expired data as live', () {
      final c = FrontendCache.instance;
      var now = DateTime(2026, 7, 8, 12);
      c.nowClock = () => now;
      c.put('crypto:balance:eth', 100,
          ttl: const Duration(seconds: 5));
      now = now.add(const Duration(seconds: 10));

      expect(c.get<int>('crypto:balance:eth'), isNull);
    });

    test(
      'chat controller only records first-response counter after '
      'assistant actually responded',
      () {
        final ctrl = ChatSendController();
        ctrl.onUserSendClicked('hi');

        expect(
          PerfTrace.instance.requestCount(
            kSpanChatFirstAssistantResponse,
          ),
          0,
        );
        ctrl.onAssistantFirstResponse();
        expect(
          PerfTrace.instance.requestCount(
            kSpanChatFirstAssistantResponse,
          ),
          1,
        );
      },
    );
  });


  group('Part 8 — perf module resilience', () {
    test('empty cache returns null for anything', () {
      final c = FrontendCache.instance;
      expect(c.get<int>('nothing:here'), isNull);
      expect(c.has('nothing:here'), isFalse);
    });

    test('cache is a singleton across imports', () {

      final a = FrontendCache.instance;
      final b = FrontendCache.instance;
      expect(identical(a, b), isTrue);
    });

    test('perf trace is a singleton across imports', () {
      expect(
        identical(PerfTrace.instance, PerfTrace.instance),
        isTrue,
      );
    });
  });


  group('Part 9 — mobile no-overflow smoke on placeholder UI', () {
    testWidgets(
      'placeholder chat UI at 360x800 does not overflow',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(360, 800));
        addTearDown(() async {
          await tester.binding.setSurfaceSize(null);
        });
        final ctrl = ChatSendController();
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: ValueListenableBuilder<ChatSendState>(
                valueListenable: ctrl,
                builder: (context, s, _) {
                  final label = s.phase == ChatSendPhase.idle
                      ? 'ready'
                      : s.phase == ChatSendPhase.userBubbleShown
                          ? 'user bubble shown'
                          : s.phase == ChatSendPhase.thinking
                              ? 'thinking…'
                              : s.phase == ChatSendPhase.streaming
                                  ? 'streaming'
                                  : s.phase == ChatSendPhase.done
                                      ? 'done'
                                      : 'error';
                  return Text(label);
                },
              ),
            ),
          ),
        );
        ctrl.onUserSendClicked('hi');
        await tester.pump();
        ctrl.onAssistantThinking();
        await tester.pump();
        expect(tester.takeException(), isNull);
      },
    );
  });
}
