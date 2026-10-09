import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/device_id.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/concierge_exposure.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_exposure_panel.dart';

// REAL ISOLATED QA ONLY. This is NOT the production acceptance/deletion test.
// Run only on a newly created iPhone Simulator and the independently verified,
// empty, disposable QA backend. No app.main(), persisted-session hydration,
// existing-account login, billing mutation, AI, wallet send or deletion helper.
// Native OPAQUE, secure storage, KDF, MVK, encrypted login/state and UI are real.
// The only external request is a GET-only public range query for the synthetic
// password "password"; no vault metadata or authorization accompanies it.
const _qaBase = 'http://127.0.0.1:18081';
const _qaPrefix = 'qa_native_concierge_';
const _password = 'password';
const _loginTitle = 'Local QA exposure example';
const _email = 'isolated-qa@example.test';

class _LoopbackQaClient extends http.BaseClient {
  _LoopbackQaClient()
      : _inner = IOClient(
            HttpClient()..connectionTimeout = const Duration(seconds: 8));

  final http.Client _inner;
  final Set<String> _createdVaultTokens = {};
  final List<String> operations = [];
  int passwordRanges = 0;
  bool _closed = false;

  static const _allowedBackendOperations = {
    'GET /health',
    'POST /auth/zk-register-init',
    'POST /auth/zk-register-finalize',
    'POST /auth/zk-login-init',
    'POST /auth/zk-login-finalize',
    'POST /auth/logout',
    'GET /auth/me',
    'POST /devices/register',
    'GET /vault-meta',
    'POST /vault/ciphertext/vault-items',
    'GET /vault/ciphertext/vault-items',
    'GET /concierge/capabilities',
    'GET /concierge/state',
    'PUT /concierge/state',
    'GET /concierge/monitors',
    'POST /vault-stats',
    'GET /billing/me',
    'POST /list-files',
    'GET /folders',
    'POST /list-secure-items',
    'GET /security-center/summary',
    'POST /expiry/active',
  };

  void allowCreatedVaultToken(String token) {
    if (token.isEmpty) throw StateError('Missing isolated QA session');
    _createdVaultTokens.add(token);
  }

  int count(String operation) =>
      operations.where((value) => value == operation).length;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (_closed) throw StateError('Local QA transport closed');
    // A redirect may not bypass the exact destination/path guard below.
    request.followRedirects = false;
    final uri = request.url;
    final headers = {
      for (final entry in request.headers.entries)
        entry.key.toLowerCase(): entry.value
    };
    final body = request is http.Request ? request.body : '';
    if (request is! http.Request) {
      throw StateError('Non-allowlisted local QA request type');
    }
    if (uri.scheme == 'https' &&
        uri.host == 'api.pwnedpasswords.com' &&
        uri.port == 443) {
      final prefix = sha1
          .convert(utf8.encode(_password))
          .toString()
          .toUpperCase()
          .substring(0, 5);
      if (request.method != 'GET' ||
          uri.path != '/range/$prefix' ||
          uri.query.isNotEmpty ||
          uri.userInfo.isNotEmpty ||
          body.isNotEmpty ||
          headers['add-padding'] != 'true' ||
          headers.containsKey('authorization') ||
          headers.containsKey('x-device-id')) {
        throw StateError('Unsafe public synthetic password range request');
      }
      passwordRanges++;
      operations.add('GET public-synthetic-password-range');
      return _inner.send(request);
    }
    if (uri.scheme != 'http' ||
        uri.host != '127.0.0.1' ||
        uri.port != 18081 ||
        uri.userInfo.isNotEmpty ||
        uri.fragment.isNotEmpty) {
      throw StateError('Refusing all non-loopback QA backend requests');
    }
    final operation = '${request.method} ${uri.path}';
    if (!_allowedBackendOperations.contains(operation)) {
      throw StateError('Refusing non-allowlisted QA operation: $operation');
    }
    final unauthenticated =
        operation == 'GET /health' || operation.startsWith('POST /auth/zk-');
    if (!unauthenticated) {
      final bearer = headers['authorization'];
      if (!_createdVaultTokens.any((token) => bearer == 'Bearer $token')) {
        throw StateError('Refusing a session not created by this QA run');
      }
    }
    // Never retain or print bearer tokens, PINs, opaque exchanges or ciphertext.
    // Credential writes/Concierge state must remain opaque on the real wire.
    if (uri.path.startsWith('/concierge/') ||
        operation == 'POST /vault/ciphertext/vault-items') {
      if (body.contains(_password) ||
          body.contains(_email) ||
          body.contains(_loginTitle)) {
        throw StateError('Refusing plaintext in isolated encrypted-state wire');
      }
    }
    if (uri.path.startsWith('/concierge/')) {
      if (headers['x-device-id'] != apiClientDeviceId() ||
          headers['x-device-id'] == null ||
          headers['x-device-id']!.isEmpty) {
        throw StateError('Isolated Concierge device header missing or stale');
      }
    }
    operations.add(operation);
    return _inner.send(request);
  }

  // http.post/get and a disposed dashboard may close their zone-created client.
  // They share this scoped wrapper; its real transport lives only for the test.
  @override
  void close() {}
  void closeOwnedTransport() {
    _closed = true;
    _createdVaultTokens.clear();
    _inner.close();
  }
}

Future<void> _waitUntil(
    WidgetTester tester, bool Function() ready, String checkpoint,
    {Duration timeout = const Duration(seconds: 40),
    void Function()? onTimeout}) async {
  final deadline = DateTime.now().add(timeout);
  while (!ready() && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  if (!ready()) onTimeout?.call();
  expect(ready(), true, reason: 'Isolated native QA checkpoint: $checkpoint');
  await tester.pump();
}

Future<void> _openSection(WidgetTester tester, String section) async {
  final menu = find.byIcon(Icons.menu_rounded).hitTestable();
  await _waitUntil(tester, () => menu.evaluate().isNotEmpty, 'dashboard menu');
  await tester.tap(menu);
  await _settleRoute(tester);
  final tile = find.byKey(ValueKey('sidebar_section_$section'));
  await _waitUntil(tester, () => tile.evaluate().isNotEmpty, 'opened drawer');
  await tester.ensureVisible(tile);
  await _waitUntil(tester, () => tile.hitTestable().evaluate().isNotEmpty,
      'tappable drawer section');
  await tester.tap(tile.hitTestable());
  await _settleRoute(tester);
}

Future<void> _settleRoute(WidgetTester tester) async {
  await tester.pumpAndSettle(const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));
}

bool _buttonEnabled(String label) => find
    .ancestor(
        of: find.text(label),
        matching: find.byWidgetPredicate((widget) =>
            widget is ButtonStyleButton && widget.onPressed != null))
    .evaluate()
    .isNotEmpty;

Widget _dashboard(AppState app) => ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        routes: {
          '/pin': (_) => const Scaffold(body: Text('Local QA locked vault'))
        },
        home: const ChatDashboardPage(),
      ),
    );

Future<void> _installRealSession(
    AppState app, VaultAIClient api, _LoopbackQaClient transport,
    {required String token,
    required String vaultId,
    required String name,
    required String handle,
    required String pin,
    required SecretKey mvk,
    required SecretKey sk}) async {
  transport.allowCreatedVaultToken(token);
  await app.setSession(
      token: token,
      vaultIdValue: vaultId,
      vaultNameValue: name,
      vaultHandleValue: handle,
      displayNameValue: 'Isolated native QA');
  final device = await api.registerDevice(
      authToken: token,
      deviceId: apiClientDeviceId()!,
      label: 'Isolated native QA');
  expect(device['status'], 'trusted');
  ZkActiveMvk.set(mvk: mvk, vaultId: vaultId, vaultHandle: handle);
  ZkActiveSkVault.set(skVault: sk, vaultId: vaultId);
  final meta = await api.getVaultMeta(vaultName: name, authToken: token);
  expect(meta['pin_salt'], isA<String>());
  expect(meta['kdf_iterations'], isA<int>());
  expect(
      await deriveAndInstallCryptoContext(
          vaultId: vaultId,
          vaultName: name,
          pin: pin,
          pinSaltBase64: meta['pin_salt'] as String,
          iterations: meta['kdf_iterations'] as int,
          source: 'isolated-native-qa-real-auth'),
      isNotNull);
  app.markUnlocked();
  await app.refreshBilling();
  expect(app.billingLoadState, BillingLoadState.loaded);
  expect(app.billingBlockCount, 0);
  expect(app.billingPurchasedBytes, 0);
  expect(await NativeSecureStore.readString('session_token') == token, true,
      reason: 'Real native secure-store session round trip');
  expect(await const FlutterSecureStorage().read(key: 'session_token') == token,
      true,
      reason: 'Prove native Keychain storage, not the debug fallback');
}

Future<Map<String, dynamic>> _savedState(AppState app) async {
  final token = app.sessionToken!;
  final vaultId = app.vaultId!;
  final mvk = ZkActiveMvk.current();
  final context = VaultCryptoRegistry.current;
  final access = ConciergeAccessLease(
      isCurrent: () =>
          app.authed &&
          app.unlocked &&
          app.sessionToken == token &&
          app.vaultId == vaultId &&
          identical(ZkActiveMvk.current(), mvk) &&
          identical(VaultCryptoRegistry.current, context));
  final repository = ConciergeVaultRepository(
      baseUrl: _qaBase,
      authToken: token,
      vaultId: vaultId,
      deviceId: apiClientDeviceId()!);
  try {
    return (await repository.readEncryptedState(access))!;
  } finally {
    repository.close();
  }
}

void main() {
  _LoopbackQaClient? activeTransport;
  // Native frame/pointer callbacks capture their registration zone. Bind them
  // to the strict factory as well as the test body so engine-driven builds
  // cannot silently construct an unguarded client. No transport exists until
  // all compile-target/native-storage safety guards have passed below.
  http.runWithClient(() {
    final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
    binding.scheduleForcedFrame();
    _registerIsolatedNativeTest(
        binding, (transport) => activeTransport = transport);
  }, () {
    final transport = activeTransport;
    if (transport == null) {
      throw StateError('Isolated native QA transport is not ready');
    }
    return transport;
  });
}

void _registerIsolatedNativeTest(IntegrationTestWidgetsFlutterBinding binding,
    void Function(_LoopbackQaClient?) bindTransport) {
  testWidgets('real isolated iPhone Concierge auth/encrypted-state lifecycle',
      (tester) async {
    // All guards run before the first network call or native-store write.
    expect(const bool.fromEnvironment('SVAULTAI_ISOLATED_NATIVE_QA'), true,
        reason: 'Explicit isolated QA opt-in is required');
    expect(backendBaseUrl, _qaBase,
        reason: 'Never run this account-creation target against production');
    expect(kIsWeb || kReleaseMode, false);
    expect(defaultTargetPlatform, TargetPlatform.iOS);
    expect(NativeSecureStore.useSharedPreferencesForTesting, false,
        reason: 'Use the actual native secure-store plugin in this target');
    for (final key in [
      'session_token',
      'last_vault_name',
      'last_vault_handle',
      'last_display_name',
      deviceIdStorageKey
    ]) {
      expect(await NativeSecureStore.readString(key), isNull,
          reason: 'Refusing a Simulator with existing account/device state');
    }
    expect(currentDeviceId(), isNull);
    final holdMs = const int.fromEnvironment('SVAULTAI_QA_CAPTURE_HOLD_MS');
    expect(holdMs >= 0 && holdMs <= 10000, true);
    Future<void> checkpoint(String label) async {
      binding.reportData ??= {};
      binding.reportData!['scope'] = 'isolated-loopback-qa-not-production';
      (binding.reportData!.putIfAbsent('verified_checkpoints', () => <String>[])
              as List<String>)
          .add(label);
      debugPrint('[qa-native-checkpoint] $label');
      if (holdMs > 0) await tester.pump(Duration(milliseconds: holdMs));
    }

    final random = Random.secure();
    final name = '$_qaPrefix${DateTime.now().microsecondsSinceEpoch}_'
        '${random.nextInt(1 << 24).toRadixString(16)}';
    expect(name.startsWith(_qaPrefix), true);
    final pin = '${10000000 + random.nextInt(90000000)}';
    final transport = _LoopbackQaClient();
    bindTransport(transport);
    final app = AppState();
    String? ownedDevice;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
    try {
      await http.runWithClient(() async {
        try {
          final healthResponse = await http.get(Uri.parse('$_qaBase/health'));
          expect(healthResponse.statusCode, 200);
          final health = jsonDecode(healthResponse.body) as Map;
          expect(health['status'], 'ok');
          expect(health['db'], 'connected');
          ownedDevice = await getOrCreateDeviceId();
          setApiClientDeviceId(ownedDevice!);
          final api = VaultAIClient(baseUrl: _qaBase);
          Future<Map<String, dynamic>> authPost(
              String path, Map<String, dynamic> body,
              {String? bearerToken}) async {
            final headers = {
              'Content-Type': 'application/json',
              'X-Device-Id': ownedDevice!
            };
            if (bearerToken != null) {
              headers['Authorization'] = 'Bearer $bearerToken';
            }
            final outgoing = Map<String, dynamic>.from(body);
            if (path == '/auth/zk-login-finalize') {
              outgoing.putIfAbsent('device_id', () => ownedDevice!);
            }
            final response = await http
                .post(Uri.parse('$_qaBase$path'),
                    headers: headers, body: jsonEncode(outgoing))
                .timeout(const Duration(seconds: 30));
            if (response.statusCode != 200) {
              throw StateError('Isolated QA authentication failed: '
                  '$path (${response.statusCode})');
            }
            return Map<String, dynamic>.from(jsonDecode(response.body) as Map);
          }

          final zk = ZkAuthService(authPost);
          final registration = await zk.registerVault(
              vaultName: name, displayName: 'Isolated native QA', pin: pin);
          final ownedVault = registration.vaultId;
          await _installRealSession(app, api, transport,
              token: registration.sessionToken,
              vaultId: ownedVault,
              name: name,
              handle: registration.vaultHandle,
              pin: pin,
              mvk: registration.mvk,
              sk: registration.skVaultPrivate);
          final saved = await api.tryZkVaultItemCiphertextUpsert(
              baseUrl: _qaBase,
              authToken: app.sessionToken!,
              itemType: 'login',
              service: _loginTitle,
              payload: {
                'fields': {'username': _email, 'password': _password}
              });
          expect(saved?['created'], true);
          expect(saved?['item_id'], isA<int>());
          final inventoryResponse = await http.get(
              Uri.parse('$_qaBase/vault/ciphertext/vault-items'),
              headers: {
                'Authorization': 'Bearer ${app.sessionToken}',
                'X-Device-Id': ownedDevice!
              });
          expect(inventoryResponse.statusCode, 200);
          expect((jsonDecode(inventoryResponse.body) as List), hasLength(1));
          expect(inventoryResponse.body.contains(_password), false);
          expect(inventoryResponse.body.contains(_loginTitle), false);

          await tester.pumpWidget(_dashboard(app));
          await _settleRoute(tester);
          expect(
              MediaQuery.sizeOf(tester.element(find.byType(ChatDashboardPage)))
                  .shortestSide,
              lessThan(600));
          await _openSection(tester, 'cryptoVault');
          expect(find.byType(CryptoVaultLockedCard), findsOneWidget,
              reason: 'The genuine fresh vault retains the free billing gate');
          expect(find.byType(AssetsPage), findsNothing);
          await checkpoint('fresh-free-assets-upgrade-gate');

          await _openSection(tester, 'concierge');
          await _waitUntil(
              tester,
              () => find
                  .textContaining('Free checks for exposed, weak and reused')
                  .evaluate()
                  .isNotEmpty,
              'real free Concierge capabilities', onTimeout: () {
            final panels = find.byType(ConciergeExposurePanel).evaluate();
            final leaseCurrent = panels.isNotEmpty &&
                tester
                    .widget<ConciergeExposurePanel>(
                        find.byType(ConciergeExposurePanel))
                    .bindings
                    .captureAccess()
                    .isCurrent;
            debugPrint('[qa-native-loopback] concierge timeout: '
                'panel=${panels.isNotEmpty}, lease=$leaseCurrent, '
                'authed=${app.authed}, unlocked=${app.unlocked}, '
                'crypto=${VaultCryptoRegistry.current != null}, '
                'mvk=${ZkActiveMvk.current() != null}, '
                'capabilityRequests=${transport.count('GET /concierge/capabilities')}, '
                'stateRequests=${transport.count('GET /concierge/state')}, '
                'paths=${transport.operations.join(', ')}');
          });
          expect(transport.count('GET /concierge/capabilities'), 1,
              reason: 'Native frame-created HTTP must use guarded loopback');
          expect(find.textContaining('are not enabled in this release.'),
              findsOneWidget);
          expect(find.textContaining('Email status:'), findsNothing);
          await checkpoint('real-free-concierge-policy');
          await tester.ensureVisible(find.text('Manage checks'));
          await tester.tap(find.text('Manage checks'));
          await _settleRoute(tester);
          expect(find.text('Allow password exposure checks'), findsOneWidget);
          expect(find.text('Email exposure checks'), findsNothing);
          expect(
              find.text('Authorize background email monitoring'), findsNothing);
          expect(
              find.text('Include supported stealer-log checks'), findsNothing);
          await checkpoint('real-password-only-consent');
          await tester.tap(find.text('Allow password exposure checks'));
          await tester.pump();
          await tester.ensureVisible(find.text('Save choices'));
          await tester.tap(find.text('Save choices'));
          await _waitUntil(
              tester,
              () =>
                  find.text('Save choices').evaluate().isEmpty &&
                  transport.count('PUT /concierge/state') >= 1 &&
                  _buttonEnabled('Check now'),
              'real encrypted consent persisted');
          final consent = await _savedState(app);
          expect(consent['consent']['enabled'], true);
          expect(consent['consent']['background_emails'], false);
          expect(consent['consent']['stealer_logs'], false);
          await tester.ensureVisible(find.text('Check now'));
          await tester.tap(find.text('Check now'));
          await _waitUntil(
              tester,
              () =>
                  find
                      .textContaining('times in known exposed-password data.')
                      .evaluate()
                      .isNotEmpty &&
                  transport.count('PUT /concierge/state') >= 2,
              'real public password provider and encrypted findings');
          final completed = await _savedState(app);
          final findings =
              (completed['findings'] as List).whereType<Map>().toList();
          expect(
              findings.any(
                  (row) => row['kind'] == 'pwned' && (row['count'] as int) > 0),
              true);
          expect(findings.any((row) => row['kind'] == 'weak'), true);
          expect(completed['last_password_check_at'], isNotNull);
          expect(completed['last_email_check_at'], isNull);
          expect(transport.passwordRanges, 1);
          await tester.ensureVisible(
              find.textContaining('times in known exposed-password data.'));
          await checkpoint('real-free-password-findings-saved');

          await tester.pumpWidget(const SizedBox.shrink());
          await _settleRoute(tester);
          await app.signOut();
          expect(app.sessionToken, isNull);
          expect(ZkActiveMvk.current(), isNull);
          expect(ZkActiveSkVault.current(), isNull);
          expect(VaultCryptoRegistry.current, isNull);
          expect(await NativeSecureStore.readString('session_token'), isNull);
          final login = await zk.loginVault(vaultName: name, pin: pin);
          expect(login.vaultId == ownedVault, true,
              reason: 'Only the vault created by this QA run may be restored');
          await _installRealSession(app, api, transport,
              token: login.sessionToken,
              vaultId: ownedVault,
              name: name,
              handle: login.vaultHandle,
              pin: pin,
              mvk: login.mvk,
              sk: login.skVaultPrivate);
          await tester.pumpWidget(_dashboard(app));
          await _settleRoute(tester);
          await _openSection(tester, 'concierge');
          await _waitUntil(
              tester,
              () => find
                  .textContaining('times in known exposed-password data.')
                  .evaluate()
                  .isNotEmpty,
              'real encrypted findings restored after sign-out/relogin');
          expect(find.text(_loginTitle), findsWidgets);
          expect(transport.passwordRanges, 1,
              reason:
                  'Rehydration must not masquerade as a new provider query');
          expect((await _savedState(app))['consent']['enabled'], true);
          await tester.ensureVisible(
              find.textContaining('times in known exposed-password data.'));
          await checkpoint('real-findings-rehydrated-after-relogin');
          final bindings = tester
              .widget<ConciergeExposurePanel>(
                  find.byType(ConciergeExposurePanel))
              .bindings;
          final lease = bindings.captureAccess();
          expect(lease.isCurrent, true);
          ZkActiveMvk.clear();
          ZkActiveSkVault.clear();
          VaultCryptoRegistry.clear(reason: 'isolated-native-qa-lock');
          app.unlocked = false;
          app.notifyListeners();
          await _settleRoute(tester);
          expect(lease.isCurrent, false);
          expect(find.byType(ConciergeExposurePanel), findsNothing);
          expect(find.text(_loginTitle), findsNothing);
          await expectLater(bindings.readEncryptedState(lease),
              throwsA(isA<ConciergeAccessExpired>()));
          await checkpoint('real-private-findings-hidden-after-lock');
          expect(transport.count('POST /auth/zk-register-finalize'), 1);
          expect(transport.count('POST /auth/zk-login-finalize'), 1);
          expect(
              transport.operations.any((op) =>
                  op.contains('email-range') ||
                  op.contains('/send') ||
                  op.contains('/delete') ||
                  op.startsWith('POST /concierge/monitors')),
              false);
          expect(tester.takeException(), isNull);
        } finally {
          await tester.pumpWidget(const SizedBox.shrink());
          await _settleRoute(tester);
          // Local sign-out only. The created backend account remains in the
          // disposable QA database; this file intentionally has no deletion.
          await app.signOut();
          await app.clearSession(keepLastVaultName: false);
          if (ownedDevice != null &&
              await NativeSecureStore.readString(deviceIdStorageKey) ==
                  ownedDevice) {
            await NativeSecureStore.deleteString(deviceIdStorageKey);
          }
        }
      }, () => transport);
    } finally {
      app.dispose();
      transport.closeOwnedTransport();
      bindTransport(null);
      setApiClientDeviceId('');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
              const MethodChannel('com.llfbandit.record/messages'), null);
    }
  }, timeout: const Timeout(Duration(minutes: 8)));
}
