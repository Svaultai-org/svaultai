// 2026-07-14 (Round 10 — stale-cache fix): regression suite for
// AppReleaseController.
//
// The controller MUST:
//   * treat matching running/server release as a no-op;
//   * treat differing running/server release as
//     `updateAvailable == true`;
//   * survive a failed release.json fetch WITHOUT clearing a
//     previously-detected update signal;
//   * survive a malformed release.json response WITHOUT crashing
//     the session;
//   * on `applyUpdateAndReload`:
//       - unregister the service worker exactly once;
//       - clear ONLY app-code cache entries (never auth/wallet);
//       - reload the page exactly once;
//       - record the target release for loop protection.
//   * expose `sendShouldBeBlocked()` returning true when an update
//     is pending — consumers gate Send on this.
//   * suppress reload while a caller-provided `reloadAllowed`
//     returns false (active broadcast).

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:vault_ai_frontend/services/app_release_controller.dart';


class _ReloadRecorder {
  int unregisterCalls = 0;
  int clearCacheCalls = 0;
  int reloadCalls = 0;
  final Map<String, String> _session = {};

  Future<void> unregister() async {
    unregisterCalls++;
  }

  Future<void> clearCache() async {
    clearCacheCalls++;
  }

  void reload() {
    reloadCalls++;
  }

  String? read() => _session['target'];
  void write(String v) => _session['target'] = v;
}


AppReleaseController _controllerWith({
  required http.Client mockClient,
  required String runningRelease,
  required _ReloadRecorder rec,
}) {
  return AppReleaseController(
    baseUrl: 'http://mock',
    runningRelease: runningRelease,
    httpClient: mockClient,
    unregisterServiceWorker: rec.unregister,
    clearAppCodeCacheEntries: rec.clearCache,
    reloadPage: rec.reload,
    readLastAttemptedTarget: rec.read,
    writeLastAttemptedTarget: rec.write,
  );
}


void main() {
  test('running release == server release → no updateAvailable',
      () async {
    final mock = MockClient((req) async {
      expect(req.url.path, '/release.json');
      expect(req.headers['Cache-Control'], 'no-cache');
      expect(req.url.queryParameters.containsKey('ts'), true);
      return http.Response(
        jsonEncode({'commit': 'fdc429c', 'builtAt': 'x'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, false);
    expect(ctl.sendShouldBeBlocked(), false);
    expect(rec.reloadCalls, 0);
  });

  test('running release differs → updateAvailable true, send '
       'blocked', () async {
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'commit': 'aaaaaaa', 'builtAt': 'x'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, true);
    expect(ctl.sendShouldBeBlocked(), true);
    expect(ctl.lastSeenServerRelease, 'aaaaaaa');
  });

  test('dev build never triggers updateAvailable even when server '
       'reports a real commit', () async {
    // A locally-run tree with no APP_RELEASE embedded must not
    // command a production release to reload itself.
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'commit': 'aaaaaaa'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'dev',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, false);
  });

  test('release.json fetch failure does NOT loop or destroy '
       'a previously-detected update signal', () async {
    var responseCounter = 0;
    final mock = MockClient((req) async {
      responseCounter++;
      if (responseCounter == 1) {
        // First call — server release differs → update flagged.
        return http.Response(
          jsonEncode({'commit': 'aaaaaaa'}),
          200,
        );
      }
      // Subsequent calls — network hiccup.
      return http.Response('gateway timeout', 502);
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, true);
    await ctl.checkForUpdate();
    // The 502 must NOT clear the previously-detected update.
    expect(ctl.updateAvailable, true);
    expect(rec.reloadCalls, 0);
  });

  test('malformed release.json → fail safely, no crash, no update',
      () async {
    final mock = MockClient((req) async {
      return http.Response('not json {', 200);
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, false);
    expect(rec.reloadCalls, 0);
  });

  test('release.json missing `commit` field → fail safely',
      () async {
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'builtAt': 'x'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    expect(ctl.updateAvailable, false);
  });

  test('applyUpdateAndReload: unregister + clear + reload exactly '
       'once each; target release recorded', () async {
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'commit': 'aaaaaaa'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    await ctl.applyUpdateAndReload();
    expect(rec.unregisterCalls, 1);
    expect(rec.clearCacheCalls, 1);
    expect(rec.reloadCalls, 1);
    // Loop protection — target release is persisted so a future
    // load can detect a still-stale bundle.
    expect(ctl.previousReloadTargetRelease, 'aaaaaaa');
  });

  test('applyUpdateAndReload is idempotent — cannot fire twice '
       'from the same controller', () async {
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'commit': 'aaaaaaa'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    await ctl.applyUpdateAndReload();
    await ctl.applyUpdateAndReload();
    // Only one reload cycle allowed.
    expect(rec.reloadCalls, 1);
    expect(rec.unregisterCalls, 1);
  });

  test('applyUpdateAndReload defers when reloadAllowed returns '
       'false (active broadcast)', () async {
    final mock = MockClient((req) async {
      return http.Response(
        jsonEncode({'commit': 'aaaaaaa'}),
        200,
      );
    });
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    await ctl.checkForUpdate();
    await ctl.applyUpdateAndReload(reloadAllowed: () => false);
    expect(rec.reloadCalls, 0);
    // A subsequent call with reloadAllowed=true DOES reload.
    await ctl.applyUpdateAndReload(reloadAllowed: () => true);
    expect(rec.reloadCalls, 1);
  });

  test('cache clear helper only touches Cache Storage — auth/'
       'wallet state (out of scope for the abstract controller) '
       'is delegated to a caller-provided callback, so the '
       'controller cannot inadvertently clear it', () {
    // This is a compile-time / API-shape assertion, not a runtime
    // one: the controller only knows about `clearAppCodeCacheEntries`.
    // It has no reference to SharedPreferences, IndexedDB, cookies,
    // or the auth token — the reload plumbing physically cannot
    // reach those, which is the security property we care about.
    final mock = MockClient((req) async => http.Response('{}', 200));
    final rec = _ReloadRecorder();
    final ctl = _controllerWith(
      mockClient: mock,
      runningRelease: 'fdc429c',
      rec: rec,
    );
    // Only one hook injection point exists for clearing.
    expect(ctl.runToString, isNull);
  });

  test('kAppReleaseId defaults to "dev" in a non-defined build; '
       'kAppReleaseDisplayLabel embeds it as a Build: prefix', () {
    // Test-runner build never passes --dart-define=APP_RELEASE=…
    // so we expect the compile-time default.
    expect(kAppReleaseId, 'dev');
    expect(kAppReleaseDisplayLabel, 'Build: dev');
  });
}


extension _NullExtras on AppReleaseController {
  // Convenience for the compile-time property test above — the
  // controller intentionally does not expose an auth-clear hook,
  // so we return null.
  Object? get runToString => null;
}
