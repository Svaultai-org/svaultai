

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _mainSrc() {
  final f = File('lib/main.dart');
  expect(f.existsSync(), isTrue,
      reason: 'lib/main.dart not found from ${Directory.current.path}');
  return f.readAsStringSync();
}

String _classBody(String src, String className) {
  final start = src.indexOf('class $className');
  expect(start, greaterThan(-1), reason: 'class $className not found');
  
  var depth = 0;
  var firstBrace = -1;
  for (var i = start; i < src.length; i++) {
    final ch = src[i];
    if (ch == '{') {
      if (firstBrace == -1) firstBrace = i;
      depth++;
    } else if (ch == '}') {
      depth--;
      if (depth == 0 && firstBrace != -1) {
        return src.substring(start, i + 1);
      }
    }
  }
  fail('Could not isolate body of class $className');
}

void main() {
  late String src;
  setUpAll(() => src = _mainSrc());

  
  group('PIN length policy strings', () {
    test('new operator-pinned UI copy is present', () {
      const required = <String>[
        'Enter your 6–64 digit PIN.',
        'Create a 6–64 digit PIN.',
        'PIN must be at least 6 digits.',
        'PIN must be 64 digits or fewer.',
        'PIN can only contain digits.',

        'PIN (6–64 digits)',
      ];
      for (final needle in required) {
        expect(src.contains(needle), isTrue,
            reason: 'lib/main.dart MUST contain the operator-pinned '
                'string: "$needle"');
      }


      expect(
        src.contains('Log in to another vault') ||
            src.contains('authLogInAnotherVault'),
        isTrue,
        reason:
            'lib/main.dart MUST expose the "Log in to another vault" '
            'link (literal or AppLocalizations.authLogInAnotherVault).',
      );
    });

    test('legacy 4-8 / 6-8 PIN copy is gone', () {
      const forbidden = <String>[
        'Enter 4–8 digits.',
        'Enter 4-8 digits.',
        'Use 6–8 digits.',
        'Use 6-8 digits.',
        'PIN (6–8 digits)',
        'PIN (6-8 digits)',
        'Enter your 4-digit PIN',
        
        
        'Enter your PIN to unlock.',
      ];
      for (final needle in forbidden) {
        expect(src.contains(needle), isFalse,
            reason: 'lib/main.dart still contains forbidden legacy '
                'string: "$needle"');
      }
    });
  });

  
  group('PIN TextField maxLength', () {
    test('no surviving "maxLength: 8" on the PIN entry surfaces', () {
      
      
      final signup = _classBody(src, '_SignupPageState');
      final login = _classBody(src, '_LoginPageState');
      final unlock = _classBody(src, '_UnlockPageState');
      final pingate = _classBody(src, '_PinGatePageState');

      for (final entry in <String, String>{
        '_SignupPageState':  signup,
        '_LoginPageState':   login,
        '_UnlockPageState':  unlock,
        '_PinGatePageState': pingate,
      }.entries) {
        expect(
          entry.value.contains('maxLength: 8'),
          isFalse,
          reason: '${entry.key} must not pin maxLength: 8 anymore. '
              'PIN length is 6–64; use maxLength: 64 (or _maxPinLength).',
        );
        expect(
          entry.value.contains('maxLength: 4'),
          isFalse,
          reason: '${entry.key} must not pin maxLength: 4 anymore.',
        );
      }
    });

    test('SignupPage / LoginPage / UnlockPage use maxLength: 64 or '
        '_maxPinLength', () {
      final signup = _classBody(src, '_SignupPageState');
      final login = _classBody(src, '_LoginPageState');
      final unlock = _classBody(src, '_UnlockPageState');

      for (final entry in <String, String>{
        '_SignupPageState': signup,
        '_LoginPageState':  login,
        '_UnlockPageState': unlock,
      }.entries) {
        final ok = entry.value.contains('maxLength: 64') ||
            entry.value.contains('maxLength: _maxPinLength');
        expect(
          ok, isTrue,
          reason: '${entry.key} must bind its PIN TextField to '
              'maxLength: 64 (literal) or maxLength: _maxPinLength '
              '(_maxPinLength = 64).',
        );
      }
    });

    test('_PinGatePageState binds the PIN TextField via _maxPinLength', () {
      final body = _classBody(src, '_PinGatePageState');
      expect(
        body.contains('maxLength: _maxPinLength'),
        isTrue,
        reason: '_PinGatePageState must bind its PIN TextField via '
            'maxLength: _maxPinLength (_maxPinLength = 64).',
      );
    });
  });

  
  group('PinGatePage "Log in to another vault" link', () {
    test('PinGatePage carries the link in its unlock branch', () {
      final body = _classBody(src, '_PinGatePageState');
      expect(
        body.contains("'Log in to another vault'") ||
            body.contains('authLogInAnotherVault'),
        isTrue,
        reason:
            '_PinGatePageState must render the '
            '"Log in to another vault" link in its unlock branch '
            '(literal or AppLocalizations.authLogInAnotherVault).',
      );
      
      expect(
        body.contains('onPressed: _submitting ? null : _useAnotherVault'),
        isTrue,
        reason: 'The "Log in to another vault" link must be wired to '
            '_useAnotherVault and disabled while submitting.',
      );
    });

    test('_useAnotherVault is local-only — no delete-vault / data APIs',
        () {
      final body = _classBody(src, '_PinGatePageState');
      final helperStart = body.indexOf('Future<void> _useAnotherVault()');
      expect(helperStart, greaterThan(-1),
          reason: '_useAnotherVault() must exist on _PinGatePageState.');
      
      
      final helperEnd =
          body.indexOf('Future<void> _submit()', helperStart);
      expect(helperEnd > helperStart, isTrue,
          reason: 'Could not locate end of _useAnotherVault() body.');
      final helperBody = body.substring(helperStart, helperEnd);

      expect(
        helperBody.contains('clearSession(keepLastVaultName: false)'),
        isTrue,
        reason: '_useAnotherVault must call '
            'clearSession(keepLastVaultName: false) — the local-only '
            'session + last-vault-name clear.',
      );
      expect(
        helperBody.contains('_scheduleLoginReplacement()'),
        isTrue,
        reason: '_useAnotherVault must schedule the guarded /login route.',
      );

      for (final banned in const <String>[
        'wipeOrphanData',
        'deleteVault',
        'delete-vault',
        'delete_vault',
        'deleteData',
        'delete-data',
        'delete_data',
        'authLogout',
      ]) {
        expect(
          helperBody.contains(banned),
          isFalse,
          reason: '_useAnotherVault must NEVER call "$banned" — it '
              'is a local-only session / vault-pointer clear.',
        );
      }
    });
  });

  group('shared switch-vault route', () {
    test('vault selector delegates through one AppState transition', () {
      final switcher = _classBody(src, '_VaultSwitcher');
      expect(
        RegExp(r'app\.requestSwitchVault\(').allMatches(switcher).length,
        1,
      );
      expect(switcher, isNot(contains('Navigator.')));

      final appState = _classBody(src, 'AppState');
      final start = appState.indexOf('Future<void> requestSwitchVault(');
      final end = appState.indexOf('bool handleApiException(', start);
      expect(start, greaterThan(-1));
      expect(end, greaterThan(start));
      final transition = appState.substring(start, end);
      expect(transition, contains('userFacingVaultNameOrNull(newVaultName)'));
      expect(transition, contains('_VaultCrypto.clearCache(currentVaultId)'));
      expect(transition, contains("pushNamedAndRemoveUntil(context, '/pin'"));
      expect(transition, isNot(contains('VaultAIClient(')));
      expect(transition, isNot(contains('deleteVault')));
    });
  });


  group('PIN validator predicate (mirrors _PinGatePageState._submit)', () {
    String? validate(String pin) {
      final digitsOnly = RegExp(r'^\d+$');
      if (!digitsOnly.hasMatch(pin)) return 'PIN can only contain digits.';
      if (pin.length < 6) return 'PIN must be at least 6 digits.';
      if (pin.length > 64) return 'PIN must be 64 digits or fewer.';
      return null;
    }

    test('rejects 4-digit PIN', () {
      expect(validate('1234'), 'PIN must be at least 6 digits.');
    });

    test('rejects 5-digit PIN', () {
      expect(validate('12345'), 'PIN must be at least 6 digits.');
    });

    test('accepts every length in [6, 64]', () {
      for (final n in [6, 7, 8, 10, 16, 32, 50, 63, 64]) {
        expect(validate('1' * n), isNull,
            reason: 'PIN of length $n must be accepted.');
      }
    });

    test('rejects 65-digit PIN', () {
      expect(validate('1' * 65), 'PIN must be 64 digits or fewer.');
    });

    test('rejects non-digit PIN', () {
      expect(validate('1234ab'), 'PIN can only contain digits.');
    });

    test('rejects empty PIN as non-digit', () {
      expect(validate(''), 'PIN can only contain digits.');
    });
  });
}
