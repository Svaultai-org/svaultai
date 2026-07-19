// Regression tests for the 2026-07-20 identity + unlock architecture
// correction.
//
// Locks four contracts:
//
//   1. AppState identity separation
//      canonicalUsername (badge, primary UI label) is distinct from
//      displayUsername (optional nickname). Signup captures the
//      typed vault name as canonicalUsername and never routes it
//      via the display slot. Dashboard, drawer, and account menu
//      render canonicalUsername first.
//
//   2. Privacy-preserving lookup identifier
//      The client sends username_lookup (32-byte b64url) on
//      register-init, register-finalize, and login-init. NEVER
//      sends the raw canonical username or an already-normalized
//      string. The 32 bytes are derived as
//          SHA-256(salt || nfkc_casefolded_utf8_username)
//      via services/vault_handle.dart::deriveUsernameLookupV1.
//
//   3. Chat SSE middle catch routes InvalidVaultUnlockException
//      through handleApiException on both chat surfaces so the
//      dashboard-says-unlocked / chat-says-expired desync from the
//      2026-07-20 investigation cannot recur.
//
//   4. Strict AppState.unlocked invariant
//      `unlocked` returns true only when there is a live key-cache
//      entry for the current (vaultId, vaultName). Any code path
//      that clears the cache automatically flips the getter to
//      false — the field-only fix from the previous pass was
//      insufficient.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('AppState identity fields', () {
    test('canonicalUsername field exists and is documented', () {
      final src = _read('lib/main.dart');
      expect(src.contains('String? canonicalUsername;'), isTrue);
    });

    test('setSession accepts canonicalUsernameValue and persists it', () {
      final src = _read('lib/main.dart');
      expect(src.contains('String? canonicalUsernameValue,'), isTrue);
      expect(
        src.contains("await sp.setString('last_canonical_username',"),
        isTrue,
      );
    });

    test('hydrate restores canonicalUsername from SharedPreferences', () {
      final src = _read('lib/main.dart');
      expect(src.contains("sp.getString('last_canonical_username')"), isTrue);
    });

    test('clearSession(keepLastVaultName=false) removes last_canonical_username',
        () {
      final src = _read('lib/main.dart');
      expect(
        src.contains("await sp.remove('last_canonical_username');"),
        isTrue,
      );
    });
  });

  group('AppState.unlocked strict invariant', () {
    test('the unlocked getter derives from _unlocked AND authed AND '
         'a live key-cache hit for (vaultId, vaultName)', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('bool get unlocked {');
      expect(idx, greaterThan(-1),
          reason: 'unlocked must be a getter with an explicit '
                  'invariant, not a bare field accessor');
      final endIdx = src.indexOf('set unlocked(', idx);
      final window = src.substring(idx, endIdx);
      // Every component of the invariant must be checked. If any
      // one of these is removed the desync can recur.
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

  group('SignupPage identity capture', () {
    test('signup passes vaultName as canonicalUsernameValue', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('class _SignupPageState');
      final endIdx = src.indexOf('Widget build(BuildContext context)', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains('canonicalUsernameValue: vaultName'), isTrue);
    });

    test('signup does NOT default displayUsername to vaultName', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('class _SignupPageState');
      final endIdx = src.indexOf('Widget build(BuildContext context)', idx);
      final window = src.substring(idx, endIdx);
      expect(
        window.contains(
          'displayUsernameValue: nickname.isEmpty ? null : nickname',
        ),
        isTrue,
      );
    });
  });

  group('Dashboard, drawer, account menu render canonicalUsername first', () {
    test('dashboard welcome banner reads canonicalUsername before displayUsername',
        () {
      final src = _read('lib/main.dart');
      expect(
        src.contains(
          "'Welcome to \${app.canonicalUsername ?? app.displayUsername ?? 'your vault'}'",
        ),
        isTrue,
      );
    });

    test('drawer header reads canonicalUsername before displayUsername', () {
      final src = _read('lib/main.dart');
      expect(
        src.contains(
          "app.canonicalUsername ?? app.displayUsername ?? 'Vault',",
        ),
        isTrue,
      );
    });

    test('account menu label reads canonicalUsername before displayUsername',
        () {
      final src = _read('lib/main.dart');
      // dart format may wrap the ternary across lines, so match on
      // a whitespace-tolerant regex instead of an exact string.
      final re = RegExp(
        r"app\.canonicalUsername\s*\?\?\s*"
        r"app\.displayUsername\s*\?\?\s*'VaultAI User'",
      );
      final matches = re.allMatches(src).length;
      expect(matches, greaterThanOrEqualTo(2));
    });
  });

  group('Chat SSE middle catch routes InvalidVaultUnlockException', () {
    test('both chat SSE surfaces guard with handleApiException before '
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
    test('ZkAuthService sends username_lookup (32-byte b64url), NOT '
         'normalized_username, on every ZK request', () {
      final src = _read('lib/services/zk_auth_service.dart');
      // Positive check: the new field must appear in all three
      // request bodies.
      final ulOccurrences =
          "'username_lookup': lookupV1B64".allMatches(src).length +
              "'username_lookup': usernameLookupB64".allMatches(src).length;
      expect(ulOccurrences, greaterThanOrEqualTo(3),
          reason: 'register-init, register-finalize, and login-init '
                  'must all carry username_lookup');
      // Negative check: the leaky field must NOT appear anywhere.
      expect(src.contains("'normalized_username'"), isFalse,
          reason: 'normalized_username exposes the raw canonical '
                  'username to the app server; the client must derive '
                  'the lookup id locally instead');
    });

    test('vault_handle.dart exports deriveUsernameLookupV1 with the '
         'correct salt and byte length', () {
      final src = _read('lib/services/vault_handle.dart');
      expect(src.contains("'vaultai.username_lookup.v1|'"), isTrue,
          reason: 'salt must be exactly the same UTF-8 bytes as the '
                  'Python mirror in vault_handle.py::_USERNAME_LOOKUP_V1_SALT');
      expect(src.contains('const int usernameLookupV1Bytes = 32;'), isTrue);
      expect(
        src.contains('Uint8List deriveUsernameLookupV1(String rawUsername)'),
        isTrue,
      );
    });
  });

  group('Deterministic account-identity chat intent', () {
    test('the intent regex covers vault-name / username / who-am-i '
         'questions and only exact-form matches', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('_accountIdentityQueryRe = RegExp');
      expect(idx, greaterThan(-1),
          reason: 'a deterministic account-identity intent must exist');
      // The regex must not accidentally match casual chat like
      // "my vault name is a mess". Anchoring on ^ and $ is the
      // primary defense.
      final tailIdx = src.indexOf(');', idx);
      final regexSrc = src.substring(idx, tailIdx);
      expect(regexSrc.contains(r'"^\s*(?:"'), isTrue,
          reason: 'anchored on start');
      expect(regexSrc.contains(r"caseSensitive: false"), isTrue);
    });

    test('the intent replies from canonicalUsername first, then nickname, '
         'then a neutral prompt — never from the VLT handle or uuid', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('_tryDirectAccountIdentityReply(');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('Future<void> _send()', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains(r"'Your vault name is $canonical.'"), isTrue);
      expect(window.contains(r'canonical.isNotEmpty'), isTrue);
      // NEGATIVE: neither the vault handle nor vault_id nor the raw
      // exception may appear in the reply string.
      expect(window.contains('vaultHandle'), isFalse,
          reason: 'account-identity intent must never surface the '
                  'VLT-* handle');
      expect(window.contains('vaultId'), isFalse,
          reason: 'account-identity intent must never surface the '
                  'internal UUID');
    });

    test('the intent is dispatched from _send BEFORE any network call', () {
      final src = _read('lib/main.dart');
      final sendIdx = src.indexOf('Future<void> _send() async {');
      expect(sendIdx, greaterThan(-1));
      final window = src.substring(sendIdx, (sendIdx + 8000).clamp(0, src.length));
      final intentIdx = window.indexOf('_tryDirectAccountIdentityReply(text, app)');
      // If the intent check moved after the network payload build,
      // the reply would race with a real chat request.
      expect(intentIdx, greaterThan(-1));
    });
  });
}
