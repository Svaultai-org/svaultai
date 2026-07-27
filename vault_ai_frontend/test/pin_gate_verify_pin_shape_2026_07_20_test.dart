// Frontend-side contract locks that go with the 2026-07-20 backend
// legacy-login case-insensitive fix.
//
// Neither of these tests requires the backend fix to pass — they lock
// down the client-side invariants the fix RELIES on. If a future
// change silently lowercases vault_name client-side, or removes the
// return-false path in PinGatePage._submit, the PIN-loop failure
// mode returns without the backend seeing anything different.
//
// Backend counterpart:
//   vault_ai_backend/test_auth_login_case_insensitive_2026_07_20.py

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _lib(String path) => File('lib/$path').readAsStringSync();

void main() {
  group('api_client.authLogin sends vault_name verbatim (no client lowercase)', () {
    // The backend fix uses LOWER(vault_name) = LOWER($1) with an
    // exact-case precedence branch. That precedence branch can only
    // fire if the client sends the vault_name the user actually
    // typed. A well-meaning `.toLowerCase()` on the client would
    // silently break case-collision selection and re-introduce the
    // production bug for any case-preserved row.
    test('authLogin request body uses vaultName as-provided', () {
      final src = _lib('api_client.dart');
      final idx = src.indexOf('Future<Map<String, dynamic>> authLogin(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 800).clamp(0, src.length));
      // The jsonEncode body must reference vaultName directly (not
      // vaultName.toLowerCase() / .trim().toLowerCase() / any
      // .toLowerCase() variant on the vault_name value).
      expect(
        window.contains("'vault_name': vaultName"),
        isTrue,
        reason: 'authLogin body must contain `vault_name: vaultName` — '
                'client-side lowercasing would break the case-insensitive '
                'lookup\'s exact-match precedence branch',
      );
      // Explicit belt: no toLowerCase call between the function
      // signature and the http.post call.
      final postIdx = window.indexOf('http.post(uri');
      expect(postIdx, greaterThan(-1));
      final preBody = window.substring(0, postIdx);
      expect(
        preBody.contains('.toLowerCase()'),
        isFalse,
        reason: 'authLogin must NOT normalize vaultName to lowercase '
                'before sending — collision-safe case selection lives '
                'entirely on the backend',
      );
    });
  });

  group('PinGatePage handles verifyPin false without crash or loop', () {
    // If the backend rejects the PIN (wrong PIN case, or the pre-fix
    // case-mismatch case), verifyPin returns false and PinGatePage
    // must stay on /pin with a "try again" message. It must NOT
    // navigate anywhere. The production PIN loop symptom was exactly
    // this branch firing (verifyPin returning false for a CORRECT
    // PIN because of the backend lookup bug) — the backend fix
    // resolves the false-return-for-correct-PIN case; this test
    // makes sure the false-return path itself stays quietly on /pin
    // and doesn't accidentally start doing something more disruptive.
    test('PinGatePage._submit shows error and stays on /pin on false', () {
      final src = _lib('main.dart');
      final classIdx = src.indexOf('class _PinGatePageState');
      expect(classIdx, greaterThan(-1));
      final classBlock =
          src.substring(classIdx, (classIdx + 20000).clamp(0, src.length));

      // The submit method calls verifyPin and inspects the boolean.
      final verifyPinIdx = classBlock.indexOf('await app.verifyPin(');
      expect(verifyPinIdx, greaterThan(-1),
          reason: 'PinGate._submit must call app.verifyPin');

      // The immediately-following block must handle !ok by setting
      // an error message and returning — NOT by navigating to a
      // different route.
      final tail = classBlock.substring(verifyPinIdx);
      final ifNotOkIdx = tail.indexOf('if (!ok)');
      expect(ifNotOkIdx, greaterThan(-1),
          reason: 'PinGate._submit must guard on !ok from verifyPin');

      // Extract the `if (!ok) { ... }` body.
      final ifBodyStart = tail.indexOf('{', ifNotOkIdx);
      final ifBodyEnd = tail.indexOf('}', ifBodyStart);
      expect(ifBodyStart, greaterThan(-1));
      expect(ifBodyEnd, greaterThan(-1));
      final ifBody = tail.substring(ifBodyStart, ifBodyEnd + 1);
      expect(
        ifBody.contains('err = '),
        isTrue,
        reason: '!ok branch must set the error message so the user '
                'can see the failure and retry',
      );
      // The !ok branch must NOT call Navigator to push away from
      // /pin. If it did, a wrong PIN would boot the user somewhere,
      // and the PIN-loop symptom would surface as a nav-loop.
      expect(
        ifBody.contains('Navigator.'),
        isFalse,
        reason: '!ok branch must NOT push a route — stay on /pin and '
                'let the user retry. Navigation belongs to the ok=true '
                'branch only',
      );
      expect(
        ifBody.contains('clearSession'),
        isFalse,
        reason: '!ok branch must NOT clear the session — a wrong PIN '
                'attempt is not grounds for dumping the session',
      );
    });

    test('PinGatePage._submit routes exceptions through handleApiException', () {
      // Any thrown exception (device_not_trusted / device_revoked /
      // AuthExpired / SessionTerminated / ...) is a distinct path
      // from verifyPin returning false. It must go through the
      // AppState error router so route + session state stay
      // consistent across the app.
      final src = _lib('main.dart');
      final classIdx = src.indexOf('class _PinGatePageState');
      final classBlock =
          src.substring(classIdx, (classIdx + 20000).clamp(0, src.length));
      final catchIdx = classBlock.indexOf('} catch (e) {');
      expect(catchIdx, greaterThan(-1),
          reason: 'PinGate._submit must catch exceptions from verifyPin');
      final catchTail = classBlock.substring(catchIdx);
      final endOfCatch = catchTail.indexOf('} finally {');
      expect(endOfCatch, greaterThan(-1));
      final catchBody = catchTail.substring(0, endOfCatch);
      expect(
        catchBody.contains('app.handleApiException(e)'),
        isTrue,
        reason: 'PinGate._submit exception handler must delegate to '
                'AppState.handleApiException so DeviceNotTrusted / '
                'SessionTerminated / AuthExpired etc. route through '
                'the app-wide error path (not a per-page duplicate)',
      );
    });
  });

  group('verifyPin still uses the legacy /auth/login endpoint', () {
    // The fix is on the /auth/login backend endpoint. If a future
    // refactor moves verifyPin to a different endpoint (e.g. the ZK
    // path) without also matching the case-preservation contract,
    // this test flags it so the fix boundary stays visible.
    test('AppState.verifyPin calls client.authLogin', () {
      final src = _lib('main.dart');
      final verifyIdx = src.indexOf('Future<bool> verifyPin');
      expect(verifyIdx, greaterThan(-1),
          reason: 'AppState.verifyPin must exist');
      final window =
          src.substring(verifyIdx, (verifyIdx + 4000).clamp(0, src.length));
      expect(
        window.contains('client.authLogin('),
        isTrue,
        reason: 'verifyPin must call client.authLogin — the fix in '
                'auth_routes.py landed on that endpoint\'s DB lookup. '
                'If verifyPin is retargeted to a different endpoint, '
                'validate the new endpoint also preserves vault_name '
                'case-precedence semantics.',
      );
    });
  });
}
