

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _readLib(String relative) {
  final file = File('lib/$relative');
  expect(file.existsSync(), isTrue,
      reason: 'expected file does not exist: ${file.path}');
  return file.readAsStringSync();
}


String _windowAfter(String src, String marker, {int length = 6000}) {
  final idx = src.indexOf(marker);
  expect(idx, greaterThan(-1),
      reason: 'expected to find marker: $marker');
  return src.substring(idx, (idx + length).clamp(0, src.length));
}


void main() {
  
  
  group('SignupPage', () {
    test('exists as a StatefulWidget', () {
      final src = _readLib('main.dart');
      expect(src, contains('class SignupPage extends StatefulWidget'));
    });

    test('declares the four required form controllers and the '
        'acknowledgement flag', () {
      // ZK signup contract: SignupPage must collect vault_name +
      // PIN + confirm PIN and gate submission on an acknowledgement
      // that VaultAI cannot recover the vault. The variable that
      // holds that acknowledgement is a boolean checked before the
      // ZK registration call. We do NOT bind to the specific
      // variable name (that would be a rename-brittleness trap);
      // we bind to the structural contract: an `acknowledged` /
      // `acknowledge` boolean is declared, is set via a Checkbox,
      // and is enforced (a message about "cannot recover" is
      // surfaced when it is not set).
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class SignupPage', length: 12000);

      expect(window, contains('vaultName'),
          reason: 'SignupPage must collect a vault name (vaultName)');
      expect(window, contains('confirmPin'),
          reason: 'PIN confirmation is mandatory (confirmPin)');

      final ackFlagPattern = RegExp(r'bool\s+acknowledged?\s*=\s*false');
      expect(
        ackFlagPattern.hasMatch(window),
        isTrue,
        reason: 'SignupPage must declare a boolean acknowledgement '
                'flag (matches `bool acknowledged = false` or '
                '`bool acknowledge = false`).',
      );
      expect(
        window,
        contains('Checkbox('),
        reason: 'The acknowledgement must be wired to a Checkbox in '
                'the SignupPage form.',
      );
      expect(
        window,
        contains('cannot recover your vault'),
        reason: 'Submitting without acknowledgement must surface the '
                '"VaultAI cannot recover your vault" enforcement copy.',
      );
    });

    test('shows the irrecoverability warning copy', () {
      
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class SignupPage', length: 9000);
      
      
      expect(
        window,
        contains('cannot recover'),
        reason: 'Signup must surface the "cannot recover your vault" '
                'warning before the acknowledgement checkbox',
      );
    });

    test('calls ZkAuthService.registerVault on submit '
        '(ZK-first registration; no plaintext authSignup)', () {
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class SignupPage', length: 12000);

      // The ZK architecture replaces the plaintext authSignup path
      // with an OPAQUE registration handled by ZkAuthService. The
      // SignupPage submit handler must dispatch to
      // ZkAuthService.registerVault; it must NOT re-introduce a
      // client.authSignup call that would leak the vault_name.
      expect(
        window,
        contains('ZkAuthService('),
        reason: 'SignupPage must construct a ZkAuthService for '
                'OPAQUE-backed ZK registration.',
      );
      expect(
        window,
        contains('.registerVault('),
        reason: 'SignupPage must invoke ZkAuthService.registerVault '
                'on submit (the ZK registration entry point).',
      );
      expect(
        window,
        isNot(contains('client.authSignup(')),
        reason: 'SignupPage must NOT call the plaintext '
                'client.authSignup path — it leaks the vault_name to '
                'the backend and violates the ZK boundary.',
      );
    });

    test('catches RateLimitedException so the 429 message reaches the '
        'UI without the raw status code', () {
      
      
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class SignupPage', length: 12000);
      expect(
        window,
        contains('RateLimitedException'),
        reason: 'SignupPage must catch RateLimitedException',
      );
    });
  });

  
  group('LoginPage', () {
    test('exists as a StatefulWidget', () {
      final src = _readLib('main.dart');
      expect(src, contains('class LoginPage extends StatefulWidget'));
    });

    test('calls authLogin on submit', () {
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(window, contains('authLogin'),
          reason: 'LoginPage must call client.authLogin on submit');
    });

    test('catches InvalidCredentialsException → generic 401 error', () {
      
      
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(
        window,
        contains('InvalidCredentialsException'),
        reason: 'LoginPage must catch InvalidCredentialsException so '
                'the generic 401 message reaches the UI',
      );
    });

    test('does NOT surface a "vault not found" branch', () {
      
      
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(
        window,
        isNot(contains('Vault not found')),
        reason: 'LoginPage must never say "Vault not found" — that '
                'reveals which vault names exist',
      );
    });

    test('api_client.InvalidCredentialsException default message is the '
        'generic phrase', () {
      
      
      final src = _readLib('api_client.dart');
      expect(
        src,
        contains("'Vault name or PIN is incorrect'"),
        reason: 'InvalidCredentialsException default message must be '
                'the generic phrase',
      );
    });

    test('catches RateLimitedException so the 429 message reaches the '
        'UI without the raw status code', () {
      
      
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(
        window,
        contains('RateLimitedException'),
        reason: 'LoginPage must catch RateLimitedException',
      );
    });

    test('surfaces a "New device trusted." snackbar when the backend '
        'response sets new_device_trusted=true', () {
      
      
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(
        window,
        contains('new_device_trusted'),
        reason: 'LoginPage must read new_device_trusted from the auth '
                'response',
      );
      expect(
        window,
        contains('_notifyNewDeviceTrustedIfNeeded'),
        reason: 'LoginPage must invoke the shared snackbar helper',
      );
    });
  });

  
  group('UnlockPage', () {
    test('exists as a StatefulWidget', () {
      final src = _readLib('main.dart');
      expect(src, contains('class UnlockPage extends StatefulWidget'));
    });

    test('reads vault name from AppState.lastVaultName (not a form '
        'field)', () {
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class UnlockPage', length: 9000);
      
      
      expect(
        window,
        contains('lastVaultName'),
        reason: 'UnlockPage must read the vault name from '
                'AppState.lastVaultName',
      );
    });

    test('shows the generic "Welcome back" header (never leaks '
        'vault_name)', () {
      
      
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class UnlockPage', length: 9000);
      expect(window, contains("'Welcome back'"));
      expect(
        window,
        isNot(contains("'Welcome back to ")),
        reason: 'UnlockPage must not interpolate vault_name into its '
                'header — that surface is pre-auth and must stay '
                'vault-name-free.',
      );
      expect(
        window,
        isNot(contains(r"'Welcome back to $")),
        reason: r'no $-interpolated title variant either',
      );
    });

    test('offers a "Use another vault" link that clears the remembered '
        'name and routes to /login', () {
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class UnlockPage', length: 9000);
      expect(
        window.contains('Use another vault') ||
            window.contains('authUseAnotherVault'),
        isTrue,
        reason:
            'UnlockPage must offer a path off the remembered vault '
            '(either literal "Use another vault" or via '
            'AppLocalizations.authUseAnotherVault)',
      );
    });

    test('catches RateLimitedException and surfaces "New device '
        'trusted." snackbar on success', () {
      
      
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class UnlockPage', length: 9000);
      expect(window, contains('RateLimitedException'));
      expect(window, contains('new_device_trusted'));
      expect(window, contains('_notifyNewDeviceTrustedIfNeeded'));
    });

    test('build() body never interpolates a vault-name variable into '
        'a Text widget', () {
      
      
      final src = _readLib('main.dart');
      final classIdx = src.indexOf('class _UnlockPageState');
      expect(classIdx, greaterThan(-1));
      final buildIdx = src.indexOf('Widget build(BuildContext context)', classIdx);
      expect(buildIdx, greaterThan(-1));
      
      
      final lfEnd = src.indexOf('\n}\n', buildIdx);
      final crlfEnd = src.indexOf('\r\n}\r\n', buildIdx);
      int endIdx;
      if (lfEnd == -1) {
        endIdx = crlfEnd;
      } else if (crlfEnd == -1) {
        endIdx = lfEnd;
      } else {
        endIdx = lfEnd < crlfEnd ? lfEnd : crlfEnd;
      }
      final body = src.substring(buildIdx, endIdx == -1 ? src.length : endIdx);

      
      expect(
        body,
        isNot(contains(r'$name')),
        reason: r'no $name interpolation in UnlockPage build body',
      );
      expect(
        body,
        isNot(contains(r'$vaultName')),
        reason: r'no $vaultName interpolation in UnlockPage build body',
      );
      expect(
        body,
        isNot(contains(r'${app.vaultName}')),
        reason: r'no ${app.vaultName} interpolation in UnlockPage '
                'build body',
      );
      expect(
        body,
        isNot(contains(r'${app.lastVaultName}')),
        reason: r'no ${app.lastVaultName} interpolation in '
                'UnlockPage build body',
      );
      expect(
        body,
        isNot(contains('Text(name')),
        reason: 'no bare Text(name) widget in UnlockPage build body',
      );
    });
  });

  
  group('Post-auth account labels never fall back to vault_name', () {
    test('TopNavBar account labels use displayUsername ?? "VaultAI '
        'User", never vaultName', () {
      final src = _readLib('main.dart');
      final classIdx = src.indexOf('class TopNavBar');
      expect(classIdx, greaterThan(-1));
      
      final window = src.substring(
        classIdx,
        (classIdx + 12000).clamp(0, src.length),
      );
      
      expect(
        window,
        contains("'VaultAI User'"),
        reason: 'TopNavBar must use the generic "VaultAI User" '
                'fallback in the displayUsername chain.',
      );
      
      expect(
        window,
        isNot(contains('displayUsername ?? app.vaultName')),
        reason: 'TopNavBar must not fall back to vault_name in '
                'account labels — vault_name is the login handle.',
      );
      expect(
        window,
        isNot(contains("?? app.vaultName ?? 'Account'")),
        reason: 'legacy three-step fallback chain must be removed',
      );
    });
  });

  
  group('_notifyNewDeviceTrustedIfNeeded helper', () {
    test('is a top-level void function defined in main.dart', () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains('void _notifyNewDeviceTrustedIfNeeded(bool flag)'),
        reason: 'helper must exist with the bool gate baked in',
      );
    });

    test('shows the canonical "New device trusted." copy', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('void _notifyNewDeviceTrustedIfNeeded');
      expect(idx, greaterThan(-1));
      final window = src.substring(
        idx,
        (idx + 1500).clamp(0, src.length),
      );
      expect(
        window,
        contains("'New device trusted.'"),
        reason: 'snackbar text must be the user-facing canonical phrase',
      );
    });

    test('short-circuits when flag is false', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('void _notifyNewDeviceTrustedIfNeeded');
      final window = src.substring(
        idx,
        (idx + 1500).clamp(0, src.length),
      );
      expect(
        window,
        contains('if (!flag) return;'),
        reason: 'helper must no-op when the backend response says false',
      );
    });

    test('routes through rootScaffoldMessengerKey so the snackbar '
        'outlives the pushReplacementNamed to /chat', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('void _notifyNewDeviceTrustedIfNeeded');
      final window = src.substring(
        idx,
        (idx + 1500).clamp(0, src.length),
      );
      expect(
        window,
        contains('rootScaffoldMessengerKey'),
        reason: 'must use the root messenger — the auth page is about '
                'to be popped',
      );
    });
  });

  
  group('AppState auth fields', () {
    test('declares sessionToken, vaultId, vaultName, lastVaultName, '
        'displayUsername', () {
      final src = _readLib('main.dart');
      expect(src, contains('String? sessionToken'));
      expect(src, contains('String? vaultId'));
      expect(src, contains('lastVaultName'));
      expect(src, contains('displayUsername'));
    });

    test('does NOT carry a top-level email field', () {
      final src = _readLib('main.dart');
      
      
      final stateIdx = src.indexOf('class AppState extends ChangeNotifier');
      expect(stateIdx, greaterThan(-1));
      final stateEnd = src.indexOf('\n}', stateIdx);
      expect(stateEnd, greaterThan(stateIdx));
      final body = src.substring(stateIdx, stateEnd);
      expect(
        body,
        isNot(contains('String? email;')),
        reason: 'AppState must not carry an email field as identity',
      );
    });

    test('signOut() exists and calls authLogout', () {
      final src = _readLib('main.dart');
      expect(src, contains('Future<void> signOut'));
      
      final idx = src.indexOf('Future<void> signOut');
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(window, contains('authLogout'));
    });
  });

  
  group('api_client.dart 429 → RateLimitedException', () {
    test('RateLimitedException is defined with the canonical message',
        () {
      final src = _readLib('api_client.dart');
      expect(
        src,
        contains('class RateLimitedException implements Exception'),
        reason: 'typed exception must exist',
      );
      expect(
        src,
        contains(
          "'Too many attempts. Please wait a few minutes and try again.'",
        ),
        reason: 'default message must be the canonical generic phrase '
                '— never the backend literal',
      );
    });

    test('authSignup maps HTTP 429 to RateLimitedException', () {
      final src = _readLib('api_client.dart');
      final idx = src.indexOf('Future<Map<String, dynamic>> authSignup');
      expect(idx, greaterThan(-1));
      
      
      final body = src.substring(idx, (idx + 5000).clamp(0, src.length));
      expect(
        body,
        contains('statusCode == 429'),
        reason: 'authSignup must branch on the 429 status',
      );
      expect(
        body,
        contains('_rateLimitedFromBody'),
        reason: 'authSignup must throw via the shared helper so the '
                'reset_in_seconds field is parsed',
      );
    });

    test('authLogin maps HTTP 429 to RateLimitedException', () {
      final src = _readLib('api_client.dart');
      final idx = src.indexOf('Future<Map<String, dynamic>> authLogin');
      expect(idx, greaterThan(-1));
      final body = src.substring(idx, (idx + 5000).clamp(0, src.length));
      expect(body, contains('statusCode == 429'));
      expect(body, contains('_rateLimitedFromBody'));
    });

    test('_rateLimitedFromBody never surfaces the backend literal '
        'message', () {
      
      
      final src = _readLib('api_client.dart');
      final idx = src.indexOf('_rateLimitedFromBody(String body)');
      expect(idx, greaterThan(-1));
      final body = src.substring(idx, (idx + 1500).clamp(0, src.length));
      expect(
        body,
        contains('return RateLimitedException(resetInSeconds: resetIn);'),
        reason: 'helper must rely on RateLimitedException default '
                'message — never pass message: detail["message"]',
      );
    });
  });

  
  group('display_username plumbing', () {
    test('LoginPage reads display_username from the auth response and '
        'forwards it through setSession', () {
      final src = _readLib('main.dart');
      // 15k is enough to cover the LoginPage class + its state class
      // + the submit body. The pre-2026-07-20 build fit in 9k; the
      // preflight + diagnostic vlogs added ~50 lines.
      final window = _windowAfter(src, 'class LoginPage', length: 15000);
      expect(
        window,
        contains("result['display_username']"),
        reason: 'LoginPage must read display_username off the response',
      );
      expect(
        window,
        contains('displayUsernameValue:'),
        reason: 'LoginPage must forward it through setSession',
      );
    });

    test('UnlockPage reads display_username from the auth response', () {
      final src = _readLib('main.dart');
      final window = _windowAfter(src, 'class UnlockPage', length: 9000);
      expect(window, contains("result['display_username']"));
      expect(window, contains('displayUsernameValue:'));
    });

    test('AppState.setSession persists displayUsername when present', () {
      
      
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> setSession(');
      expect(idx, greaterThan(-1));
      final body = src.substring(idx, (idx + 2500).clamp(0, src.length));
      expect(
        body,
        contains('displayUsername = displayUsernameValue'),
        reason: 'setSession must assign the new displayUsername',
      );
    });
  });
}
