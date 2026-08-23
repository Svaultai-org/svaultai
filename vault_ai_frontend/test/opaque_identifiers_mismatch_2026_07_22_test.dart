// Regression tests for the OPAQUE identifier-mismatch root cause
// pinned in the 2026-07-22 investigation.
//
// The frontend was passing ``identifiers.client = credentialId`` to
// @serenity-kit/opaque's finishRegistration + finishLogin. The Rust
// backend called ``ServerLoginParameters::default()`` (identifiers =
// None). Per RFC 9807 the two must agree; the mismatch made
// ``client.finishLogin`` silently return undefined for every login
// attempt, which surfaced as ``OpaqueAuthenticationFailed`` =>
// "Wrong username or PIN." regardless of PIN correctness.
//
// The fix: strip ``clientIdentifier`` from frontend OPAQUE
// registration finish calls and from the primary login finish call
// to match the interop test that provably works. A later production
// compatibility patch permits loginVault to retry finishLogin with
// the historical identifier only after the default finish rejects,
// so records created by the short-lived bad build can still unlock.
// This suite locks both invariants.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readSvc(String path) => File('lib/services/$path').readAsStringSync();

String _readLib(String path) => File('lib/$path').readAsStringSync();

void main() {
  group('OPAQUE finish calls must NOT set identifiers.client', () {
    test(
        'zk_auth_service.registerVault.finishRegistration does not pass '
        'clientIdentifier', () {
      final src = _readSvc('zk_auth_service.dart');
      final idx = src.indexOf('Future<RegisterResult> registerVault(');
      expect(idx, greaterThan(-1));
      // Everything up to the next public method (loginVault).
      final endIdx = src.indexOf('Future<LoginResult> loginVault(', idx);
      final window = src.substring(idx, endIdx);
      expect(
        window.contains('finishRegistration('),
        isTrue,
      );
      // The exact argument that broke production:
      //   clientIdentifier: credentialId
      // — must be absent from the registerVault body.
      expect(
        window.contains('clientIdentifier:'),
        isFalse,
        reason: 'registerVault must not pass clientIdentifier — RFC '
            '9807 requires the server to use the matching '
            'ServerLoginParameters, and our Rust backend calls '
            '::default(). Passing an identifier here baked a '
            'mismatch into the OPAQUE envelope and made every '
            'subsequent login return undefined.',
      );
    });

    test(
        'zk_auth_service.loginVault tries default finish first, then '
        'legacy clientIdentifier compatibility only after rejection', () {
      final src = _readSvc('zk_auth_service.dart');
      final idx = src.indexOf('Future<LoginResult> loginVault(');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('/// Transparent legacy adoption', idx);
      final window = src.substring(idx, endIdx);
      expect(
        window.contains('finishLogin('),
        isTrue,
      );
      final modernAttemptIdx =
          window.indexOf('final modern = await finishLoginAttempt(');
      final rejectedStepIdx =
          window.indexOf("step('opaque_finish_login_default_rejected')");
      final retryBeginIdx = window.indexOf("step('opaque_legacy_retry_begin')");
      final legacyAttemptIdx =
          window.indexOf('final legacy = await finishLoginAttempt(');
      final legacyIdentifierIdx = window
          .indexOf('clientIdentifier: vaultHandleCredentialId(handleBytes)');
      final finalizeIdx = window.indexOf("'/auth/zk-login-finalize'");
      expect(
        modernAttemptIdx,
        greaterThan(-1),
        reason: 'loginVault must attempt the corrected no-identifier '
            'finish first',
      );
      expect(
        window.substring(modernAttemptIdx, rejectedStepIdx).contains(
              'clientIdentifier: null',
            ),
        isTrue,
      );
      expect(rejectedStepIdx, greaterThan(modernAttemptIdx));
      expect(retryBeginIdx, greaterThan(rejectedStepIdx));
      expect(legacyAttemptIdx, greaterThan(retryBeginIdx));
      expect(legacyIdentifierIdx, greaterThan(legacyAttemptIdx));
      expect(finalizeIdx, greaterThan(legacyIdentifierIdx));
      expect(
        window.substring(rejectedStepIdx, finalizeIdx).contains(
              'clientIdentifier: vaultHandleCredentialId(handleBytes)',
            ),
        isTrue,
        reason: 'only the post-rejection compatibility retry may use '
            'the historical client identifier',
      );
    });

    test(
        'adoptLegacyVault.finishRegistration also omits '
        'clientIdentifier', () {
      final src = _readSvc('zk_auth_service.dart');
      final idx = src.indexOf('Future<AdoptResult> adoptLegacyVault(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 4000).clamp(0, src.length));
      expect(
        window.contains('finishRegistration('),
        isTrue,
      );
      expect(
        window.contains('clientIdentifier:'),
        isFalse,
        reason: 'the legacy-adopt registration flow must also match '
            'the server-side ServerLoginParameters::default() — '
            'otherwise adopted accounts would be stranded the '
            'same way fresh ZK ones were before the fix',
      );
    });
  });

  group('the SERVER-side credential_id is still the deterministic handle', () {
    // Removing identifiers.client MUST NOT be conflated with
    // dropping the OPAQUE OPRF credential_identifier. The latter
    // is what binds the account to the vault_handle bytes on the
    // server side; if we lost that, every account would share the
    // same OPRF secret.
    //
    // The credential_identifier still flows via ``vault_handle`` in
    // the request bodies; the backend derives it via
    // ``_opaque_credential_id(handle_bytes)``. The frontend does
    // NOT pass it on the client side because @serenity-kit/opaque's
    // API does not take a client-side credential_identifier.
    test('registerVault still sends vault_handle in both init and finalize',
        () {
      final src = _readSvc('zk_auth_service.dart');
      final idx = src.indexOf('Future<RegisterResult> registerVault(');
      final endIdx = src.indexOf('Future<LoginResult> loginVault(', idx);
      final window = src.substring(idx, endIdx);
      final initIdx = window.indexOf("'/auth/zk-register-init'");
      final finalizeIdx = window.indexOf("'/auth/zk-register-finalize'");
      expect(initIdx, greaterThan(-1));
      expect(finalizeIdx, greaterThan(-1));
      // Both bodies must contain the vault_handle field.
      expect(
        window.substring(initIdx, finalizeIdx).contains("'vault_handle'"),
        isTrue,
      );
      expect(
        window.substring(finalizeIdx).contains("'vault_handle'"),
        isTrue,
      );
    });

    test('loginVault still sends vault_handle in login-init', () {
      final src = _readSvc('zk_auth_service.dart');
      final idx = src.indexOf('Future<LoginResult> loginVault(');
      final endIdx = src.indexOf('/// Transparent legacy adoption', idx);
      final window = src.substring(idx, endIdx);
      final loginInitIdx = window.indexOf("'/auth/zk-login-init'");
      expect(loginInitIdx, greaterThan(-1));
      expect(
        window.substring(loginInitIdx).contains("'vault_handle'"),
        isTrue,
      );
    });
  });

  group('SignupPage duplicate-username 409 shows a clean copy', () {
    test(
        'the SignupPage catch converts a 409 error string to the '
        'friendly copy', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _SignupPageState');
      final endIdx = src.indexOf('Widget build(BuildContext context)', idx);
      final window = src.substring(idx, endIdx);
      // Guard against regression of the raw stringification.
      expect(
        window.contains(r"err = e.toString().replaceFirst('Exception: ', '')"),
        isFalse,
        reason: 'SignupPage must not surface the raw '
            '_zkHttpPost exception message — that leaks the '
            'endpoint URL and response body',
      );
      // Positive check: the friendly duplicate-username copy is
      // present and matches the spec verbatim.
      expect(
        window.contains(
          "'That username is already taken. Please choose another.'",
        ),
        isTrue,
        reason: 'SignupPage must classify 409 responses and show '
            'the friendly "already taken" message',
      );
      // The classification must match on both the ``failed 409``
      // shape (from _zkHttpPost) AND the generic ``HTTP 409`` shape
      // (from api_client style errors).
      expect(window.contains("'failed 409'"), isTrue);
      expect(window.contains("'HTTP 409'"), isTrue);
    });
  });

  group('UnlockPage cache invariants', () {
    test(
        'UnlockPage._submit routes to /login when both cached identifiers '
        'are unavailable', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _UnlockPageState');
      final endIdx = src.indexOf('Future<void> _useAnotherVault()', idx);
      final window = src.substring(idx, endIdx);
      // A friendly vault name is optional when a private vault handle is
      // available for rehydration. Only the absence of both identifiers must
      // route to full login; the handle must never become display state.
      expect(
        window.contains(
          'displayVaultName == null && privateVaultHandle == null',
        ),
        isTrue,
        reason: 'UnlockPage must route to /login when the cached '
            'identity has neither a display-safe name nor a private handle',
      );
      expect(
        window.contains('final name = displayVaultName ?? privateVaultHandle!'),
        isTrue,
        reason: 'private handle rehydration must remain available when the '
            'display name is unavailable',
      );
    });
  });
}
