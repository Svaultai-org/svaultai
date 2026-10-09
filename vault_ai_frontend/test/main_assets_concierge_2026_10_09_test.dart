import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_exposure_panel.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_page.dart';

import 'asset_catalog_2026_10_09_test.dart' show catalogFixture;

// These are synthetic in-process fixtures, not production credentials. Only
// HTTP and the unused recorder plugin are substituted: AppState, dashboard
// navigation, key/MVK gates, bindings, repository and password checker are real.
const _token = 'synthetic-dashboard-session';
const _device = 'synthetic-dashboard-device';
const _vaultId = 'synthetic-dashboard-vault';
const _password = r'zR7!wQ9#bM2@tN8$kL4%';
const _loginTitle = 'Dashboard fixture login';

class _NetworkFixture {
  final List<http.Request> requests = [];
  final List<String> unexpected = [];
  final List<Map<String, dynamic>> encryptedLogins;
  final SecretKey metadataKey;
  String? ciphertext;
  int revision = 0;
  Completer<http.Response>? delayedPassword;

  _NetworkFixture(this.encryptedLogins, this.metadataKey);

  int count(String path, {String? method}) => requests
      .where(
          (r) => r.url.path == path && (method == null || r.method == method))
      .length;

  http.Response json(Object? value) => http.Response(jsonEncode(value), 200,
      headers: {'content-type': 'application/json'});

  Future<http.Response> respond(http.Request request) async {
    requests.add(request);
    if (request.url.host == 'api.pwnedpasswords.com') {
      final digest =
          sha1.convert(utf8.encode(_password)).toString().toUpperCase();
      expect(request.method, 'GET');
      expect(request.url.path, '/range/${digest.substring(0, 5)}');
      expect(request.url.query, isEmpty);
      expect(request.headers['Add-Padding'], 'true');
      expect(request.headers.keys.map((v) => v.toLowerCase()),
          isNot(contains('authorization')));
      expect(request.headers.keys.map((v) => v.toLowerCase()),
          isNot(contains('x-device-id')));
      if (delayedPassword != null) return delayedPassword!.future;
      return http.Response('${digest.substring(5)}:8\n', 200);
    }
    expect(request.url.host, Uri.parse(backendBaseUrl).host);
    expect(request.headers['Authorization'], 'Bearer $_token');
    expect(request.headers['X-Device-Id'], _device);
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
          'status': 'active',
        });
      case 'POST /list-files':
        return json({'files': []});
      case 'GET /folders':
        return json({'path': '', 'folders': [], 'files': []});
      case 'POST /list-secure-items':
        return json({'items': []});
      case 'GET /vault/ciphertext/vault-items':
        return json(encryptedLogins);
      case 'GET /crypto/wallet/asset-catalog':
        return json(catalogFixture());
      case 'GET /crypto/wallet/features':
        return json({
          'walletEngineEnabled': true,
          'mainnetReceiveEnabled': true,
          'mainnetErc20ReceiveEnabled': true,
          'mainnetSendEnabled': true,
          'mainnetSendPaused': false,
        });
      case 'GET /security-center/summary':
        return json({
          'score': 50,
          'score_band': 'moderate',
          'recommendations': [],
          'inheritance': {},
        });
      case 'POST /expiry/active':
        return json({'alerts': [], 'counts': {}, 'engine': 'on'});
      case 'GET /concierge/state':
        return json({'revision': revision, 'ciphertext': ciphertext});
      case 'PUT /concierge/state':
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body.keys.toSet(),
            {'ciphertext', 'envelope_version', 'expected_revision'});
        expect(body['expected_revision'], revision);
        expect(body['envelope_version'], 'v1');
        ciphertext = body['ciphertext'] as String;
        return json({'revision': ++revision});
      case 'GET /concierge/capabilities':
        return json({
          'enabled': true,
          'email_range': {'status': 'not_configured'},
          'email_monitoring': {'status': 'not_configured'},
          'stealer_logs': {'status': 'not_configured'},
        });
      case 'GET /concierge/monitors':
        return json({'monitors': []});
      default:
        unexpected.add('${request.method} ${request.url.path}');
        throw StateError('Unexpected fixture endpoint');
    }
  }

  Future<Map<String, dynamic>> savedState() async {
    final bytes = await aesGcmUnwrap(metadataKey, b64urlDecode(ciphertext!));
    final envelope = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    expect(envelope['purpose'], 'vaultai.concierge.state.v1');
    expect(envelope['vault_id'], _vaultId);
    return Map<String, dynamic>.from(envelope['data'] as Map);
  }

  void assertPrivateWire() {
    final digest =
        sha1.convert(utf8.encode(_password)).toString().toUpperCase();
    for (final request in requests) {
      expect('${request.url} ${request.body}', isNot(contains(_password)));
      expect('${request.url} ${request.body}', isNot(contains(digest)));
      if (request.url.path.startsWith('/concierge/')) {
        expect(request.body, isNot(contains('fixture-owner@example.test')));
        expect(request.body, isNot(contains(_loginTitle)));
      }
    }
    expect(unexpected, isEmpty,
        reason: 'Every real dashboard request must have an explicit fixture');
  }
}

Future<(AppState, _NetworkFixture)> _fixture() async {
  final app = AppState()
    ..sessionToken = _token
    ..vaultId = _vaultId
    ..vaultName = 'Synthetic dashboard vault'
    ..vaultHandle = 'synthetic-dashboard-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingBlockCount = 1
    ..billingPurchasedBytes = 50 * kVaultStorageLimitBytes
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = 51 * kVaultStorageLimitBytes;
  final context = await deriveAndInstallCryptoContext(
      vaultId: _vaultId,
      vaultName: app.vaultName!,
      pin: '123456',
      pinSaltBase64: base64Encode(List.filled(16, 9)),
      iterations: 1,
      source: 'dashboard-integration-fixture');
  expect(context, isNotNull);
  final mvk = SecretKey(List.generate(32, (i) => i + 1));
  ZkActiveMvk.set(mvk: mvk, vaultId: _vaultId, vaultHandle: app.vaultHandle!);
  setApiClientDeviceId(_device);
  app.unlocked = true;
  expect(app.unlocked, isTrue);
  final key = await VaultKeyHierarchy(mvk).metadataKey();
  Future<String> encrypt(Object value) async => b64urlEncode(await aesGcmWrap(
      key, utf8.encode(value is String ? value : jsonEncode(value))));
  return (
    app,
    _NetworkFixture([
      {
        'item_id': 1,
        'item_type_ciphertext': await encrypt('login'),
        'service_ciphertext': await encrypt(_loginTitle),
        'payload_ciphertext': await encrypt({
          'fields': {
            'username': 'fixture-owner@example.test',
            'password': _password,
          },
        }),
      }
    ], key)
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
          '/pin': (_) => const Scaffold(body: Text('PIN fixture route'))
        },
        home: const ChatDashboardPage(),
      ),
    );

Future<void> _openSection(WidgetTester tester, String section) async {
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  final tile = find.byKey(ValueKey('sidebar_section_$section'));
  await tester.ensureVisible(tile);
  await tester.tap(tile);
  await tester.pumpAndSettle();
}

Future<void> _enableChecks(WidgetTester tester) async {
  await tester.ensureVisible(find.text('Manage checks'));
  await tester.tap(find.text('Manage checks'));
  await tester.pumpAndSettle();
  expect(find.text('Choose your privacy checks'), findsOneWidget);
  await tester.tap(find.text('Allow password exposure checks'));
  await tester.pump();
  await tester.ensureVisible(find.text('Save choices'));
  await tester.tap(find.text('Save choices'));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
  });
  tearDown(() {
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'dashboard-integration-cleanup');
    setApiClientDeviceId('');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets(
      'real dashboard opens eight Assets categories and keeps Concierge consent/bindings across rebuilds',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final fixture = await tester.runAsync(_fixture);
    final (app, network) = fixture!;
    addTearDown(() {
      app.unlocked = false;
      app.dispose();
    });
    await http.runWithClient(() async {
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      expect(find.text('PIN fixture route'), findsNothing);
      expect(app.isCryptoEntitled, isTrue);
      await _openSection(tester, 'cryptoVault');
      expect(find.byType(AssetsPage), findsOneWidget);
      for (final category in VaultAssetCategory.values) {
        final tile = find.byKey(Key('assets_category_${category.id}'));
        await tester.scrollUntilVisible(tile, 250,
            scrollable: find.descendant(
                of: find.byType(AssetsPage),
                matching: find.byType(Scrollable)));
        expect(find.descendant(of: tile, matching: find.text(category.label)),
            findsOneWidget);
      }
      expect(network.count('/crypto/wallet/asset-catalog'), 1);
      expect(network.count('/crypto/wallet/features'), 1);

      await _openSection(tester, 'concierge');
      expect(find.byType(ConciergePage), findsOneWidget);
      expect(find.text('Login exposure checks'), findsOneWidget);
      final bindings = tester
          .widget<ConciergeExposurePanel>(find.byType(ConciergeExposurePanel))
          .bindings;
      expect(bindings.captureAccess().isCurrent, isTrue);
      expect(network.count('/concierge/state'), 1);
      expect(network.count('/concierge/capabilities'), 1);
      await _enableChecks(tester);
      final state = await tester.runAsync(network.savedState);
      expect(state!['consent']['enabled'], isTrue);
      expect(state['consent']['background_emails'], isFalse);

      for (var i = 0; i < 3; i++) {
        app.notifyListeners();
        await tester.pumpAndSettle();
        expect(
            tester
                .widget<ConciergeExposurePanel>(
                    find.byType(ConciergeExposurePanel))
                .bindings,
            same(bindings));
      }
      expect(network.count('/concierge/state', method: 'GET'), 1);
      expect(network.count('/concierge/capabilities'), 1);
      await tester.ensureVisible(find.text('Check now'));
      await tester.tap(find.text('Check now'));
      await tester.pumpAndSettle();
      expect(find.text(_loginTitle), findsOneWidget);
      expect(find.textContaining('appears 8 times'), findsOneWidget);
      expect(
          network.requests.where((r) => r.url.host == 'api.pwnedpasswords.com'),
          hasLength(1));
      network.assertPrivateWire();

      app.unlocked = false;
      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(bindings.captureAccess().isCurrent, isFalse);
      expect(find.byType(ConciergeExposurePanel), findsNothing);
      expect(find.text(_loginTitle), findsNothing);
      final requestCount = network.requests.length;
      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(network.requests.length, requestCount);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    }, () => MockClient(network.respond));
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets(
      'dashboard MVK clear fences an in-flight password result without writing stale findings',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final fixture = await tester.runAsync(_fixture);
    final (app, network) = fixture!;
    addTearDown(() {
      app.unlocked = false;
      app.dispose();
    });
    await http.runWithClient(() async {
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      await _openSection(tester, 'concierge');
      await _enableChecks(tester);
      final bindings = tester
          .widget<ConciergeExposurePanel>(find.byType(ConciergeExposurePanel))
          .bindings;
      network.delayedPassword = Completer<http.Response>();
      await tester.ensureVisible(find.text('Check now'));
      await tester.tap(find.text('Check now'));
      // Pump bounded frames, not settle: the real request intentionally awaits
      // its response, and the spinner must stay active until the vault locks.
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 20));
      }
      expect(
          network.requests.where((r) => r.url.host == 'api.pwnedpasswords.com'),
          hasLength(1));
      final writes = network.count('/concierge/state', method: 'PUT');
      ZkActiveMvk.clear();
      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(bindings.captureAccess().isCurrent, isFalse);
      expect(find.byType(ConciergeExposurePanel), findsNothing);
      final digest =
          sha1.convert(utf8.encode(_password)).toString().toUpperCase();
      network.delayedPassword!
          .complete(http.Response('${digest.substring(5)}:8\n', 200));
      await tester.pumpAndSettle();
      expect(find.text(_loginTitle), findsNothing);
      expect(network.count('/concierge/state', method: 'PUT'), writes);
      final requestCount = network.requests.length;
      app.notifyListeners();
      await tester.pumpAndSettle();
      expect(network.requests.length, requestCount);
      network.assertPrivateWire();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    }, () => MockClient(network.respond));
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
}
