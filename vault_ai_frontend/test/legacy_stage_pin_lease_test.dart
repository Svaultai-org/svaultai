import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_stage_pin_lease.dart';

void main() {
  test('migration PIN lease expires and clears synthetic credential', () {
    var now = DateTime.utc(2026, 11, 4);
    final lease = LegacyStagePinLease(
      'synthetic-pin-only',
      lifetime: const Duration(minutes: 2),
      now: () => now,
    );
    expect(lease.requirePin(), 'synthetic-pin-only');
    now = now.add(const Duration(minutes: 2));
    expect(lease.requirePin, throwsStateError);
    lease.clear();
    expect(lease.requirePin, throwsStateError);
  });

  test('migration PIN lease cannot outlive its five minute limit', () {
    expect(
      () => LegacyStagePinLease(
        'synthetic-pin-only',
        lifetime: const Duration(minutes: 6),
      ),
      throwsArgumentError,
    );
  });

  test('owner renewal asks again only after the bounded lease expires',
      () async {
    var now = DateTime.utc(2026, 11, 7);
    var prompts = 0;
    final answers = <String?>['111111', '222222', null];
    final renewal = RenewableLegacyStagePinLease(
      promptPin: () async => answers[prompts++],
      lifetime: const Duration(minutes: 1),
      now: () => now,
    );
    expect(await renewal.requireOrPrompt(), '111111');
    expect(renewal.requireActive, returnsNormally);
    now = now.add(const Duration(seconds: 59));
    expect(await renewal.requireOrPrompt(), '111111');
    expect(prompts, 1);
    now = now.add(const Duration(seconds: 1));
    expect(renewal.requireActive, throwsStateError);
    expect(await renewal.requireOrPrompt(), '222222');
    expect(prompts, 2);
    now = now.add(const Duration(minutes: 1));
    expect(await renewal.requireOrPrompt(), isNull);
    expect(prompts, 3);
    expect(renewal.requireActive, throwsStateError);
    renewal.clear();
    await expectLater(renewal.requireOrPrompt(), throwsStateError);
  });

  test('closing while a renewal prompt is open cannot revive its PIN',
      () async {
    final entry = Completer<String?>();
    final renewal = RenewableLegacyStagePinLease(
      promptPin: () => entry.future,
    );
    final pending = renewal.requireOrPrompt();
    renewal.clear();
    entry.complete('111111');
    await expectLater(pending, throwsStateError);
    expect(renewal.requireActive, throwsStateError);
  });

  test('simultaneous proof requests share one owner prompt', () async {
    final entry = Completer<String?>();
    var prompts = 0;
    final renewal = RenewableLegacyStagePinLease(
      promptPin: () {
        prompts++;
        return entry.future;
      },
    );
    final first = renewal.requireOrPrompt();
    final second = renewal.requireOrPrompt();
    expect(prompts, 1);
    entry.complete('111111');
    expect(await first, '111111');
    expect(await second, '111111');
    expect(renewal.requireActive, returnsNormally);
    renewal.clear();
  });

  test(
    'a live session can finish an existing grant after PIN clears, but cannot renew it',
    () {
      var now = DateTime.utc(2026, 11, 5);
      var activeSession = true;
      var expiredSignals = 0;
      final lease = LegacyStagePinLease(
        'synthetic-pin-only',
        lifetime: const Duration(minutes: 1),
        now: () => now,
      );
      final guard = LegacyStageSessionGuard(
        pinLease: lease,
        requireSession: () {
          if (!activeSession) throw StateError('session ended');
        },
        onPinLeaseExpired: () => expiredSignals++,
      );

      expect(guard.requirePinForProof(), 'synthetic-pin-only');
      guard.requireProofCompletion();
      now = now.add(const Duration(minutes: 1));
      expect(guard.requireRequest, returnsNormally);
      expect(guard.requirePinForProof, throwsStateError);
      expect(expiredSignals, 1);
      expect(lease.requirePin, throwsStateError);
      activeSession = false;
      expect(guard.requireRequest, throwsStateError);
      expect(guard.requirePinForProof, throwsStateError);
      expect(expiredSignals, 1);
      lease.clear();
    },
  );

  test('a proof finishing after the PIN lease expires is discarded', () {
    var now = DateTime.utc(2026, 11, 5);
    var expiredSignals = 0;
    final lease = LegacyStagePinLease(
      'synthetic-pin-only',
      lifetime: const Duration(minutes: 1),
      now: () => now,
    );
    final guard = LegacyStageSessionGuard(
      pinLease: lease,
      requireSession: () {},
      onPinLeaseExpired: () => expiredSignals++,
    );
    expect(guard.requirePinForProof(), 'synthetic-pin-only');
    now = now.add(const Duration(minutes: 1));
    expect(guard.requireProofCompletion, throwsStateError);
    expect(expiredSignals, 1);
    lease.clear();
  });
}
