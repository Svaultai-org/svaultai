// Corrective-release regression tests (2026-07-19).
//
// After the 828ad4d deploy, production surfaced two issues:
//
//   1. A newly registered beneficiary hitting /beneficiary/link was
//      rejected with HTTP 400 "PIN not initialized". Root cause:
//      /auth/zk-register-finalize wrote empty strings into
//      vaults.pin_salt / pin_verifier; the legacy verify_vault_pin
//      helper used by /beneficiary/link treats those as unset.
//
//   2. The "Save your Vault ID" onboarding screen was still shown
//      after ZK registration and legacy → ZK adoption. Product
//      direction (2026-07-19): username + PIN only; the internal
//      vault handle stays internal.
//
// This file locks in both fixes with source-scan invariants that a
// future refactor cannot silently regress.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readLib(String path) => File('lib/$path').readAsStringSync();

void main() {
  group('the Save-your-Vault-ID screen no longer exists anywhere', () {
    test('the widget file has been deleted', () {
      expect(
        File('lib/vault_handle_saved_page.dart').existsSync(),
        isFalse,
        reason: 'lib/vault_handle_saved_page.dart must be removed — '
                'the onboarding no longer surfaces the vault handle',
      );
    });

    test('main.dart does not import the removed widget', () {
      final src = _readLib('main.dart');
      expect(src.contains("import 'vault_handle_saved_page.dart'"), isFalse);
      expect(src.contains('VaultHandleSavedPage'), isFalse,
          reason: 'no reference to the deleted widget');
    });

    test('no user-facing copy references the vault handle', () {
      // The user-visible copy for the removed screen was "Save your
      // Vault ID" / "Copy Vault ID". Guard against it creeping back
      // into ANY dart source under lib/.
      final banned = ['Save your Vault ID', 'Copy Vault ID'];
      for (final entry in Directory('lib').listSync(recursive: true)) {
        if (entry is! File || !entry.path.endsWith('.dart')) continue;
        final src = entry.readAsStringSync();
        for (final needle in banned) {
          expect(src.contains(needle), isFalse,
              reason: '${entry.path} still contains "$needle"');
        }
      }
    });
  });

  group('signup routes directly to /chat after ZK registration', () {
    test('the ZK signup handler calls pushReplacementNamed("/chat")', () {
      final src = _readLib('main.dart');
      // The ZK signup submit handler awaits zk.registerVault(...) then
      // markUnlocked, then navigates. The navigation MUST be a
      // pushReplacementNamed("/chat") — never a push to a save-vault-id
      // page.
      final idx = src.indexOf('zk.registerVault(');
      expect(idx, greaterThan(-1),
          reason: 'signup handler must call zk.registerVault');
      // Look at the window after registerVault for the navigation call.
      final window = src.substring(idx, (idx + 3000).clamp(0, src.length));
      expect(window.contains("pushReplacementNamed('/chat')"), isTrue,
          reason: 'signup must navigate to /chat via '
                  'pushReplacementNamed after successful registration');
      // Make sure the removed page isn't referenced in that window.
      expect(window.contains('VaultHandleSavedPage'), isFalse);
    });

    test('legacy → ZK adoption also routes to /chat', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('_tryLegacyAdoptionBestEffort');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2500).clamp(0, src.length));
      expect(window.contains("pushReplacementNamed('/chat')"), isTrue,
          reason: 'adoption path must navigate to /chat after success');
      expect(window.contains('VaultHandleSavedPage'), isFalse);
    });
  });

  group('ZK registration derives + sends the legacy PIN verifier', () {
    File _svc() => File('lib/services/zk_auth_service.dart');

    test('the client derives pin_salt + pin_verifier locally', () {
      final src = _svc().readAsStringSync();
      // The derivation helper must exist and use PBKDF2-HMAC-SHA256
      // with the same 32-byte output the server expects
      // (vault_core.derive_key).
      expect(src.contains('_deriveLegacyPinVerifier'), isTrue,
          reason: 'ZkAuthService must derive the legacy PIN verifier '
                  'client-side so the server never sees the plaintext '
                  'PIN yet the vaults row has non-empty pin_salt / '
                  'pin_verifier for the /beneficiary/link check');
      expect(src.contains('Pbkdf2('), isTrue);
      expect(src.contains('Hmac.sha256()'), isTrue);
      // The plaintext the server expects to decrypt out of pin_verifier
      // is a fixed literal (see vault_core.PIN_VERIFIER_PLAINTEXT).
      expect(src.contains("'vaultai_pin_ok'"), isTrue,
          reason: 'PIN verifier plaintext must match the server-side '
                  'constant vault_core.PIN_VERIFIER_PLAINTEXT');
    });

    test('registerVault sends pin_salt + pin_verifier + kdf_iterations',
        () {
      final src = _svc().readAsStringSync();
      final idx = src.indexOf('/auth/zk-register-finalize');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 1200).clamp(0, src.length));
      expect(window.contains("'pin_salt'"), isTrue,
          reason: 'finalize body must carry pin_salt');
      expect(window.contains("'pin_verifier'"), isTrue,
          reason: 'finalize body must carry pin_verifier');
      expect(window.contains("'kdf_iterations'"), isTrue,
          reason: 'finalize body must carry kdf_iterations');
    });

    test('the plaintext PIN is NEVER placed in the finalize JSON body',
        () {
      // The whole point of ZK: the /auth/zk-register-finalize request
      // must not contain the plaintext PIN as a JSON field. If a
      // future refactor accidentally does { 'pin': pin } we want a
      // loud test failure.
      final src = _svc().readAsStringSync();
      final idx = src.indexOf('/auth/zk-register-finalize');
      final window = src.substring(idx, (idx + 1200).clamp(0, src.length));
      // Look for the specific footgun pattern: a literal 'pin' key in
      // the body map.
      expect(window.contains("'pin':"), isFalse,
          reason: 'plaintext PIN must never appear as a JSON key on '
                  'the finalize request — OPAQUE hides it end-to-end');
    });
  });

  group('legacy adopt path also preserves ZK properties', () {
    test('adoption does NOT send a new pin_salt to the server', () {
      // On adoption, the legacy row already has pin_salt / pin_verifier
      // populated (from the legacy signup). The client must not
      // overwrite them — the server no longer wipes them either
      // (see auth_zk_routes.zk_adopt). This makes adopted accounts
      // able to link as beneficiaries just like fresh ZK signups.
      final src = File('lib/services/zk_auth_service.dart').readAsStringSync();
      final idx = src.indexOf('/auth/zk-adopt');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 1000).clamp(0, src.length));
      expect(window.contains("'pin_salt'"), isFalse,
          reason: 'adopt must preserve the legacy pin_salt row; '
                  'sending a new one would rewrite the existing '
                  'PBKDF2 verifier and invalidate the legacy PIN');
      expect(window.contains("'pin_verifier'"), isFalse);
    });
  });
}
