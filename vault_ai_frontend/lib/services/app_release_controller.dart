/// 2026-07-14 (Round 10 — stale-cache fix): frontend release-update
/// controller.
///
/// SVaultAI is a financial web application. Users must NOT need
/// Incognito, logout, cache clearing, or dev tools to receive a
/// new deployment.
///
/// Contract:
///
///  * The current build's release ID is embedded at build time via
///    `--dart-define=APP_RELEASE=<commit>` and read here via
///    `String.fromEnvironment('APP_RELEASE')`.
///  * On startup, on tab-visibility resume, on app resume, before a
///    Send confirmation, and periodically (5 min) while the tab is
///    open, this controller fetches `/release.json` with cache-
///    busting query + `Cache-Control: no-cache` request headers.
///  * If the server release differs from the running release, the
///    controller marks `updateAvailable=true`. Consumers gate Send
///    on `updateAvailable == false` and can call
///    [applyUpdateAndReload] to force the browser onto the new
///    bundle.
///  * [applyUpdateAndReload] unregisters any Flutter service worker,
///    clears ONLY Cache Storage entries (not `localStorage`,
///    `sessionStorage`, `IndexedDB`, or cookies — those hold the
///    auth session, wallet ciphertext, and user prefs), records
///    the target release ID in `sessionStorage` to prevent a reload
///    loop, and calls `window.location.reload()` exactly once.
///  * After reload, the controller compares the new
///    `String.fromEnvironment('APP_RELEASE')` against the last
///    target release ID. If they match, the reload cycle is done.
///    If they don't, we do NOT reload again automatically — surface
///    a clear diagnostic instead.
///
/// The controller is safe to call on non-web platforms — it becomes
/// a no-op there (uses `kIsWeb` gates).
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

// Web-only imports. Conditional import so unit tests on VM stay
// green and non-web builds compile.
import 'app_release_controller_web_stub.dart'
    if (dart.library.html) 'app_release_controller_web.dart' as web;

/// Release ID embedded at build time. `dev` means an unpublished
/// local build.
const String kAppReleaseId =
    String.fromEnvironment('APP_RELEASE', defaultValue: 'dev');

/// Diagnostic label — surface this in About / Settings so support
/// can confirm which build a user is actually running.
const String kAppReleaseDisplayLabel = 'Build: $kAppReleaseId';

class AppReleaseController {
  AppReleaseController({
    required this.baseUrl,
    this.runningRelease = kAppReleaseId,
    this.pollInterval = const Duration(minutes: 5),
    http.Client? httpClient,
    Future<void> Function()? unregisterServiceWorker,
    Future<void> Function()? clearAppCodeCacheEntries,
    void Function()? reloadPage,
    String? Function()? readLastAttemptedTarget,
    void Function(String targetRelease)? writeLastAttemptedTarget,
  })  : _http = httpClient ?? http.Client(),
        _unregisterServiceWorker =
            unregisterServiceWorker ?? web.unregisterFlutterServiceWorker,
        _clearAppCodeCacheEntries =
            clearAppCodeCacheEntries ?? web.clearAppCodeCacheEntries,
        _reloadPage = reloadPage ?? web.reloadPage,
        _readLastAttemptedTarget =
            readLastAttemptedTarget ?? web.readLastAttemptedTargetRelease,
        _writeLastAttemptedTarget =
            writeLastAttemptedTarget ?? web.writeLastAttemptedTargetRelease;

  /// Backend base URL that serves `/release.json`. Usually the same
  /// origin the Flutter web app was served from.
  final String baseUrl;

  /// Release ID this bundle self-reports. Defaulted from
  /// `String.fromEnvironment('APP_RELEASE')` — override in tests.
  final String runningRelease;

  final Duration pollInterval;

  final http.Client _http;
  final Future<void> Function() _unregisterServiceWorker;
  final Future<void> Function() _clearAppCodeCacheEntries;
  final void Function() _reloadPage;
  final String? Function() _readLastAttemptedTarget;
  final void Function(String targetRelease) _writeLastAttemptedTarget;

  bool _fetchInFlight = false;
  bool _disposed = false;
  String? _serverRelease;
  bool _updateInProgress = false;
  Timer? _pollTimer;

  final _updateNotifier = ValueNotifier<bool>(false);

  /// Consumers listen to this to render "SVaultAI was updated.
  /// Refreshing…" banners and to disable Review/Confirm until the
  /// user chooses to reload.
  ValueListenable<bool> get updateAvailableNotifier => _updateNotifier;

  /// True iff we have fetched `/release.json` at least once AND
  /// the server release differs from the running release.
  bool get updateAvailable => _updateNotifier.value;

  /// True iff a reload has been initiated. Consumers should stop
  /// starting new Send flows once this becomes true.
  bool get updateInProgress => _updateInProgress;

  /// The most recent server release seen (null before the first
  /// successful fetch). Exposed so a Settings page can render
  /// "Running: X · Available: Y".
  String? get lastSeenServerRelease => _serverRelease;

  void start() {
    if (_disposed) return;
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(pollInterval, (_) => checkForUpdate());
    // Fire immediately, then rely on the timer + external events.
    unawaited(checkForUpdate());
  }

  void stop() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  void dispose() {
    _disposed = true;
    stop();
    _updateNotifier.dispose();
  }

  /// Fetch `/release.json` and update `updateAvailable`. Safe to
  /// call from any lifecycle callback. If the fetch fails or the
  /// response is malformed, we DO NOT clear a previously-detected
  /// update — a temporary network hiccup must never re-hide a real
  /// pending update.
  Future<void> checkForUpdate() async {
    if (_disposed || _updateInProgress) return;
    if (_fetchInFlight) return;
    _fetchInFlight = true;
    try {
      final ts = DateTime.now().microsecondsSinceEpoch.toString();
      final uri = Uri.parse('$baseUrl/release.json?ts=$ts');
      final resp = await _http.get(uri, headers: {
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
      });
      if (resp.statusCode != 200) return;
      final decoded = jsonDecode(resp.body);
      if (decoded is! Map<String, dynamic>) return;
      final commit = decoded['commit'];
      if (commit is! String || commit.isEmpty) return;
      _serverRelease = commit;
      // Only trigger updateAvailable when the running bundle
      // reports a non-dev release identifier. A dev build never
      // forces a real production release to reload itself.
      if (runningRelease != 'dev') {
        // A previously observed mismatch can converge after the new bundle
        // activates. Assign in both directions so the banner cannot remain
        // latched after release.json and the running build agree.
        _updateNotifier.value = commit != runningRelease;
      }
    } catch (_) {
      // Silent — a transient error must not clear a real update
      // signal nor reveal internal RPC state to the UI.
    } finally {
      _fetchInFlight = false;
    }
  }

  /// Perform the reload sequence:
  ///
  ///   1. mark `updateInProgress` so no new Send starts;
  ///   2. record the target release in `sessionStorage` to detect a
  ///      failed reload cycle;
  ///   3. unregister any Flutter service worker;
  ///   4. clear ONLY Cache Storage (never `localStorage`,
  ///      `sessionStorage`, `IndexedDB`, or cookies);
  ///   5. reload the page.
  ///
  /// If [reloadAllowed] returns `false`, the update is deferred —
  /// consumers pass a check that returns `false` when a signing or
  /// broadcast operation is in flight.
  Future<void> applyUpdateAndReload({
    bool Function()? reloadAllowed,
  }) async {
    if (_disposed || _updateInProgress) return;
    if (reloadAllowed != null && !reloadAllowed()) return;
    _updateInProgress = true;
    final target = _serverRelease;
    if (target != null) {
      // Loop protection: remember the release we tried to reach.
      _writeLastAttemptedTarget(target);
    }
    try {
      await _unregisterServiceWorker();
    } catch (_) {
      // Continue — clearing caches + reload still helps.
    }
    try {
      await _clearAppCodeCacheEntries();
    } catch (_) {
      // Continue — the reload itself often gets the new shell.
    }
    _reloadPage();
  }

  /// Returns the release ID we last tried to reach on a previous
  /// reload attempt, if any. Consumers can use this to detect a
  /// loop and surface a "still on old release" diagnostic instead
  /// of triggering another reload.
  String? get previousReloadTargetRelease => _readLastAttemptedTarget();

  /// Consumer helper — call before starting a Send flow. Returns
  /// `true` iff Send should be blocked (update available and
  /// applyUpdateAndReload should be offered).
  bool sendShouldBeBlocked() {
    return updateAvailable || _updateInProgress;
  }
}
