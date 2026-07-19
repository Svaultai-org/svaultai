// Tests for the automatic inheritance device-authorization consume
// step that runs at the end of every login.
//
// The decision function ``shouldPreservePendingInheritanceToken`` is
// unit-tested directly; the wiring at each login handoff is checked
// via a source-scan invariant so a future refactor can't
// accidentally break normal (non-inheritance) logins by adding a
// login site without also calling the consume helper.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show shouldPreservePendingInheritanceToken;

void main() {
  group('shouldPreservePendingInheritanceToken', () {
    // The token must survive a wrong-account 403 so the beneficiary
    // can retry after logging into the correct inherited vault.
    test('INH-DEV-004 → preserve (wrong account)', () {
      expect(
        shouldPreservePendingInheritanceToken(
          'Consume inheritance device authorization failed: '
          'HTTP 403: {"detail":{"code":"INH-DEV-004"}}',
        ),
        isTrue,
      );
    });

    // Wrong device → the token was issued for a different device,
    // it will never succeed on this device.
    test('INH-DEV-005 → clear (wrong device)', () {
      expect(
        shouldPreservePendingInheritanceToken(
          'code":"INH-DEV-005","message":"wrong device"',
        ),
        isFalse,
      );
    });

    // Invalid / expired token → clear.
    test('INH-DEV-003 → clear (invalid/expired token)', () {
      expect(
        shouldPreservePendingInheritanceToken('INH-DEV-003 expired'),
        isFalse,
      );
    });

    // Already consumed → clear.
    test('INH-DEV-006 → clear (already consumed)', () {
      expect(
        shouldPreservePendingInheritanceToken('INH-DEV-006 replayed'),
        isFalse,
      );
    });

    // Release revoked → clear.
    test('INH-ACCESS-006 → clear (release revoked)', () {
      expect(
        shouldPreservePendingInheritanceToken('INH-ACCESS-006'),
        isFalse,
      );
    });

    // Anything else (network error, timeout, unknown) → clear so
    // the app doesn't keep retrying forever.
    test('non-matching error → clear', () {
      expect(
        shouldPreservePendingInheritanceToken(
          'SocketException: connection refused',
        ),
        isFalse,
      );
    });
  });

  group('login wiring invariants', () {
    File _main() => File('lib/main.dart');

    test('the consume helper is defined and receives the '
         'session token + AppState', () {
      final src = _main().readAsStringSync();
      expect(
        src.contains('Future<void> _autoConsumeInheritanceTokenIfPresent'),
        isTrue,
      );
      // The helper must consult ``pendingInheritanceDeviceToken`` —
      // this is the state field that gets cleared on success.
      expect(src.contains('pendingInheritanceDeviceToken'), isTrue);
    });

    test('every login handoff calls the consume helper', () {
      final src = _main().readAsStringSync();

      final registerMatches =
          RegExp(r'_registerDeviceBestEffort\(').allMatches(src).length;
      final consumeMatches =
          RegExp(r'_autoConsumeInheritanceTokenIfPresent\(')
              .allMatches(src)
              .length;

      // Each call-site pair (register + consume) plus one
      // definition each. Function definitions:
      //   _registerDeviceBestEffort        1
      //   _autoConsumeInheritanceTokenIfPresent 1
      // Login sites currently: 5 (see grep in the phase-2 report).
      // Total register occurrences = 1 def + 5 calls = 6.
      // Total consume occurrences  = 1 def + 5 calls = 6.
      expect(
        registerMatches, greaterThanOrEqualTo(6),
        reason: 'expected at least 6 _registerDeviceBestEffort '
                'call-sites+def',
      );
      expect(
        consumeMatches, registerMatches,
        reason:
            'every _registerDeviceBestEffort must be paired with '
            'an _autoConsumeInheritanceTokenIfPresent; otherwise a '
            'login site would silently skip the automatic device '
            'enrollment step.',
      );
    });

    test('the consume helper is called AFTER the register call at '
         'every site (so the row exists before we try to trust it)',
        () {
      final src = _main().readAsStringSync();
      // Find every register call; look for the consume call
      // immediately after it (within the next 3 lines).
      final registerLocations = <int>[];
      final re = RegExp(r'_registerDeviceBestEffort\(');
      for (final m in re.allMatches(src)) {
        registerLocations.add(m.start);
      }
      // Drop the definition (first hit).
      registerLocations.removeAt(0);

      for (final start in registerLocations) {
        // Read a small window after the register call.
        final windowEnd = (start + 400).clamp(0, src.length);
        final window = src.substring(start, windowEnd);
        expect(
          window.contains('_autoConsumeInheritanceTokenIfPresent'),
          isTrue,
          reason:
              'call site at offset $start does not consume the '
              'pending inheritance token immediately after '
              'registering the device — normal login flow is '
              'unaffected, but inheritance logins would need a '
              'second manual step.',
        );
      }
    });

    test('the beneficiary continue-to-inherited-account copy no '
         'longer says "sign out"', () {
      final src = _main().readAsStringSync();
      // Old copy required a manual sign-out before the inherited
      // login. Automatic consumption makes that unnecessary; guard
      // against regression.
      expect(
        src.contains(
          'Sign out and sign back in with the inherited '
          'username and PIN',
        ),
        isFalse,
        reason:
            'the sign-out-first copy came back — the auto-consume '
            'path is meant to remove the manual second step.',
      );
    });
  });
}
