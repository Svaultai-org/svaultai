// Regression tests for the ed825aa "signup succeeds → redirects
// to PIN" / "existing login → 'Vault name or PIN is incorrect'"
// bug.
//
// Root cause: the crypto cache was populated with
//   _VaultCrypto._ck(vaultId, vaultHandle)   // VLT-XXXX-...
// but the AppState.unlocked invariant getter looks it up with
//   _VaultCrypto.hasKeyFor(vaultId, vaultName)   // "Alexa"
// Under the corrected identity model, ``AppState._vaultName``
// holds the user-typed vault name (e.g. "Alexa"), not the VLT
// handle. The two strings differ; the lookup missed; unlocked
// returned false; the router redirected to /pin. UnlockPage's
// classifier also treated a non-VLT string as "must be legacy"
// and tried /auth/login, which 401'd for ZK-adopted accounts
// with "Vault name or PIN is incorrect".
//
// This suite locks the alignment so it cannot regress silently.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('Crypto cache producer / consumer alignment', () {
    test(
        'the ``unlocked`` invariant getter reads the cache under '
        '(vaultId, vaultName)', () {
      final src = _read('lib/main.dart');
      // Anchor: bool get unlocked { ... hasKeyFor(vaultId: vId,
      // vaultName: vName) ... }
      final idx = src.indexOf('bool get unlocked {');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 800).clamp(0, src.length));
      expect(
        window.contains(
          '_VaultCrypto.hasKeyFor(vaultId: vId, vaultName: vName)',
        ),
        isTrue,
      );
    });

    test(
        'SignupPage populates the cache under (vaultId, vaultName), '
        'never (vaultId, vaultHandle)', () {
      final src = _read('lib/main.dart');
      final signupIdx = src.indexOf('class _SignupPageState');
      final endIdx =
          src.indexOf('Widget build(BuildContext context)', signupIdx);
      final window = src.substring(signupIdx, endIdx);
      // Positive: uses the local ``vaultName`` variable (which is
      // vaultNameCtrl.text.trim() — the user-typed name).
      expect(
        window.contains('_VaultCrypto._ck(result.vaultId, vaultName)'),
        isTrue,
        reason: 'signup cache key must match what unlocked reads — '
            'AppState._vaultName is the user-typed vault name',
      );
      // Negative: the retired handle-keyed populate must be gone.
      expect(
        window.contains('_VaultCrypto._ck(result.vaultId, result.vaultHandle)'),
        isFalse,
        reason: 'the pre-fix key format populated cache entries the '
            'invariant getter could not find, producing the '
            '"signup redirects to PIN" symptom',
      );
      // setActiveVault must also use the vault name (not the
      // handle), so the ambient decrypt/encrypt calls reach the
      // right key.
      expect(
        RegExp(
          r'_VaultCrypto\.setActiveVault\(\s*'
          r'vaultId:\s*result\.vaultId,\s*'
          r'vaultName:\s*vaultName,\s*\)',
        ).hasMatch(window),
        isTrue,
      );
    });

    test('LoginPage populates the cache under (vaultId, resolvedVaultName)',
        () {
      final src = _read('lib/main.dart');
      final loginIdx = src.indexOf('class _LoginPageState');
      final endIdx = src.indexOf('class UnlockPage', loginIdx);
      final window = src.substring(loginIdx, endIdx);
      // Positive: uses ``resolvedVaultName`` — the same value
      // handed to setSession.
      expect(
        RegExp(
          r'_VaultCrypto\._ck\(\s*loginResult\.vaultId,\s*resolvedVaultName\)',
        ).hasMatch(window),
        isTrue,
        reason: 'login cache key must equal the value setSession '
            'stored as AppState.vaultName',
      );
      expect(
        RegExp(
          r'_VaultCrypto\._ck\(\s*loginResult\.vaultId,\s*loginResult\.vaultHandle\)',
        ).hasMatch(window),
        isFalse,
      );
    });

    test('UnlockPage populates the cache under (vaultId, resolvedVaultName)',
        () {
      final src = _read('lib/main.dart');
      final unlockIdx = src.indexOf('class _UnlockPageState');
      final endIdx = src.indexOf('class PinGatePage', unlockIdx);
      final window = src.substring(unlockIdx, endIdx);
      expect(
        RegExp(
          r'_VaultCrypto\._ck\(\s*loginResult\.vaultId,\s*resolvedVaultName\)',
        ).hasMatch(window),
        isTrue,
      );
      expect(
        RegExp(
          r'_VaultCrypto\._ck\(\s*loginResult\.vaultId,\s*loginResult\.vaultHandle\)',
        ).hasMatch(window),
        isFalse,
      );
    });
  });

  group(
      'UnlockPage handles user-typed vault name (not just VLT '
      'handle) — regression for "Vault name or PIN is incorrect"', () {
    test(
        'UnlockPage submits via ZK loginVault(vaultName:) when the '
        'cached lastVaultName is a user-typed name, and via '
        'loginVault(vaultHandle:) only when it is a literal VLT '
        'display', () {
      final src = _read('lib/main.dart');
      final unlockIdx = src.indexOf('class _UnlockPageState');
      final endIdx = src.indexOf('class PinGatePage', unlockIdx);
      final window = src.substring(unlockIdx, endIdx);
      // Positive: display name and private handle are selected from separate
      // state slots. A VLT value is never recovered from lastVaultName or a
      // visible controller.
      expect(
        window.contains('vh.userFacingVaultNameOrNull(app.lastVaultName)'),
        isTrue,
      );
      expect(
        window.contains(
          'vh.canonicalInternalVaultHandleOrNull(app.vaultHandle)',
        ),
        isTrue,
      );
      expect(
        window.contains('final entryIsVltHandle = displayVaultName == null;'),
        isTrue,
      );
      // Positive: the ZK call routes both cases correctly.
      expect(
        window.contains(
          'vaultName: entryIsVltHandle ? null : name,',
        ),
        isTrue,
        reason: 'user-typed lastVaultName must go through the ZK '
            'vault-name path; the legacy fallback would 401 for '
            'every ZK-adopted account (that is the bug we are '
            'fixing)',
      );
      expect(
        window.contains(
          'vaultHandle: entryIsVltHandle ? name : null,',
        ),
        isTrue,
      );
    });

    test(
        'UnlockPage does NOT unconditionally dispatch to legacy '
        '/auth/login for non-VLT names', () {
      final src = _read('lib/main.dart');
      final unlockIdx = src.indexOf('class _UnlockPageState');
      final endIdx = src.indexOf('class PinGatePage', unlockIdx);
      final window = src.substring(unlockIdx, endIdx);
      // The pre-fix pattern:
      //     if (vh.isValidVaultHandleDisplay(name)) { ... ZK ... }
      //     ...legacy path always runs below...
      // meant every user-typed name went straight to legacy and
      // ZK-adopted accounts 401'd with
      //     InvalidCredentialsException(message:
      //         "Vault name or PIN is incorrect")
      // The corrected pattern gates the legacy fallback on
      // ``zkLoginNotFound`` — set only when the ZK path returned
      // a 401 for a non-VLT entry.
      expect(
        window.contains('bool zkLoginNotFound = false;'),
        isTrue,
        reason: 'legacy fallback must be gated behind a ZK failure '
            'classifier, mirroring LoginPage',
      );
      expect(
        window.contains(
          'if (looksLikeAuth401 && !entryIsVltHandle)',
        ),
        isTrue,
        reason: 'only a 401 from the ZK path AND a non-VLT entry '
            'may fall through to legacy /auth/login',
      );
    });

    test(
        'the legacy /auth/login fallback still exists for pre-ZK '
        'unadopted accounts', () {
      final src = _read('lib/main.dart');
      final unlockIdx = src.indexOf('class _UnlockPageState');
      final endIdx = src.indexOf('class PinGatePage', unlockIdx);
      final window = src.substring(unlockIdx, endIdx);
      // The legacy fallback must still be present — pre-ZK accounts
      // that never went through the ZK adoption flow can only be
      // unlocked via /auth/login.
      expect(
        window.contains('client.authLogin(vaultName: name, pin: pin)'),
        isTrue,
      );
    });
  });
}
