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
}
