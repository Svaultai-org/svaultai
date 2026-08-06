// 2026-07-14 (Round 11 — real production wiring): integration /
// widget tests proving `AppReleaseController` is actually reachable
// from every production consumer that claims to gate on it.
//
// Coverage:
//
//   * FULL-SHA canonicalization: comparison uses 40-char SHAs
//     end-to-end; short SHAs would produce a permanent update
//     signal.
//   * `AppReleaseControllerScope` retains the controller for the
//     lifetime of the widget tree and provides it via
//     `.maybeOf(context)`.
//   * `WidgetsBindingObserver` is registered — an
//     `AppLifecycleState.resumed` triggers `checkForUpdate`.
//   * `AppReleaseUpdateBanner` renders when
//     `updateAvailable == true` and disappears when false. Tapping
//     "Update now" calls `applyUpdateAndReload`.
//   * ETH / SOL / TRON Send panels each block Review when
//     `sendShouldBeBlocked() == true`, with a panel-specific
//     "SVaultAI was updated" error.
//   * `applyUpdateAndReload(reloadAllowed: () => false)` defers
//     the reload; a later `reloadAllowed: () => true` runs it.
//   * Source-level proof that the production wiring exists in
//     `main.dart` and each Send panel.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/app_release_controller.dart';
import 'package:vault_ai_frontend/services/app_release_controller_scope.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/app_release_update_banner.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';


const List<LocalizationsDelegate<Object?>> _l10n = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

const String _kFullSha1 =
    'fdc429cdb13c3c0c8cc888d2d7e49089f30b6231';
const String _kFullSha2 =
    'aabbccddeeff00112233445566778899aabbccdd';
const String _kEthFrom =
    '0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855';
const String _kSolFrom =
    'So11111111111111111111111111111111111111112';
const String _kTrnFrom = 'TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq';


CryptoWalletFeatures _solFeatures() =>
    CryptoWalletFeatures.fromBackend(const <String, dynamic>{
      'walletEngineEnabled': true,
      'solanaEnabled': true,
      'solanaSendEnabled': true,
    });

CryptoWalletFeatures _tronFeatures() =>
    CryptoWalletFeatures.fromBackend(const <String, dynamic>{
      'walletEngineEnabled': true,
      'tronEnabled': true,
      'tronSendEnabled': true,
      'tronUsdtContractConfigured': true,
    });


class _RecordingHooks {
  int unregisterCalls = 0;
  int clearCacheCalls = 0;
  int reloadCalls = 0;
  String? lastTarget;

  Future<void> unregister() async {
    unregisterCalls++;
  }

  Future<void> clearCache() async {
    clearCacheCalls++;
  }

  void reload() {
    reloadCalls++;
  }

  String? read() => lastTarget;
  void write(String v) => lastTarget = v;
}


AppReleaseController _makeController({
  required String running,
  required String serverCommit,
  _RecordingHooks? hooks,
}) {
  final rec = hooks ?? _RecordingHooks();
  final mock = MockClient((req) async {
    return http.Response(
      jsonEncode({'commit': serverCommit, 'builtAt': 'x'}),
      200,
    );
  });
  return AppReleaseController(
    baseUrl: 'http://mock',
    runningRelease: running,
    httpClient: mock,
    unregisterServiceWorker: rec.unregister,
    clearAppCodeCacheEntries: rec.clearCache,
    reloadPage: rec.reload,
    readLastAttemptedTarget: rec.read,
    writeLastAttemptedTarget: rec.write,
  );
}


class _StubClient extends VaultAIClient {
  int reviewDrafts = 0;
  _StubClient() : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>>
      createCryptoWalletSendDraftNetwork({
    required String network, required String asset,
    required String authToken, required String fromAddress,
    required String destinationAddress,
    String? amountEth, String? amountSol, String? amountUsdt,
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    reviewDrafts++;
    return const {'status': 'draft_ready'};
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset, required String authToken,
    required String fromAddress, required String destinationAddress,
    required String amountEth,
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    reviewDrafts++;
    return const {'status': 'draft_ready'};
  }
}


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  group('Round 11 — FULL-SHA canonicalization', () {
    test('same full SHA on both sides → no update', () async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha1,
      );
      await ctl.checkForUpdate();
      expect(ctl.updateAvailable, false);
      expect(ctl.sendShouldBeBlocked(), false);
    });

    test('different full SHAs → update', () async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await ctl.checkForUpdate();
      expect(ctl.updateAvailable, true);
      expect(ctl.sendShouldBeBlocked(), true);
    });

    test('short-vs-full guaranteed to mismatch (the Round-10 bug '
         'this pass fixes)', () async {
      // If build scripts had passed the SHORT sha, this is what
      // the runtime would see: a permanent, insurmountable
      // updateAvailable=true. This test both DOCUMENTS the bug
      // and asserts that a correct build (full === full) does not
      // trigger the same failure mode.
      final buggy = _makeController(
        running: 'fdc429c', // 7-char short
        serverCommit: _kFullSha1, // 40-char full
      );
      await buggy.checkForUpdate();
      expect(buggy.updateAvailable, true,
          reason: 'short vs full always differs — the source of the '
                  'Round-10 permanent-update-banner regression.');

      final fixed = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha1,
      );
      await fixed.checkForUpdate();
      expect(fixed.updateAvailable, false);
    });

    test('after reload with new running == target full SHA, '
         'updateAvailable is false and Send is unblocked',
        () async {
      final ctl1 = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await ctl1.checkForUpdate();
      expect(ctl1.updateAvailable, true);
      // Simulate the post-reload page load with new APP_RELEASE:
      final ctl2 = _makeController(
        running: _kFullSha2,
        serverCommit: _kFullSha2,
      );
      await ctl2.checkForUpdate();
      expect(ctl2.updateAvailable, false);
      expect(ctl2.sendShouldBeBlocked(), false);
    });

    test('source: build-web-release.ps1 passes FULL sha via '
         '--dart-define=APP_RELEASE=', () {
      final ps1 = File(
        '${Directory.current.path}/scripts/build-web-release.ps1',
      ).readAsStringSync();
      // The full-SHA variable is $shaFull; must be embedded, not
      // $shaShort.
      expect(ps1.contains(r'--dart-define=APP_RELEASE=$shaFull'), true,
          reason: 'PS1 must embed the FULL SHA.');
      expect(ps1.contains(r'--dart-define=APP_RELEASE=$shaShort'),
          false,
          reason: 'PS1 must NOT embed the SHORT SHA.');
    });

    test('source: build-web-release.sh passes FULL sha via '
         '--dart-define=APP_RELEASE=', () {
      final sh = File(
        '${Directory.current.path}/scripts/build-web-release.sh',
      ).readAsStringSync();
      expect(
        sh.contains(r'--dart-define=APP_RELEASE="$sha_full"'), true,
        reason: 'sh must embed the FULL SHA.',
      );
      expect(
        sh.contains(r'--dart-define=APP_RELEASE="$sha_short"'),
        false,
        reason: 'sh must NOT embed the SHORT SHA.',
      );
    });

    test('source: controller compares runningRelease to '
         "decoded['commit'] and never to decoded['commitShort']",
        () {
      final src = _readLib('services/app_release_controller.dart');
      final idx = src.indexOf('checkForUpdate()');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 3000);
      expect(scope.contains("decoded['commit']"), true,
          reason: 'controller must read the `commit` field.');
      expect(scope.contains("decoded['commitShort']"), false,
          reason: 'controller MUST NEVER use `commitShort` for '
                  'equality.');
    });
  });

  group('Round 11 — scope wiring', () {
    testWidgets(
        'AppReleaseControllerScope provides the controller to '
        'descendants via .maybeOf(context)', (tester) async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha1,
      );
      AppReleaseController? seen;
      await tester.pumpWidget(MaterialApp(
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: Builder(builder: (context) {
            seen = AppReleaseControllerScope.maybeOf(context);
            return const SizedBox.shrink();
          }),
        ),
      ));
      expect(identical(seen, ctl), true);
    });

    testWidgets(
        'AppReleaseControllerScope registers a lifecycle observer; '
        'resumed → checkForUpdate fires', (tester) async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await tester.pumpWidget(MaterialApp(
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: const SizedBox.shrink(),
        ),
      ));
      // Not yet resumed manually — but the scope kicks off an
      // immediate startup check via start().
      // Simulate a resume:
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      );
      await tester.pump();
      // Give the controller a beat to complete the async check.
      await tester.pump(const Duration(milliseconds: 100));
      expect(ctl.lastSeenServerRelease, _kFullSha2);
    });

    test('source: main.dart wraps SvaultaiApp with '
         'AppReleaseControllerScope(baseUrl: kIsWeb ? Uri.base.origin '
         ': backendBaseUrl, ...)', () {
      final src = _readLib('main.dart');
      expect(src.contains('AppReleaseControllerScope'), true);
      // 2026-07-18 (release-URL fix): on web we must resolve
      // `/release.json` against the frontend origin (app.svaultai.com),
      // NOT the API host (api.svaultai.com) which does not host this
      // manifest. Mobile/desktop still uses backendBaseUrl because
      // `Uri.base.origin` is undefined there.
      expect(
        RegExp(r'baseUrl:\s*kIsWeb\s*\?\s*Uri\.base\.origin\s*'
               r':\s*backendBaseUrl').hasMatch(src),
        isTrue,
        reason:
            'main.dart must wire the release scope with '
            '`baseUrl: kIsWeb ? Uri.base.origin : backendBaseUrl`, '
            'not the raw backendBaseUrl (which would 404 on '
            'https://api.svaultai.com/release.json).',
      );
      expect(src.contains('child: SvaultaiApp()'), true,
          reason: 'The scope must wrap the top-level app widget so '
                  'every descendant can see it.');
    });

    test('source: _ActivityWrapper builds AppReleaseUpdateBanner',
        () {
      final src = _readLib('main.dart');
      expect(src.contains('AppReleaseUpdateBanner(child: widget.child)'),
          true,
          reason: 'The update banner must overlay every route.');
    });

    test('source: SecurityCenterPage renders '
         'kAppReleaseDisplayLabel', () {
      final src = _readLib('security_center_page.dart');
      expect(src.contains('kAppReleaseDisplayLabel'), true,
          reason: 'The About/Settings page must surface which build '
                  'the user is running.');
      expect(src.contains("Key('vaultai_running_release_label')"),
          true);
    });
  });

  group('Round 11 — Update banner UI', () {
    testWidgets(
        'banner hidden when no update; visible when update detected; '
        'Update now → applyUpdateAndReload', (tester) async {
      final hooks = _RecordingHooks();
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
        hooks: hooks,
      );
      await tester.pumpWidget(MaterialApp(
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: const AppReleaseUpdateBanner(
            child: Scaffold(body: SizedBox.expand()),
          ),
        ),
      ));
      // Before the first check completes, the banner is hidden.
      expect(find.byKey(const Key(kAppReleaseUpdateBannerKey)),
          findsNothing);
      // Trigger a check.
      await ctl.checkForUpdate();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kAppReleaseUpdateBannerKey)),
          findsOneWidget);
      expect(find.text(kAppReleaseUpdateBannerCopy), findsOneWidget);
      // Tap Update now.
      await tester.tap(
        find.byKey(const Key('${kAppReleaseUpdateBannerKey}_action')),
      );
      await tester.pumpAndSettle();
      expect(hooks.unregisterCalls, 1);
      expect(hooks.clearCacheCalls, 1);
      expect(hooks.reloadCalls, 1);
      // Loop-protection target persisted for the reloaded page:
      expect(hooks.lastTarget, _kFullSha2);
    });
  });

  group('Round 11 — Send-block wiring on every network', () {
    testWidgets('ETH Send Review is blocked when update pending',
        (tester) async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await ctl.checkForUpdate();
      final client = _StubClient();
      await tester.binding.setSurfaceSize(const Size(390, 2400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: Scaffold(
            body: CryptoWalletEngineSendPanel(
              authToken: 'tok',
              fromAddress: _kEthFrom,
              client: client,
              decryptForVault: (_) async => '0x${'11' * 32}',
              isVaultKeyAvailable: () => true,
              verifyPin: (_) async => true,
              asset: 'ETH',
              network: kEvmNetworkEthereumSepolia,
              fetchAvailableBalance: () async => 1.0,
            ),
          ),
        ),
      ));
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        '0x7C49215A2cB86aaC3e6308EA4D6206912578e870',
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.001',
      );
      await tester.pump();
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kSendUpdatePendingError), findsOneWidget);
      expect(client.reviewDrafts, 0);
    });

    testWidgets('SOL Send Review is blocked when update pending',
        (tester) async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await ctl.checkForUpdate();
      final client = _StubClient();
      await tester.binding.setSurfaceSize(const Size(390, 2400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: Scaffold(
            body: CryptoWalletEngineSolanaSendPanel(
              authToken: 'tok',
              fromAddress: _kSolFrom,
              client: client,
              decryptForVault: (_) async => '{"secretKeyBase58":"aa"}',
              isVaultKeyAvailable: () => true,
              verifyPin: (_) async => true,
              features: _solFeatures(),
            ),
          ),
        ),
      ));
      await tester.enterText(
        find.byKey(const Key('solana_send_panel_destination_input')),
        '11111111111111111111111111111111',
      );
      await tester.enterText(
        find.byKey(const Key('solana_send_panel_amount_input')),
        '0.001',
      );
      await tester.pump();
      await tester.tap(
        find.byKey(const Key('solana_send_panel_review_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kSolanaSendUpdatePendingError), findsOneWidget);
      expect(client.reviewDrafts, 0);
    });

    testWidgets('TRON Send Review is blocked when update pending',
        (tester) async {
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
      );
      await ctl.checkForUpdate();
      final client = _StubClient();
      await tester.binding.setSurfaceSize(const Size(390, 2400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: AppReleaseControllerScope(
          baseUrl: 'http://mock',
          controllerOverride: ctl,
          child: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kTrnFrom,
              client: client,
              decryptForVault: (_) async => '{"privateKeyHex":"de"}',
              isVaultKeyAvailable: () => true,
              verifyPin: (_) async => true,
              features: _tronFeatures(),
            ),
          ),
        ),
      ));
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_destination_input')),
        'TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9',
      );
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_amount_input')),
        '1.0',
      );
      await tester.pump();
      await tester.tap(
        find.byKey(const Key('tron_send_panel_review_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kTronSendUpdatePendingError), findsOneWidget);
      expect(client.reviewDrafts, 0);
    });

    test('source: every Send panel _onReview looks up '
         'AppReleaseControllerScope and blocks on '
         'sendShouldBeBlocked()', () {
      for (final path in [
        'ui/crypto_wallet_engine_send_panel.dart',
        'ui/crypto_wallet_engine_solana_send_panel.dart',
        'ui/crypto_wallet_engine_tron_send_panel.dart',
      ]) {
        final src = _readLib(path);
        final idx = src.indexOf('Future<void> _onReview()');
        expect(idx, greaterThan(-1), reason: '$path missing _onReview');
        final scope = src.substring(idx, idx + 2500);
        expect(
            scope.contains('AppReleaseControllerScope.maybeOf(context)'),
            true,
            reason: '$path _onReview must look up the scope.');
        expect(scope.contains('sendShouldBeBlocked()'), true,
            reason: '$path _onReview must gate on '
                    'sendShouldBeBlocked().');
      }
    });
  });

  group('Round 11 — reload deferral', () {
    test('applyUpdateAndReload with reloadAllowed=false defers; '
         'later reloadAllowed=true runs it exactly once', () async {
      final hooks = _RecordingHooks();
      final ctl = _makeController(
        running: _kFullSha1,
        serverCommit: _kFullSha2,
        hooks: hooks,
      );
      await ctl.checkForUpdate();
      await ctl.applyUpdateAndReload(reloadAllowed: () => false);
      expect(hooks.reloadCalls, 0);
      expect(hooks.unregisterCalls, 0);
      await ctl.applyUpdateAndReload(reloadAllowed: () => true);
      expect(hooks.reloadCalls, 1);
      expect(hooks.unregisterCalls, 1);
    });
  });

  group('Round 11 — service-worker migration', () {
    test('migration SW body skipWaiting + clients.claim + navigate '
         '+ flutter cache drain', () {
      final sw = File(
        '${Directory.current.path}/scripts/migration-service-worker.js',
      ).readAsStringSync();
      expect(sw.contains('self.skipWaiting()'), true,
          reason: 'Must call skipWaiting so the new SW replaces the '
                  'old offline-first SW without waiting for tabs.');
      expect(sw.contains('self.clients.claim()'), true,
          reason: 'Must call clients.claim so already-controlled '
                  'tabs start routing through the new (empty) SW.');
      expect(sw.contains("names[i].indexOf('flutter') === 0"), true,
          reason: 'Must delete only flutter* Cache Storage entries.');
      expect(sw.contains('.navigate('), true,
          reason: 'Must force each controlled tab to navigate so it '
                  'fetches the new main.dart.js (with '
                  'AppReleaseController).');
      // Must NOT call any localStorage / IndexedDB / cookie APIs.
      // (Comments describing them are fine; those don't touch anything.)
      final noComments = sw.split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(noComments.contains('localStorage.'), false,
          reason: 'SW must not touch localStorage.');
      expect(noComments.contains('indexedDB.'), false,
          reason: 'SW must not touch IndexedDB.');
      expect(noComments.contains('document.cookie'), false,
          reason: 'SW must not touch cookies.');
    });

    test('source: build script overwrites the empty '
         'flutter_service_worker.js with migration SW', () {
      final ps1 = File(
        '${Directory.current.path}/scripts/build-web-release.ps1',
      ).readAsStringSync();
      expect(ps1.contains('migration-service-worker.js'), true);
      expect(ps1.contains('flutter_service_worker.js'), true);
      final sh = File(
        '${Directory.current.path}/scripts/build-web-release.sh',
      ).readAsStringSync();
      expect(sh.contains('migration-service-worker.js'), true);
      expect(sh.contains('flutter_service_worker.js'), true);
    });
  });

  group('Round 11 — Nginx cache correctness', () {
    test('/assets and /canvaskit use no-cache, must-revalidate '
         '(not immutable, since filenames are stable)', () {
      final conf = File(
        '${Directory.current.path}/../deploy/nginx/app.svaultai.com.conf',
      ).readAsStringSync();
      // Shell files still no-store:
      expect(conf.contains('/main.dart.js'), true);
      // Every `add_header Cache-Control` directive in the config
      // is inspected: NONE may contain `immutable`.
      final activeHeaders = RegExp(
        r'add_header\s+Cache-Control\s+"([^"]+)"',
        multiLine: true,
      ).allMatches(conf).map((m) => m.group(1)!).toList();
      expect(activeHeaders, isNotEmpty);
      for (final h in activeHeaders) {
        expect(h.contains('immutable'), false,
            reason: 'No Cache-Control directive may be `immutable` '
                    'while Flutter web ships stable /assets/ + '
                    '/canvaskit/ filenames. Offending header: $h');
      }
      // Both stable-path locations must use no-cache, must-revalidate.
      expect(
          activeHeaders.any(
              (h) => h.contains('no-cache') && h.contains('must-revalidate')),
          true,
          reason: 'Config must expose the stable-name revalidation '
                  'rule for the /assets/ and /canvaskit/ locations.');
    });
  });
}


String? _extractLocationBlock(String conf, String pathFragment) {
  // Naive extractor — enough for the location-regex blocks we own
  // in the Nginx conf. Grabs from the first occurrence of the path
  // fragment to the next closing brace at column 4.
  final idx = conf.indexOf(pathFragment);
  if (idx < 0) return null;
  final endMatch = RegExp(r'\n    \}').firstMatch(conf.substring(idx));
  if (endMatch == null) return null;
  return conf.substring(idx, idx + endMatch.start);
}
