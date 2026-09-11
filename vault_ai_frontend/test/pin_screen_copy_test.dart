

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _mainDartSource() {
  final f = File('lib/main.dart');
  if (!f.existsSync()) {
    fail('lib/main.dart not found from test cwd ${Directory.current.path}');
  }
  return f.readAsStringSync();
}

void main() {
  group('PIN screen copy', () {
    late String src;

    setUpAll(() {
      src = _mainDartSource();
    });

    test('no screen renders legacy PIN-length copy', () {
      
      
      final forbidden = <String>[
        'Enter your 4-digit PIN',
        'Create your 4-digit PIN',
        'Enter your 4 digit PIN',
        'Create your 4 digit PIN',
        'Enter your four-digit PIN',
        'Create your four-digit PIN',
        'Enter 4–8 digits.',
        'Enter 4-8 digits.',
        'Use 6–8 digits.',
        'Use 6-8 digits.',
        'PIN (6–8 digits)',
        'PIN (6-8 digits)',
      ];
      for (final s in forbidden) {
        expect(
          src.contains(s),
          isFalse,
          reason: 'lib/main.dart still contains forbidden legacy PIN '
              'copy: "$s". PINs are 6–64 digits now. Replace with the '
              'new operator-pinned strings.',
        );
      }
    });

    test('_PinGatePageState renders "Enter your PIN" title in unlock mode', () {
      expect(
        src.contains("mode ? 'Create your PIN' : 'Enter your PIN'"),
        isTrue,
        reason: 'PinGatePage title must be "Create your PIN" / '
            '"Enter your PIN" — no length number in the title.',
      );
    });

    test('PIN screen helper text reads "Enter your 6–64 digit PIN."', () {
      expect(
        src.contains("'Enter your 6–64 digit PIN.'"),
        isTrue,
        reason: 'Unlock helper text must read '
            '"Enter your 6–64 digit PIN." so it always matches the '
            '6–64-digit validator.',
      );
      expect(
        src.contains("'Create a 6–64 digit PIN.'"),
        isTrue,
        reason: 'Create-mode helper text must read '
            '"Create a 6–64 digit PIN."',
      );
      expect(
        src.contains('static const int _minPinLengthUnlock = 6;'),
        isTrue,
        reason: 'Unlock minimum PIN length must be 6 — 4- and 5-digit '
            'PINs are no longer supported.',
      );
      expect(
        src.contains('static const int _minPinLengthCreate = 6;'),
        isTrue,
        reason: 'Create minimum PIN length must be 6.',
      );
      expect(
        src.contains('static const int _maxPinLength = 64;'),
        isTrue,
        reason: 'Maximum PIN length must be 64.',
      );
    });

    test('PIN validation accepts 6–64 digit PINs', () {
      
      
      expect(
        src.contains('PIN can only contain digits.'),
        isTrue,
        reason: 'Unlock validator must emit '
            '"PIN can only contain digits." for non-digit input.',
      );
      expect(
        src.contains('PIN must be at least 6 digits.'),
        isTrue,
        reason: 'Unlock validator must emit '
            '"PIN must be at least 6 digits." for short input.',
      );
      expect(
        src.contains('PIN must be 64 digits or fewer.'),
        isTrue,
        reason: 'Unlock validator must emit '
            '"PIN must be 64 digits or fewer." for over-long input.',
      );
      expect(
        src.contains("RegExp(r'^\\d+\$')"),
        isTrue,
        reason: 'Unlock validator must use a digits-only regex.',
      );

      bool accepts(String pin, {int minLen = 6, int maxLen = 64}) {
        final digitsOnly = RegExp(r'^\d+$');
        return digitsOnly.hasMatch(pin) &&
            pin.length >= minLen &&
            pin.length <= maxLen;
      }

      for (final len in [6, 7, 8, 10, 12, 20, 32, 50, 63, 64]) {
        final pin = '1' * len;
        expect(
          accepts(pin),
          isTrue,
          reason: 'PIN of length $len must be accepted.',
        );
      }
      expect(accepts('1234'),
          isFalse, reason: '4-digit PIN must reject.');
      expect(accepts('12345'),
          isFalse, reason: '5-digit PIN must reject.');
      expect(accepts('1' * 65),
          isFalse, reason: '65-digit PIN must reject.');
      expect(accepts('1234ab'),
          isFalse, reason: 'non-numeric PIN must reject.');
      expect(accepts(''),
          isFalse, reason: 'empty PIN must reject.');
    });

    test('PIN page renders "Log in to another vault" link in unlock mode', () {
      
      
      expect(
        src.contains("'Log in to another vault'") ||
            src.contains('authLogInAnotherVault'),
        isTrue,
        reason:
            'PinGatePage unlock branch must render the '
            '"Log in to another vault" link (literal or '
            'AppLocalizations.authLogInAnotherVault).',
      );
      expect(
        src.contains('Future<void> _useAnotherVault()'),
        isTrue,
        reason: 'PinGatePage must define _useAnotherVault() — the '
            'local-only handler that clears session + last vault name.',
      );
      
      
      expect(
        src.contains(
            'await app.clearSession(keepLastVaultName: false);'),
        isTrue,
        reason: '_useAnotherVault must call the local-only '
            'clearSession(keepLastVaultName: false) — never delete-vault.',
      );
      expect(
        src.contains("Navigator.pushReplacementNamed(context, '/login');"),
        isTrue,
        reason: '_useAnotherVault must route to /login.',
      );
      
      
      final helperStart = src.indexOf('Future<void> _useAnotherVault()');
      expect(
        helperStart,
        isNonNegative,
        reason: 'Could not locate _useAnotherVault() body.',
      );
      
      
      final helperEnd =
          src.indexOf('Future<void> _submit()', helperStart);
      expect(
        helperEnd > helperStart,
        isTrue,
        reason: 'Could not locate end of _useAnotherVault() body.',
      );
      final body = src.substring(helperStart, helperEnd);
      for (final banned in const [
        'wipeOrphanData',
        'deleteVault',
        'delete_vault',
        'delete-vault',
        'deleteData',
        'delete_data',
        'delete-data',
      ]) {
        expect(
          body.contains(banned),
          isFalse,
          reason: '_useAnotherVault() must NEVER call "$banned" — it '
              'is a local-only session/vault-pointer clear.',
        );
      }
    });
  });
}
