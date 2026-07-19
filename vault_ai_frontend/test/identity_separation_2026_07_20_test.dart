// Regression tests for the invariants introduced in 98c5afd that
// survive the 2026-07-20 identity-model correction:
//
//   1. Strict AppState.unlocked invariant — unlocked returns true
//      only when the key cache actually holds an entry for
//      (vaultId, vaultName). Any code path that clears the cache
//      automatically flips the getter to false.
//
//   2. Chat SSE middle catch routes InvalidVaultUnlockException
//      through handleApiException on both chat surfaces so the
//      dashboard-says-unlocked / chat-says-expired desync cannot
//      recur.
//
//   3. Wire protocol privacy: the client sends username_lookup
//      (32-byte b64url) — NOT the raw canonical username — on
//      every ZK request. The lookup is derived as
//          SHA-256(salt || nfkc_casefolded_utf8_vault_name)
//      via services/vault_handle.dart::deriveUsernameLookupV1.
//
// The vault_name product-model tests live in
// identity_vault_name_2026_07_20_test.dart. This suite deliberately
// scopes down to the invariants that are orthogonal to the
// vault_name / display_name naming.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('AppState.unlocked strict invariant', () {
    test(
        'the unlocked getter derives from _unlocked AND authed AND '
        'a live key-cache hit for (vaultId, vaultName)', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('bool get unlocked {');
      expect(idx, greaterThan(-1),
          reason: 'unlocked must be a getter with an explicit '
              'invariant, not a bare field accessor');
      final endIdx = src.indexOf('set unlocked(', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains('if (!_unlocked) return false;'), isTrue);
      expect(window.contains('if (!authed) return false;'), isTrue);
      expect(
        window.contains(
          '_VaultCrypto.hasKeyFor(vaultId: vId, vaultName: vName)',
        ),
        isTrue,
        reason: 'unlocked must consult the key cache — the field '
            'alone is not sufficient, that is exactly what '
            'produced the 2026-07-20 desync',
      );
    });
  });

  group('Chat SSE middle catch routes InvalidVaultUnlockException', () {
    test(
        'both chat SSE surfaces guard with handleApiException before '
        'interpolating the error', () {
      final src = _read('lib/main.dart');
      final rawInterpolations =
          "msgs.add(_Msg('assistant', 'Error: \$err'))".allMatches(src).length;
      final guards =
          'if (app.handleApiException(err)) return;'.allMatches(src).length;
      expect(guards, greaterThanOrEqualTo(rawInterpolations));
    });
  });

  group('Wire protocol does NOT carry the raw canonical username', () {
    test(
        'ZkAuthService sends username_lookup (32-byte b64url), NOT '
        'a "normalized_username" field, on every ZK request', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final ulOccurrences =
          "'username_lookup': lookupV1B64".allMatches(src).length +
              "'username_lookup': usernameLookupB64".allMatches(src).length;
      expect(ulOccurrences, greaterThanOrEqualTo(3),
          reason: 'register-init, register-finalize, and login-init '
              'must all carry username_lookup');
      expect(src.contains("'normalized_username'"), isFalse);
    });

    test(
        'vault_handle.dart exports deriveUsernameLookupV1 with the '
        'correct salt and byte length', () {
      final src = _read('lib/services/vault_handle.dart');
      expect(src.contains("'vaultai.username_lookup.v1|'"), isTrue);
      expect(src.contains('const int usernameLookupV1Bytes = 32;'), isTrue);
      expect(
        src.contains('Uint8List deriveUsernameLookupV1(String rawUsername)'),
        isTrue,
      );
    });
  });
}
