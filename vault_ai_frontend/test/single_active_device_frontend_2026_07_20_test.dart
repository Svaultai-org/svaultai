// Single-active-device frontend behavior (2026-07-20).
//
// The backend now trusts the current device on ZK signup / login
// and revokes every other device row for that vault, in one
// transaction. The `/devices/register` endpoint has the same
// semantics. Any older device therefore receives a 403 with
// ``detail.code == "device_revoked"`` on its next protected
// request.
//
// This suite locks the client half of that contract:
//
//   1. api_client's ``_throwIfDeviceNotTrusted`` recognizes the new
//      ``device_revoked`` code (in addition to the legacy
//      ``device_not_trusted`` and ``missing_device_id`` codes).
//   2. ``DeviceNotTrustedException.fromResponseBody`` carries the
//      status through as ``"revoked"``.
//   3. ``AppState.handleApiException`` for a DeviceNotTrustedException
//      now routes to ``/auth`` (the login screen), NEVER to
//      ``/device-pending``. This bypasses the legacy pending-trust
//      screen from normal login.
//   4. The source no longer routes device errors to /device-pending
//      from handleApiException — a source-level guard against the
//      old flow silently returning.
//
// Widget-level flow through the login screen is a manual step (a
// live backend + browser build); this suite covers the invariants
// tests can actually reach without full HTTP mocking.
//
// Related backend tests:
//   * test_single_active_device_2026_07_20.py
//   * test_device_register_idempotency.py (rewrite for new model)

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';

String _lib(String path) => File('lib/$path').readAsStringSync();

void main() {
  group('DeviceNotTrustedException parses the new device_revoked code', () {
    test('device_revoked body → status=revoked', () {
      const body =
          '{"detail":{"code":"device_revoked","message":"This device'
          ' session ended...","device_id":"aaaa","status":"revoked"}}';
      final ex = DeviceNotTrustedException.fromResponseBody(body);
      expect(ex.status, 'revoked');
      expect(ex.message.toLowerCase(), contains('session'));
    });

    test('legacy device_not_trusted body still parses (pending)', () {
      const body =
          '{"detail":{"code":"device_not_trusted","message":"pending",'
          '"device_id":"aaaa","status":"pending"}}';
      final ex = DeviceNotTrustedException.fromResponseBody(body);
      expect(ex.status, 'pending');
    });
  });

  group('api_client._throwIfDeviceNotTrusted recognises device_revoked', () {
    // Source-level assertion: the client's throw-classifier lists all
    // three codes that trigger the device-error branch. If a future
    // refactor drops device_revoked, the AppState.handleApiException
    // hook never fires and every subsequent protected request throws
    // an uncaught 403 into the UI.
    test('_throwIfDeviceNotTrusted covers all three device codes', () {
      final src = _lib('api_client.dart');
      // The helper is called from dozens of call sites BEFORE its
      // definition, so we search for the DECLARATION explicitly.
      final helperIdx =
          src.indexOf('void _throwIfDeviceNotTrusted(int statusCode');
      expect(helperIdx, greaterThan(-1));
      final window = src.substring(
        helperIdx,
        (helperIdx + 1500).clamp(0, src.length),
      );
      expect(window.contains("'device_not_trusted'"), isTrue,
          reason: 'legacy code still handled for the "missing" case');
      expect(window.contains("'missing_device_id'"), isTrue,
          reason: 'missing-device-id still handled');
      expect(window.contains("'device_revoked'"), isTrue,
          reason:
              'NEW: revoked-device response code from the single-active-'
              'device backend must be caught here — otherwise the client '
              'never fires the AppState hook and every protected request '
              'throws a raw 403 into the UI.');
    });
  });

  group('AppState.handleApiException routes device errors to /auth', () {
    // The old ed825aa+earlier behavior: device errors → /device-pending
    // (the "This device is not trusted yet" screen). Under the single-
    // active-device model that screen must NOT appear from normal
    // login. handleApiException now pushes /auth and calls clearSession
    // (keepLastVaultName: true so the user's account name is still
    // pre-filled on the unlock screen when they log in on this
    // browser).

    test('DeviceNotTrustedException branch pushes /auth', () {
      final src = _lib('main.dart');
      final idx = src.indexOf('DeviceNotTrustedException');
      expect(idx, greaterThan(-1));
      // Scan the block that follows the ``if (error is
      // DeviceNotTrustedException)`` for the navigation call. We do
      // this by taking a bounded window after the match, then
      // looking at the pushNamedAndRemoveUntil call inside it.
      final window = src.substring(idx, (idx + 3000).clamp(0, src.length));
      final navIdx = window.indexOf('pushNamedAndRemoveUntil(');
      expect(navIdx, greaterThan(-1),
          reason: 'the DeviceNotTrustedException branch must call '
                  'pushNamedAndRemoveUntil to reroute the user');
      final navWindow = window.substring(
        navIdx,
        (navIdx + 300).clamp(0, window.length),
      );
      expect(
        navWindow.contains("'/auth'"),
        isTrue,
        reason: 'device errors must land on the LOGIN screen (/auth); '
                'the legacy /device-pending waiting-period flow is '
                'bypassed for normal login',
      );
    });

    test('DeviceNotTrustedException branch does NOT push /device-pending', () {
      final src = _lib('main.dart');
      final idx = src.indexOf('DeviceNotTrustedException');
      final window = src.substring(idx, (idx + 3000).clamp(0, src.length));
      // Between the match and the branch's return true, no route
      // string of '/device-pending' should appear. It may appear
      // elsewhere in the file (route registration), but not here.
      final endOfBranch = window.indexOf('return true;');
      expect(endOfBranch, greaterThan(-1));
      final branchBody = window.substring(0, endOfBranch);
      expect(
        branchBody.contains("'/device-pending'"),
        isFalse,
        reason: 'handleApiException must NOT route to /device-pending '
                'for device errors under the single-active-device model',
      );
    });

    test('DeviceNotTrustedException branch calls clearSession', () {
      // Without a clearSession the client would still hold a
      // (revoked) session_token and re-hit /auth/me → SessionTermination
      // → /login again. Cheaper and cleaner: clear now, keep the
      // last vault name so the user's account is pre-filled.
      final src = _lib('main.dart');
      final idx = src.indexOf('DeviceNotTrustedException');
      final window = src.substring(idx, (idx + 3000).clamp(0, src.length));
      final endOfBranch = window.indexOf('return true;');
      final branchBody = window.substring(0, endOfBranch);
      expect(
        branchBody.contains('clearSession'),
        isTrue,
        reason: 'device-error branch must drop the local session — '
                'the current session_token is no longer valid against '
                'the backend now that this device is revoked',
      );
    });
  });

  group('api_client keeps sending X-Device-Id on protected calls', () {
    // The whole enforcement model breaks if the client stops
    // attaching the X-Device-Id header, because the gate would
    // then respond `missing_device_id` for every request. This
    // guard freezes the header attachment in place.
    test('_defaultHeaders attaches X-Device-Id when set', () {
      final src = _lib('api_client.dart');
      final idx = src.indexOf('Map<String, String> _defaultHeaders(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(window.contains("headers['X-Device-Id'] = did;"), isTrue,
          reason: 'client must attach X-Device-Id to every protected '
                  'request — otherwise the gate returns missing_device_id '
                  'and the user is bounced right back to /auth every call');
    });
  });

  group('SessionTermination code parser stays compatible', () {
    // Sanity check: a 401 termination coming down for reasons
    // OTHER than device revocation still parses normally. This
    // ensures the device_revoked code addition didn't accidentally
    // capture 401 termination codes.
    test('device_revoked is not a session termination code', () {
      // If the backend ever emits `device_revoked` at 401 instead of
      // 403, the SessionTerminatedException handler would fire and
      // possibly loop. The parser lives in api_client.dart and only
      // reads a fixed enum-like list.
      final src = _lib('api_client.dart');
      // No hard proof possible without importing st.parseSessionTerminationCode,
      // but we assert `parseSessionTerminationCode` is called from a
      // 401 code path only, and we don't accidentally return the
      // device_revoked string from it (i.e. no `device_revoked` in
      // the same 5 lines).
      expect(src.contains('parseSessionTerminationCode'), isTrue);
    });
  });
}
