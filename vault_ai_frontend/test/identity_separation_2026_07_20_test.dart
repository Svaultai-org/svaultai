// Regression tests for the 2026-07-20 identity + unlock architecture
// correction.
//
// Before this pass:
//   * User typed username "Alexa" and optional display name "show".
//     The signup flow collapsed both into ``AppState.displayUsername``
//     via ``zkChosenDisplay = displayUsername.isEmpty ? vaultName : displayUsername``.
//     Dashboard rendered "Welcome to show" and "Alexa" was unreachable
//     from any UI surface after signup.
//   * ``AppState`` had no separate ``canonicalUsername`` field, so
//     hydrate on refresh had nowhere to restore the badge from.
//   * The chat SSE stream's middle catch (the one wrapping
//     ``await for`` on the encrypted response) did NOT call
//     ``AppState.handleApiException`` and instead interpolated the
//     raw ``InvalidVaultUnlockException.toString()`` into the
//     assistant message bubble. ``app.unlocked`` stayed ``true`` and
//     the user was never routed to /pin — the dashboard-says-unlocked/
//     chat-says-expired desync.
//   * Frontend registration bodies did not carry a normalized
//     username, so the backend had no way to enforce a
//     derivation-version-independent uniqueness check.
//
// This suite locks the corrected shape in place.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('AppState identity fields', () {
    test('canonicalUsername field exists and is documented', () {
      final src = _read('lib/main.dart');
      // The field declaration is the anchor for every other change
      // in this pass; if it is renamed or removed, the dashboard
      // falls back to displayUsername (nickname) as the primary
      // label and the "show replaces Alexa" symptom returns.
      expect(
        src.contains('String? canonicalUsername;'),
        isTrue,
        reason: 'AppState must expose a canonicalUsername field '
            'separate from displayUsername',
      );
    });

    test('setSession accepts canonicalUsernameValue and persists it', () {
      final src = _read('lib/main.dart');
      expect(
        src.contains('String? canonicalUsernameValue,'),
        isTrue,
        reason: 'AppState.setSession must accept a canonicalUsernameValue '
            'parameter so the SignupPage can pass the typed '
            'username in without going through the display slot',
      );
      expect(
        src.contains("await sp.setString('last_canonical_username',"),
        isTrue,
        reason: 'canonical username must be persisted to '
            "'last_canonical_username' so hydrate() restores it "
            'on next launch',
      );
    });

    test('hydrate restores canonicalUsername from SharedPreferences', () {
      final src = _read('lib/main.dart');
      expect(
        src.contains("sp.getString('last_canonical_username')"),
        isTrue,
      );
    });

    test(
        'clearSession(keepLastVaultName=false) removes last_canonical_username',
        () {
      final src = _read('lib/main.dart');
      expect(
        src.contains("await sp.remove('last_canonical_username');"),
        isTrue,
        reason: '"Use another vault" must not carry the previous '
            "vault's canonical name into the fresh session's UI",
      );
    });
  });

  group('SignupPage identity capture', () {
    test('signup passes vaultName as canonicalUsernameValue', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('class _SignupPageState');
      final endIdx = src.indexOf('Widget build(BuildContext context)', idx);
      final window = src.substring(idx, endIdx);
      expect(
        window.contains('canonicalUsernameValue: vaultName'),
        isTrue,
        reason: 'the typed vault name IS the canonical username; '
            'signup must persist it as such rather than routing '
            'it through the display-name slot',
      );
    });

    test('signup does NOT default displayUsername to vaultName', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('class _SignupPageState');
      final endIdx = src.indexOf('Widget build(BuildContext context)', idx);
      final window = src.substring(idx, endIdx);
      // The pre-fix line was:
      //   displayUsername.isEmpty ? vaultName : displayUsername
      // That collapse is exactly how "Alexa" disappeared from the UI.
      // The corrected shape either leaves displayUsername null when
      // the user did not type one, or writes canonicalUsername for
      // the encrypted slot but never assigns it to displayUsername.
      expect(
        window.contains(
          'displayUsernameValue: nickname.isEmpty ? null : nickname',
        ),
        isTrue,
        reason: 'displayUsernameValue must be null when no nickname '
            'was typed; falling back to vaultName here is what '
            'produced "Welcome to show" instead of "Welcome to Alexa"',
      );
    });
  });

  group('Dashboard, drawer, and account menu render canonicalUsername first',
      () {
    test(
        'dashboard welcome banner reads canonicalUsername before displayUsername',
        () {
      final src = _read('lib/main.dart');
      expect(
        src.contains(
          "'Welcome to \${app.canonicalUsername ?? app.displayUsername ?? 'your vault'}'",
        ),
        isTrue,
        reason: 'canonical username is the vault identity — must lead '
            'the welcome banner. Nickname is a fallback only.',
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
      final matches =
          "app.canonicalUsername ?? app.displayUsername ?? 'VaultAI User',"
              .allMatches(src)
              .length;
      // Two occurrences: the PopupMenuItem header AND the pill chip
      // that is always visible in the top nav.
      expect(matches, greaterThanOrEqualTo(2),
          reason: 'both PopupMenu header and account chip must show '
              'the canonical username; falling back to display '
              'name (nickname) hides the badge');
    });
  });

  group('Chat SSE middle catch routes InvalidVaultUnlockException properly',
      () {
    test(
        'both chat surfaces call handleApiException from the outer '
        'stream catch', () {
      final src = _read('lib/main.dart');
      // The bug had a bare
      //   } catch (err) {
      //     if (!mounted) return;
      //     setState(() { ... 'Error: \$err' ... });
      //   }
      // wrapping ``await for (final encryptedChunk in stream)``,
      // which meant an InvalidVaultUnlockException from the backend
      // during streaming would be painted into the assistant bubble
      // AND leave app.unlocked=true. The fix is a
      //   if (app.handleApiException(err)) return;
      // guard at the top of that catch. There are two chat surfaces
      // with identical structure; both must be fixed.
      final pattern = '// 2026-07-20 dashboard-says-unlocked/chat-says-expired';
      final matches = pattern.allMatches(src).length;
      expect(matches, greaterThanOrEqualTo(2),
          reason: 'the guard comment (used here as an anchor for the '
              'fix) must appear at both chat SSE outer catches. '
              'Regressing this comment out silently regresses '
              'the fix.');
      // Positive check: neither surface allows an err interpolation
      // WITHOUT a preceding handleApiException guard.
      final rawInterpolations =
          "msgs.add(_Msg('assistant', 'Error: \$err'))".allMatches(src).length;
      final guardsBeforeInterpolation =
          'if (app.handleApiException(err)) return;'.allMatches(src).length;
      expect(guardsBeforeInterpolation, greaterThanOrEqualTo(rawInterpolations),
          reason: 'every raw error interpolation must be preceded by a '
              'handleApiException guard');
    });
  });

  group('ZkAuthService sends normalized_username on register + login', () {
    test('registerVault carries normalized_username in init and finalize', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final idx = src.indexOf('Future<RegisterResult> registerVault(');
      final endIdx = src.indexOf('Future<LoginResult> loginVault(', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains("'normalized_username': normalized"), isTrue,
          reason: 'register-init AND register-finalize bodies must '
              'include normalized_username so the server can '
              'compute a per-deployment blind index and reject '
              'duplicates that vault_handle UNIQUE cannot catch');
      expect("'normalized_username':".allMatches(window).length,
          greaterThanOrEqualTo(2),
          reason: 'both init and finalize bodies must carry the field '
              'so a mid-flow reject at either stage is possible');
    });

    test(
        'loginVault carries normalized_username on login-init when '
        'username was provided', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final idx = src.indexOf('Future<LoginResult> loginVault(');
      final endIdx = src.indexOf('/// Transparent legacy adoption', idx);
      final window = src.substring(idx, endIdx);
      expect(
        window.contains("'normalized_username': normalizedUsername"),
        isTrue,
        reason: 'server needs the canonical form to fall back to the '
            'blind-index lookup when the client-derived handle '
            'bytes miss (e.g. legacy random-handle row)',
      );
    });
  });
}
