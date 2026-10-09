import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_exposure_panel.dart';

// NON-PRODUCTION NATIVE FIXTURE ONLY. Do not combine this test with a live
// acceptance/account-deletion harness or reuse its synthetic views as evidence
// of live availability. We never call app.main(), hydrate a persisted account,
// sign in, purchase, create/delete an account, or send a wallet transaction.
// All HTTP is intercepted in process; preferences and the unused recorder are
// isolated. AES/KDF, vault/MVK gates, dashboard, repository and checker are real.
const _token = 'synthetic-native-session';
const _device = 'synthetic-native-device';
const _vaultId = 'synthetic-native-vault';
const _loginTitle = 'Synthetic native login';
const _password = r'zR7!wQ9#bM2@tN8$kL4%';

void _requireFixture(bool condition, String safeReason) {
  // Native frame callbacks may execute while pump/settle holds Flutter's
  // asynchronous-test guard. Enforce wire assertions without guarded expect()
  // and without interpolating request values into an exception or log.
  if (!condition) throw StateError(safeReason);
}

class _NativeNetworkFixture {
  _NativeNetworkFixture(this.logins, this.metadataKey);

  final List<Map<String, dynamic>> logins;
  final SecretKey metadataKey;
  final List<http.Request> requests = [];
  final List<String> unexpected = [];
  String? ciphertext;
  int revision = 0;
  Completer<http.Response>? delayedPassword;

  int count(String path, {String? method}) => requests
      .where(
          (r) => r.url.path == path && (method == null || r.method == method))
      .length;
  int get passwordRequests =>
      requests.where((r) => r.url.host == 'api.pwnedpasswords.com').length;
  http.Response json(Object? body) => http.Response(jsonEncode(body), 200,
      headers: {'content-type': 'application/json'});

  String get _digest =>
      sha1.convert(utf8.encode(_password)).toString().toUpperCase();
  http.Response passwordResult(int occurrences) =>
      http.Response('${_digest.substring(5)}:$occurrences\n', 200);

  Future<http.Response> respond(http.Request request) async {
    requests.add(request);
    if (request.url.host == 'api.pwnedpasswords.com') {
      final headers = {
        for (final entry in request.headers.entries)
          entry.key.toLowerCase(): entry.value
      };
      _requireFixture(
          request.url.scheme == 'https' &&
              request.url.port == 443 &&
              request.url.userInfo.isEmpty &&
              request.url.fragment.isEmpty &&
              request.method == 'GET' &&
              request.url.path == '/range/${_digest.substring(0, 5)}' &&
              request.url.query.isEmpty &&
              request.body.isEmpty &&
              headers['add-padding'] == 'true' &&
              !headers.containsKey('authorization') &&
              !headers.containsKey('x-device-id'),
          'Unsafe synthetic password range request');
      return delayedPassword?.future ?? passwordResult(8);
    }
    final backend = Uri.parse(backendBaseUrl);
    _requireFixture(
        request.url.scheme == backend.scheme &&
            request.url.host == backend.host &&
            request.url.port == backend.port &&
            request.url.userInfo.isEmpty &&
            request.url.fragment.isEmpty,
        'Non-allowlisted synthetic backend destination');
    _requireFixture(request.headers['Authorization'] == 'Bearer $_token',
        'Synthetic backend session does not match fixture');
    _requireFixture(request.headers['X-Device-Id'] == _device,
        'Synthetic backend device does not match fixture');
    switch ('${request.method} ${request.url.path}') {
      case 'POST /vault-stats':
        return json(
            {'login_count': 1, 'file_count': 0, 'storage_used_bytes': 0});
      case 'GET /billing/me':
        return json({
          'included_bytes': kVaultStorageLimitBytes,
          'effective_limit_bytes': 51 * kVaultStorageLimitBytes,
          'purchased_bytes': 50 * kVaultStorageLimitBytes,
          'block_count': 1,
          'status': 'active'
        });
      case 'POST /list-files':
        return json({'files': []});
      case 'GET /folders':
        return json({'path': '', 'folders': [], 'files': []});
      case 'POST /list-secure-items':
        return json({'items': []});
      case 'GET /vault/ciphertext/vault-items':
        return json(logins);
      case 'GET /crypto/wallet/asset-catalog':
        // Simulate an undeployed/missing real-world-token integration, while
        // the existing cryptocurrency capabilities are still known. The UI
        // must not invent Gold availability, balances or wallet actions.
        return http.Response('{"detail":"fixture_catalog_not_deployed"}', 404);
      case 'GET /crypto/wallet/features':
        return json({
          'walletEngineEnabled': true,
          'mainnetReceiveEnabled': true,
          'mainnetErc20ReceiveEnabled': true,
          'mainnetSendEnabled': true,
          'mainnetSendPaused': false
        });
      case 'GET /crypto/wallet/network/ethereum_sepolia/ETH/receive':
      case 'GET /crypto/wallet/network/ethereum_sepolia/USDT_ERC20/receive':
      case 'GET /crypto/wallet/network/ethereum_sepolia/USDC_ERC20/receive':
      case 'GET /crypto/wallet/network/ethereum_mainnet/ETH/receive':
      case 'GET /crypto/wallet/network/ethereum_mainnet/USDT_ERC20/receive':
      case 'GET /crypto/wallet/network/ethereum_mainnet/USDC_ERC20/receive':
        // Existing Cryptocurrency navigation may read wallet presence. The
        // fixture contains no wallet and never fabricates a zero balance.
        return json({'wallet_engine': 'no_account'});
      case 'GET /crypto/wallet/network/ethereum_sepolia/ETH/transactions':
      case 'GET /crypto/wallet/network/ethereum_mainnet/ETH/transactions':
        return json({'status': 'unavailable', 'items': []});
      case 'GET /security-center/summary':
        return json({
          'score': 50,
          'score_band': 'moderate',
          'recommendations': [],
          'inheritance': {}
        });
      case 'POST /expiry/active':
        return json({'alerts': [], 'counts': {}, 'engine': 'on'});
      case 'GET /concierge/state':
        return json({'revision': revision, 'ciphertext': ciphertext});
      case 'PUT /concierge/state':
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        _requireFixture(
            setEquals(body.keys.toSet(),
                {'ciphertext', 'envelope_version', 'expected_revision'}),
            'Synthetic encrypted state has unexpected envelope fields');
        _requireFixture(body['expected_revision'] == revision,
            'Synthetic encrypted state revision mismatch');
        _requireFixture(body['envelope_version'] == 'v1',
            'Synthetic encrypted state version mismatch');
        _requireFixture(
            body['ciphertext'] is String &&
                (body['ciphertext'] as String).isNotEmpty,
            'Synthetic encrypted state ciphertext missing');
        ciphertext = body['ciphertext'] as String;
        return json({'revision': ++revision});
      case 'GET /concierge/capabilities':
        return json({
          'enabled': true,
          'provider_mode': 'free',
          'password_breaches': {'status': 'available', 'mode': 'client_range'},
          'email_range': {'status': 'deferred'},
          'email_monitoring': {'status': 'deferred'},
          'stealer_logs': {'status': 'deferred'}
        });
      case 'GET /concierge/monitors':
        // Owned-monitor discovery for possible withdrawal is management only;
        // it performs no email query and creates no background authorization.
        return json({'monitors': []});
      default:
        unexpected.add('${request.method} ${request.url.path}');
        throw StateError('Unexpected synthetic native endpoint');
    }
  }

  Future<Map<String, dynamic>> savedState() async {
    final plain = await aesGcmUnwrap(metadataKey, b64urlDecode(ciphertext!));
    final envelope = jsonDecode(utf8.decode(plain)) as Map<String, dynamic>;
    expect(envelope['purpose'], 'vaultai.concierge.state.v1');
    expect(envelope['vault_id'], _vaultId);
    return Map<String, dynamic>.from(envelope['data'] as Map);
  }

  void assertPrivateWire() {
    for (final request in requests) {
      final wire = '${request.url} ${request.body}';
      expect(wire, isNot(contains(_password)));
      expect(wire, isNot(contains(_digest)));
      if (request.url.path.startsWith('/concierge/')) {
        expect(wire, isNot(contains('fixture-owner@example.test')));
        expect(wire, isNot(contains(_loginTitle)));
      }
    }
    expect(unexpected, isEmpty,
        reason: 'The fixture rejects every non-allowlisted operation');
    expect(count('/concierge/email-range'), 0);
    expect(count('/concierge/monitors', method: 'POST'), 0);
    expect(requests.any((r) => r.url.path.contains('/send/')), false);
    expect(requests.any((r) => r.url.path.startsWith('/auth/')), false);
  }
}

Future<(AppState, _NativeNetworkFixture)> _fixture() async {
  final app = AppState()
    ..sessionToken = _token
    ..vaultId = _vaultId
    ..vaultName = 'Synthetic native vault'
    ..vaultHandle = 'synthetic-native-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingBlockCount = 1
    ..billingPurchasedBytes = 50 * kVaultStorageLimitBytes
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = 51 * kVaultStorageLimitBytes;
  final keyContext = await deriveAndInstallCryptoContext(
      vaultId: _vaultId,
      vaultName: app.vaultName!,
      pin: '127801',
      pinSaltBase64: base64Encode(List.filled(16, 13)),
      iterations: 1,
      source: 'synthetic-native-integration');
  expect(keyContext, isNotNull);
  final mvk = SecretKey(List.generate(32, (i) => i + 1));
  ZkActiveMvk.set(mvk: mvk, vaultId: _vaultId, vaultHandle: app.vaultHandle!);
  setApiClientDeviceId(_device);
  app.unlocked = true;
  final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
  Future<String> encrypt(Object value) async => b64urlEncode(await aesGcmWrap(
      metadataKey, utf8.encode(value is String ? value : jsonEncode(value))));
  return (
    app,
    _NativeNetworkFixture([
      {
        'item_id': 1,
        'item_type_ciphertext': await encrypt('login'),
        'service_ciphertext': await encrypt(_loginTitle),
        'payload_ciphertext': await encrypt({
          'fields': {
            'username': 'fixture-owner@example.test',
            'password': _password
          }
        })
      }
    ], metadataKey)
  );
}

Widget _dashboard(AppState app) => ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        routes: {
          '/pin': (_) => const Scaffold(body: Text('Synthetic locked route'))
        },
        home: const ChatDashboardPage(),
      ),
    );

Future<void> _openSection(WidgetTester tester, String section) async {
  final menu = find.byIcon(Icons.menu_rounded).hitTestable();
  await _waitFor(tester, menu, 'dashboard menu after native route transition');
  await tester.tap(menu);
  await tester.pumpAndSettle(const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));
  final tile = find.byKey(ValueKey('sidebar_section_$section'));
  await _waitFor(tester, tile, 'opened drawer section $section');
  await tester.ensureVisible(tile);
  await _waitFor(tester, tile.hitTestable(), 'drawer section is tappable');
  await tester.tap(tile.hitTestable());
  await tester.pumpAndSettle(const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));
}

// On a native integration binding, pumpAndSettle waits for rendered frames,
// not completion of AES-GCM/other platform-backed futures. Wait for the actual
// bounded readiness condition before inspecting dependent UI or ciphertext.
Future<void> _waitUntil(
    WidgetTester tester, bool Function() ready, String checkpoint,
    {void Function()? onTimeout}) async {
  final deadline = DateTime.now().add(const Duration(seconds: 30));
  while (!ready() && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  if (!ready()) onTimeout?.call();
  expect(ready(), true, reason: 'Native fixture checkpoint: $checkpoint');
  // A deliberately pending provider request keeps an animated progress
  // indicator alive. Do not wait for all animation while checking dispatch.
  await tester.pump();
}

Future<void> _waitFor(WidgetTester tester, Finder finder, String checkpoint) =>
    _waitUntil(tester, () => finder.evaluate().isNotEmpty, checkpoint);

Future<void> _tapAssetCategory(
    WidgetTester tester, Finder tile, Finder scrollable) async {
  // The ten-category list keeps tiles built outside its painted viewport.
  // Finding a tile alone does not prove that its center receives a native tap.
  await tester.scrollUntilVisible(tile, -200, scrollable: scrollable);
  await Scrollable.ensureVisible(tester.element(tile), alignment: 0.5);
  await tester.pumpAndSettle(const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));
  final tappable = tile.hitTestable();
  await _waitFor(tester, tappable, 'centered asset category receives native tap');
  expect(tappable, findsOneWidget);
  await tester.tap(tappable);
  // The incoming route is built before the outgoing list becomes offstage.
  // Finish that transition before asserting route-specific titles/controls.
  await tester.pumpAndSettle(const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));
}

void main() {
  _NativeNetworkFixture? activeFixture;
  // Native frame/pointer callbacks retain the zone in which Flutter registers
  // them. A zone around only the test body does not intercept clients created
  // by later engine-driven builds. Register the binding and frame callbacks
  // inside the same strictly guarded factory; there is no real HTTP fallback.
  http.runWithClient(() {
    final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
    binding.scheduleForcedFrame();
    _registerNativeTests((fixture) => activeFixture = fixture);
  },
      () => MockClient((request) {
            final fixture = activeFixture;
            if (fixture == null) {
              throw StateError('Native fixture transport is not ready');
            }
            return fixture.respond(request);
          }));
}

void _registerNativeTests(void Function(_NativeNetworkFixture?) bindFixture) {
  setUp(() {
    // Do not read/write a simulator's previously persisted real vault session.
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
  });
  tearDown(() {
    bindFixture(null);
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'synthetic-native-test-cleanup');
    setApiClientDeviceId('');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets(
      'synthetic iPhone Assets and free Concierge preserve encrypted state and lock fences',
      (tester) async {
    expect(kIsWeb, false,
        reason: 'Run this target on native iOS, not a browser');
    expect(defaultTargetPlatform, TargetPlatform.iOS,
        reason: 'An actual iPhone Simulator/device run is required');
    final (app, network) = await _fixture();
    bindFixture(network);
    addTearDown(() {
      app.unlocked = false;
      app.dispose();
    });
    await http.runWithClient(() async {
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      final viewport =
          MediaQuery.sizeOf(tester.element(find.byType(ChatDashboardPage)));
      expect(viewport.shortestSide, lessThan(600),
          reason:
              'Use an iPhone viewport, not iPad or an overridden test size');
      expect(find.text('Synthetic locked route'), findsNothing);
      await _openSection(tester, 'cryptoVault');
      expect(find.byType(AssetsPage), findsOneWidget);
      final assetScrollable = find.descendant(
          of: find.byType(AssetsPage), matching: find.byType(Scrollable));
      expect(VaultAssetCategory.values, hasLength(10));
      for (final category in VaultAssetCategory.values) {
        final tile = find.byKey(Key('assets_category_${category.id}'));
        await tester.scrollUntilVisible(tile, 200, scrollable: assetScrollable);
        expect(find.descendant(of: tile, matching: find.text(category.label)),
            findsOneWidget);
        expect(
            find.descendant(
                of: tile,
                matching: find.text(
                    category == VaultAssetCategory.cryptocurrency
                        ? 'Your existing cryptocurrency wallets'
                        : 'Coming soon')),
            findsOneWidget);
      }
      final gold = find.byKey(const Key('assets_category_digital_gold'));
      await _tapAssetCategory(tester, gold, assetScrollable);
      await _waitFor(tester,
          find.textContaining('No balance, receive address, send action'),
          'unavailable category route after native navigation');
      expect(find.text('Digital Gold'), findsOneWidget);
      expect(find.text('Coming soon'), findsOneWidget);
      expect(find.textContaining('No balance, receive address, send action'),
          findsOneWidget);
      expect(find.byType(CryptoWalletEngineAssetDetailPage), findsNothing);
      expect(find.byType(CryptoWalletEngineReceivePanel), findsNothing);
      expect(find.byType(CryptoWalletEngineSendPanel), findsNothing);
      await tester.tap(find.byTooltip('Back'));
      await tester.pumpAndSettle();

      final cryptocurrency =
          find.byKey(const Key('assets_category_cryptocurrency'));
      await _tapAssetCategory(tester, cryptocurrency, assetScrollable);
      await _waitFor(
          tester,
          find.byKey(const Key('assets_cryptocurrency_route')),
          'existing cryptocurrency route');
      expect(find.byType(CryptoWalletEnginePage), findsOneWidget);
      expect(
          find.byKey(const Key('assets_cryptocurrency_back')), findsOneWidget);
      await tester.tap(find.byKey(const Key('assets_cryptocurrency_back')));
      await _waitFor(tester, find.byType(AssetsPage), 'Assets after Back');
      await tester.pumpAndSettle(const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));

      await _openSection(tester, 'concierge');
      await _waitUntil(
          tester,
          () => find
              .textContaining('Free checks for exposed, weak and reused')
              .evaluate()
              .isNotEmpty,
          'free Concierge capabilities and decrypted inventory', onTimeout: () {
        final panels = find.byType(ConciergeExposurePanel).evaluate();
        final leaseCurrent = panels.isNotEmpty &&
            tester
                .widget<ConciergeExposurePanel>(
                    find.byType(ConciergeExposurePanel))
                .bindings
                .captureAccess()
                .isCurrent;
        // Diagnostics contain only static UI/key-state booleans and operation
        // paths: never request bodies, credentials, hashes or ciphertext.
        debugPrint('[qa-native-fixture] concierge timeout: '
            'panel=${panels.isNotEmpty}, lease=$leaseCurrent, '
            'authed=${app.authed}, unlocked=${app.unlocked}, '
            'crypto=${VaultCryptoRegistry.current != null}, '
            'mvk=${ZkActiveMvk.current() != null}, '
            'capabilityRequests=${network.count('/concierge/capabilities')}, '
            'stateRequests=${network.count('/concierge/state', method: 'GET')}, '
            'paths=${network.requests.map((r) => '${r.method} ${r.url.path}').join(', ')}');
      });
      expect(network.count('/concierge/capabilities'), 1,
          reason: 'Native frame-created HTTP must use the strict fixture');
      expect(find.textContaining('Free checks for exposed, weak and reused'),
          findsOneWidget);
      expect(find.textContaining('are not enabled in this release.'),
          findsOneWidget);
      expect(find.textContaining('Email status:'), findsNothing);
      final bindings = tester
          .widget<ConciergeExposurePanel>(find.byType(ConciergeExposurePanel))
          .bindings;
      await tester.ensureVisible(find.text('Manage checks'));
      await tester.tap(find.text('Manage checks'));
      await tester.pumpAndSettle();
      expect(find.text('Allow password exposure checks'), findsOneWidget);
      expect(find.text('Email exposure checks'), findsNothing);
      expect(find.text('Authorize background email monitoring'), findsNothing);
      expect(find.text('Include supported stealer-log checks'), findsNothing);
      await tester.tap(find.text('Allow password exposure checks'));
      await tester.pump();
      await tester.ensureVisible(find.text('Save choices'));
      await tester.tap(find.text('Save choices'));
      await _waitUntil(
          tester,
          () =>
              network.ciphertext != null &&
              find.text('Save choices').evaluate().isEmpty,
          'encrypted password-only consent saved');
      final consent = await network.savedState();
      expect(consent['consent']['enabled'], true);
      expect(consent['consent']['background_emails'], false);
      await tester.ensureVisible(find.text('Check now'));
      await tester.tap(find.text('Check now'));
      await _waitFor(tester, find.textContaining('appears 8 times'),
          'password findings rendered');
      await _waitUntil(tester, () => network.revision >= 2,
          'encrypted completed findings saved');
      expect(find.text(_loginTitle), findsOneWidget);
      expect(find.textContaining('appears 8 times'), findsOneWidget);
      expect(network.passwordRequests, 1);
      final completed = await network.savedState();
      expect(completed['findings'].single['count'], 8);
      expect(completed['last_password_check_at'], isNotNull);
      expect(completed['last_email_check_at'], isNull);
      network.assertPrivateWire();

      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(
          tester
              .widget<ConciergeExposurePanel>(
                  find.byType(ConciergeExposurePanel))
              .bindings,
          same(bindings));
      expect(network.count('/concierge/state', method: 'GET'), 1);

      // Remount the real screen: saved preferences/results must decrypt from
      // the encrypted fixture envelope, without making another provider query.
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      await _openSection(tester, 'concierge');
      await _waitFor(tester, find.textContaining('appears 8 times'),
          'encrypted findings rehydrated');
      expect(network.count('/concierge/state', method: 'GET'), 2);
      expect(find.text(_loginTitle), findsOneWidget);
      expect(find.textContaining('appears 8 times'), findsOneWidget);
      expect(network.passwordRequests, 1);
      final remountedBindings = tester
          .widget<ConciergeExposurePanel>(find.byType(ConciergeExposurePanel))
          .bindings;
      final currentLease = remountedBindings.captureAccess();
      expect(currentLease.isCurrent, true);

      network.delayedPassword = Completer<http.Response>();
      await tester.ensureVisible(find.text('Check now'));
      await tester.tap(find.text('Check now'));
      await _waitUntil(tester, () => network.passwordRequests == 2,
          'delayed password range request dispatched');
      expect(network.passwordRequests, 2);
      final writesBeforeLock = network.count('/concierge/state', method: 'PUT');
      ZkActiveMvk.clear();
      app.unlocked = false;
      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(find.byType(ConciergeExposurePanel), findsNothing);
      expect(find.text(_loginTitle), findsNothing);
      expect(currentLease.isCurrent, false);
      expect(remountedBindings.captureAccess().isCurrent, false);
      network.delayedPassword!.complete(network.passwordResult(999));
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pumpAndSettle();
      expect(
          network.count('/concierge/state', method: 'PUT'), writesBeforeLock);
      expect((await network.savedState())['findings'].single['count'], 8);
      network.assertPrivateWire();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
    }, () => MockClient(network.respond));
  });
}
