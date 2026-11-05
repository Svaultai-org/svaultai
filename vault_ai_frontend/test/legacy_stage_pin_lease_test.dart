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
