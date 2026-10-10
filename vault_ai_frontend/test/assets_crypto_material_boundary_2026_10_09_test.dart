import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

// No authenticated API, account, wallet, provider, or signing fixture is needed
// for this rendering regression. These are the real Assets/Crypto widgets.
Widget _app(Widget home) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          padding: const EdgeInsets.only(top: 59, bottom: 34),
          viewPadding: const EdgeInsets.only(top: 59, bottom: 34),
        ),
        child: child!,
      ),
      home: home,
    );

bool _yellowDoubleFallback(TextStyle? style) =>
    style?.decoration?.contains(TextDecoration.underline) == true &&
    style?.decorationStyle == TextDecorationStyle.double &&
    style?.decorationColor == const Color(0xffffff00);

List<String> _fallbackParagraphs(WidgetTester tester, Finder scope) {
  final paragraphs =
      find.descendant(of: scope, matching: find.byType(RichText));
  return [
    for (final element in paragraphs.evaluate())
      if (_yellowDoubleFallback(
          (element.renderObject! as RenderParagraph).text.style))
        (element.renderObject! as RenderParagraph).text.toPlainText(),
  ];
}

class _DashboardNetwork {
  final requests = <http.Request>[];
  final unexpected = <String>[];

  Future<http.Response> respond(http.Request request) async {
    requests.add(request);
    if (request.url.host != Uri.parse(backendBaseUrl).host ||
        request.headers['Authorization'] !=
            'Bearer material-boundary-synthetic-session' ||
        request.headers['X-Device-Id'] !=
            'material-boundary-synthetic-device') {
      throw StateError('Only the synthetic dashboard destination is allowed');
    }
    Object body;
    switch ('${request.method} ${request.url.path}') {
      case 'POST /vault-stats':
        body = {'login_count': 0, 'file_count': 0, 'storage_used_bytes': 0};
      case 'GET /billing/me':
        body = {
          'included_bytes': kVaultStorageLimitBytes,
          'effective_limit_bytes': 51 * kVaultStorageLimitBytes,
          'purchased_bytes': 50 * kVaultStorageLimitBytes,
          'block_count': 1,
          'status': 'active',
        };
      case 'POST /list-files':
        body = {'files': []};
      case 'GET /folders':
        body = {'path': '', 'folders': [], 'files': []};
      case 'POST /list-secure-items':
        body = {'items': []};
      case 'GET /vault/ciphertext/vault-items':
      case 'GET /vault/ciphertext/vault-ai-memory':
        body = <dynamic>[];
      case 'GET /crypto/wallet/asset-catalog':
        body = {'schema': 'svaultai_asset_catalog_v1', 'assets': []};
      case 'GET /crypto/wallet/features':
        body = {
          'walletEngineEnabled': true,
          'mainnetReceiveEnabled': true,
          'mainnetErc20ReceiveEnabled': true,
          'mainnetSendEnabled': false,
          'mainnetSendPaused': false,
        };
      case 'POST /chat':
        // UI dispatch only: an empty synthetic SSE response, no external AI.
        return http.Response('', 200,
            headers: {'content-type': 'text/event-stream'});
      default:
        if (request.method == 'GET' &&
            RegExp(r'^/crypto/wallet/network/[a-z_]+/[A-Z0-9_]+/receive$')
                .hasMatch(request.url.path)) {
          body = {'wallet_engine': 'no_account'};
        } else {
          unexpected.add('${request.method} ${request.url.path}');
          throw StateError('No fixture for unexpected dashboard operation');
        }
    }
    return http.Response(jsonEncode(body), 200,
        headers: {'content-type': 'application/json'});
  }
}

Future<AppState> _dashboardState() async {
  final app = AppState()
    ..sessionToken = 'material-boundary-synthetic-session'
    ..vaultId = 'material-boundary-synthetic-vault'
    ..vaultName = 'Material boundary fixture'
    ..vaultHandle = 'material-boundary-synthetic-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingBlockCount = 1
    ..billingPurchasedBytes = 50 * kVaultStorageLimitBytes
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = 51 * kVaultStorageLimitBytes;
  await deriveAndInstallCryptoContext(
    vaultId: app.vaultId!,
    vaultName: app.vaultName!,
    pin: '123456',
    pinSaltBase64: base64Encode(List.filled(16, 9)),
    iterations: 1,
    source: 'material-boundary-test',
  );
  ZkActiveMvk.set(
    mvk: SecretKey(List.generate(32, (index) => index + 1)),
    vaultId: app.vaultId!,
    vaultHandle: app.vaultHandle!,
  );
  setApiClientDeviceId('material-boundary-synthetic-device');
  app.unlocked = true;
  return app;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
    final store = AssetLiveStore.instance..clear();
    // Rendering-only no-wallet states avoid conflating an unrelated compact
    // loading-skeleton/Ahem-font overflow with the Material route boundary.
    for (final asset in kCryptoWalletEngineAssets) {
      store.applyState(
        source: 'material-boundary-test',
        asset: asset,
        seq: store.claimSeq(asset),
        state: const DashboardAssetLiveState.noWallet(),
      );
    }
  });
  tearDown(() {
    AssetLiveStore.instance.clear();
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'material-boundary-test-cleanup');
    setApiClientDeviceId('');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets(
      'actual Assets Cryptocurrency navigation keeps Material text boundary and Back after access notification',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(600, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final access = ValueNotifier<bool>(true);
    addTearDown(access.dispose);
    final prompts = <String>[];
    await tester.pumpWidget(_app(AssetsPage(
      accessChanges: access,
      isVaultKeyAvailable: () => access.value,
      cryptocurrency: Builder(
        builder: (_) => CryptoWalletEnginePage(onSendChatPrompt: prompts.add),
      ),
    )));
    await tester.pumpAndSettle();
    final category = find.byKey(const Key('assets_category_cryptocurrency'));
    await tester.ensureVisible(category);
    await tester.tap(category);
    await tester.pumpAndSettle();
    final route = find.byKey(const Key('assets_cryptocurrency_route'));
    expect(route, findsOneWidget);
    expect(find.byType(CryptoWalletEnginePage), findsOneWidget);
    expect(find.byKey(const Key('assets_cryptocurrency_back')), findsOneWidget);
    expect(find.descendant(of: route, matching: find.byType(AppBar)),
        findsOneWidget);
    final bodySafeArea = find.ancestor(
        of: find.byType(CryptoWalletEnginePage),
        matching: find.byType(SafeArea));
    expect(bodySafeArea, findsOneWidget);
    expect(tester.widget<SafeArea>(bodySafeArea).top, isFalse);
    expect(tester.getTopLeft(find.byType(CryptoWalletEnginePage)).dy,
        greaterThanOrEqualTo(59 + kToolbarHeight));
    expect(_fallbackParagraphs(tester, route), isEmpty);
    expect(tester.takeException(), isNull);
    final chip = find.widgetWithText(ActionChip, 'Show my ETH balance');
    expect(chip, findsOneWidget);
    await tester.ensureVisible(chip);
    await tester.tap(chip);
    await tester.pumpAndSettle();
    expect(prompts, ['Show my ETH balance']);
    expect(tester.takeException(), isNull);

    // A lease notification must not rebuild an otherwise valid route into a
    // bare non-Material child. This test makes no claim about auth semantics.
    access.value = false;
    await tester.pumpAndSettle();
    expect(_fallbackParagraphs(tester, route), isEmpty);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byKey(const Key('assets_cryptocurrency_back')));
    await tester.pumpAndSettle();
    expect(find.byType(AssetsPage), findsOneWidget);
    expect(find.byType(CryptoWalletEnginePage), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('actual dashboard Ask AI leaves the pushed Cryptocurrency route',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(600, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final app = (await tester.runAsync(_dashboardState))!;
    addTearDown(() {
      app.unlocked = false;
      app.dispose();
    });
    final network = _DashboardNetwork();
    await http.runWithClient(() async {
      await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
        value: app,
        child: _app(const ChatDashboardPage()),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.menu_rounded));
      await tester.pumpAndSettle();
      final assets = find.byKey(const ValueKey('sidebar_section_cryptoVault'));
      await tester.ensureVisible(assets);
      await tester.tap(assets);
      await tester.pumpAndSettle();
      final cryptoTile =
          find.byKey(const Key('assets_category_cryptocurrency'));
      await tester.ensureVisible(cryptoTile);
      await tester.tap(cryptoTile);
      await tester.pumpAndSettle();
      expect(find.byType(CryptoWalletEnginePage), findsOneWidget);
      final chip = find.widgetWithText(ActionChip, 'Show my ETH balance');
      await tester.ensureVisible(chip);
      await tester.tap(chip);
      await tester.pumpAndSettle();
      expect(find.byType(CryptoWalletEnginePage), findsNothing,
          reason: 'Ask AI must close its own pushed Assets route, not change '
              'only the obscured dashboard behind it.');
      expect(
          find.byKey(const Key('assets_cryptocurrency_route')), findsNothing);
      expect(find.text('Show my ETH balance'), findsOneWidget);
      expect(network.unexpected, isEmpty);
      final chatRequests =
          network.requests.where((r) => r.url.path == '/chat').toList();
      expect(chatRequests, hasLength(1),
          reason: 'One chip tap must dispatch exactly one synthetic chat.');
      expect(chatRequests.single.body, isNot(contains('Show my ETH balance')),
          reason: 'The production send path must encrypt the prompt.');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    }, () => MockClient(network.respond));
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
}
