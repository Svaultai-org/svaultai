import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/release_feature_contract.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/theme.dart';

// NATIVE DEMO ONLY: real app widgets, AES/KDF and local vault workflows, with
// every HTTP request intercepted in process. Never app.main(), live
// account auth, wallet creation, signing, transfer, purchase or account delete.
// Native secure storage is deliberately replaced by empty in-memory prefs.
// Synthetic ciphertext survives a local sign-out/remount, not a real OPAQUE
// registration/login. Wallets are absent: never invent holdings or addresses.
// Captures are demonstration screenshots, not live-transfer/provider evidence
// or proof of a Google Play eligible-install in-app update/review prompt.
const _token = 'store-screenshot-demo-session';
const _device = 'store-screenshot-demo-device';
const _vaultId = 'store-screenshot-demo-vault';
const _vaultName = 'Demo vault';
const _handle = 'store-screenshot-demo-handle';
const _pin = '127801';
const _loginTitle = 'Weekend Planner';
const _username = 'demo@example.test';
const _password = 'password';
const _memoryTitle = 'Favorite color';
const _fileName = 'vault-demo-note.txt';
const _fileText = 'A digital place for the things that matter.\n'
    'This is a harmless demonstration note, not a personal document.';

void _require(bool valid, String reason) {
  if (!valid) throw StateError(reason);
}

class _DemoTransport extends http.BaseClient {
  _DemoTransport(this.metadataKey);
  final SecretKey metadataKey;
  final operations = <String>[];
  final unexpected = <String>[];
  final items = <Map<String, dynamic>>[];
  final memories = <Map<String, dynamic>>[];
  final files = <Map<String, dynamic>>[];
  final encryptedFileBytes = <String, Uint8List>{};
  int itemSerial = 0;
  int revision = 0;
  String? conciergeCiphertext;
  bool disposed = false;

  int count(String operation) => operations.where((v) => v == operation).length;

  Future<http.StreamedResponse> _json(Object? body, {int status = 200}) async =>
      http.StreamedResponse(Stream.value(utf8.encode(jsonEncode(body))), status,
          headers: {'content-type': 'application/json'});

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    _require(!disposed, 'Demo transport is closed');
    request.followRedirects = false;
    final uri = request.url;
    final headers = {
      for (final entry in request.headers.entries)
        entry.key.toLowerCase(): entry.value,
    };
    final operation = '${request.method} ${uri.path}';
    if (uri.scheme == 'https' && uri.host == 'api.pwnedpasswords.com') {
      final digest =
          sha1.convert(utf8.encode(_password)).toString().toUpperCase();
      _require(
          request is http.Request &&
              uri.port == 443 &&
              uri.userInfo.isEmpty &&
              uri.query.isEmpty &&
              uri.fragment.isEmpty &&
              operation == 'GET /range/${digest.substring(0, 5)}' &&
              request.body.isEmpty &&
              headers['add-padding'] == 'true' &&
              !headers.containsKey('authorization') &&
              !headers.containsKey('x-device-id'),
          'Unsafe demo password range lookup');
      operations.add('GET demo-password-range');
      return http.StreamedResponse(
          Stream.value(utf8.encode('${digest.substring(5)}:8\n')), 200);
    }
    final backend = Uri.parse(backendBaseUrl);
    _require(
        uri.scheme == backend.scheme &&
            uri.host == backend.host &&
            uri.port == backend.port &&
            uri.userInfo.isEmpty &&
            uri.fragment.isEmpty &&
            headers['authorization'] == 'Bearer $_token',
        'Refusing non-demo session or destination');
    _require(
        !uri.path.startsWith('/auth/zk-') &&
            !uri.path.contains('/send') &&
            !uri.path.contains('/purchase') &&
            !uri.path.contains('/account/delete'),
        'Prohibited demo operation');
    operations.add(operation);
    if (request is http.MultipartRequest) {
      _require(operation == 'POST /upload-file' && request.files.length == 1,
          'Non-allowlisted multipart operation');
      _require(
          request.fields['filename_ciphertext']?.isNotEmpty == true &&
              request.fields['content_type_ciphertext']?.isNotEmpty == true,
          'Demo upload metadata must be encrypted by the real client');
      final bytes = await request.files.single.finalize().toBytes();
      _require(utf8.decode(bytes) == _fileText,
          'Only the static demo note is allowed');
      const id = 'demo-note';
      // Fixture storage simulates encrypted-at-rest backend content, not a
      // claim that this compatibility upload API encrypts content on-device.
      encryptedFileBytes[id] = await aesGcmWrap(metadataKey, bytes);
      files.add({
        'id': id,
        'file_id': id,
        'file_name_ciphertext': request.fields['filename_ciphertext'],
        'content_type_ciphertext': request.fields['content_type_ciphertext'],
        'file_size': bytes.length,
        'needs_naming': false,
        'created_at': '2026-10-09T12:00:00Z',
      });
      return _json(
          {'file_id': id, 'auto_named': false, 'message': 'Demo file saved.'});
    }
    _require(request is http.Request, 'Non-allowlisted demo request type');
    final bodyText = (request as http.Request).body;
    final body = bodyText.isEmpty
        ? <String, dynamic>{}
        : Map<String, dynamic>.from(jsonDecode(bodyText) as Map);
    if (uri.path.startsWith('/vault/ciphertext/') ||
        uri.path.startsWith('/concierge/')) {
      _require(
          !bodyText.contains(_username) &&
              !bodyText.contains(_loginTitle) &&
              !bodyText.contains(_fileText) &&
              !bodyText.contains(_memoryTitle),
          'Readable demo data in ciphertext wire');
    }
    switch (operation) {
      case 'POST /vault-stats':
        return _json({
          'login_count': items.length,
          'file_count': files.length,
          'storage_used_bytes':
              files.isEmpty ? 0 : utf8.encode(_fileText).length
        });
      case 'GET /billing/me':
        return _json({
          'included_bytes': kVaultStorageLimitBytes,
          'effective_limit_bytes': 51 * kVaultStorageLimitBytes,
          'purchased_bytes': 50 * kVaultStorageLimitBytes,
          'block_count': 1,
          'status': 'active'
        });
      case 'POST /list-secure-items':
        return _json({'items': []});
      case 'GET /vault/ciphertext/vault-items':
        return _json(items);
      case 'POST /vault/ciphertext/vault-items':
        _require(
            body['service_ciphertext'] is String &&
                body['item_type_ciphertext'] is String &&
                body['payload_ciphertext'] is String,
            'Incomplete demo login envelope');
        final id = (body['item_id'] as num?)?.toInt() ?? ++itemSerial;
        items.removeWhere((row) => row['item_id'] == id);
        items.add(
            {...body, 'item_id': id, 'created_at': '2026-10-09T12:00:00Z'});
        return _json({'item_id': id});
      case 'GET /vault/ciphertext/vault-ai-memory':
        return _json(memories);
      case 'POST /vault/ciphertext/vault-ai-memory':
        _require(
            body['payload_ciphertext'] is String &&
                body['memory_lookup_hash'] is String,
            'Incomplete demo memory envelope');
        memories.removeWhere((row) => row['memory_id'] == body['memory_id']);
        memories.add({...body, 'created_at': '2026-10-09T12:00:00Z'});
        return _json({'status': 'saved'});
      case 'POST /list-files':
        return _json({'files': files});
      case 'GET /folders':
        return _json({'path': '', 'folders': [], 'files': files});
      case 'POST /download-file/manifest':
        return _json({
          'storage_mode': 'inline',
          'content_type': 'text/plain',
          'file_name': _fileName
        });
      case 'POST /download-file':
        final id = body['file_id'] as String;
        final bytes = await aesGcmUnwrap(metadataKey, encryptedFileBytes[id]!);
        return _json({'base64_data': base64Encode(bytes)});
      case 'POST /manage/file/delete':
        final id = body['file_id'];
        _require(id == 'demo-note', 'Refusing non-demo file deletion');
        files.removeWhere((row) => row['file_id'] == id);
        encryptedFileBytes.remove(id);
        return _json({'status': 'deleted'});
      case 'POST /vault/ciphertext/uploaded-files':
        final id = body['file_id'];
        final row = files.singleWhere((row) => row['file_id'] == id);
        row.addAll(body);
        return _json({'status': 'saved'});
      case 'GET /crypto/wallet/asset-catalog':
        return _json(_catalog());
      case 'GET /crypto/wallet/features':
        return _json({
          'walletEngineEnabled': true,
          'defaultNetwork': 'ethereum_mainnet',
          'defaultNetworkConfigValid': true,
          'supportedNetworks': ['ethereum_mainnet'],
          'supportedAssetsByNetwork': {
            'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20']
          },
          'mainnetReceiveEnabled': true,
          'mainnetErc20ReceiveEnabled': true,
          'mainnetSendEnabled': true,
          'mainnetSendPaused': false
        });
      case 'GET /security-center/summary':
        return _json({
          'score': 50,
          'score_band': 'moderate',
          'recommendations': [],
          'inheritance': {}
        });
      case 'POST /expiry/active':
        return _json({'alerts': [], 'counts': {}, 'engine': 'on'});
      case 'GET /concierge/capabilities':
        return _json({
          'enabled': true,
          'provider_mode': 'free',
          'password_breaches': {'status': 'available', 'mode': 'client_range'},
          'email_range': {'status': 'deferred'},
          'email_monitoring': {'status': 'deferred'},
          'stealer_logs': {'status': 'deferred'}
        });
      case 'GET /concierge/state':
        return _json({'revision': revision, 'ciphertext': conciergeCiphertext});
      case 'PUT /concierge/state':
        _require(
            body['expected_revision'] == revision &&
                body['envelope_version'] == 'v1' &&
                body['ciphertext'] is String,
            'Invalid demo Concierge envelope/revision');
        conciergeCiphertext = body['ciphertext'] as String;
        return _json({'revision': ++revision});
      case 'GET /concierge/monitors':
        return _json({'monitors': []});
      case 'POST /beneficiary/list-mine':
        return _json({'beneficiaries': []});
      case 'POST /beneficiary/list-inheritances':
        return _json({'inheritances': []});
      case 'POST /auth/logout':
        return _json({'status': 'signed_out'});
      default:
        if (request.method == 'DELETE' &&
            uri.path.startsWith('/vault/ciphertext/vault-items/')) {
          final id = int.parse(uri.path.split('/').last);
          _require(items.any((row) => row['item_id'] == id),
              'Missing demo login delete target');
          items.removeWhere((row) => row['item_id'] == id);
          return _json({'status': 'deleted'});
        }
        if (request.method == 'DELETE' &&
            uri.path.startsWith('/vault/ciphertext/vault-ai-memory/')) {
          final id = Uri.decodeComponent(uri.path.split('/').last);
          _require(memories.any((row) => row['memory_id'] == id),
              'Missing demo memory delete target');
          memories.removeWhere((row) => row['memory_id'] == id);
          return _json({'status': 'deleted'});
        }
        if (request.method == 'GET' &&
            RegExp(r'^/crypto/wallet/(?:network/(?:ethereum_mainnet|ethereum_sepolia)/)?(?:ETH|USDT_ERC20|USDC_ERC20|PAXG_ERC20|KAG_ERC20)/(?:receive|transactions)$')
                .hasMatch(uri.path)) {
          return _json(uri.path.endsWith('/receive')
              ? {'wallet_engine': 'no_account'}
              : {'status': 'unavailable', 'items': []});
        }
        unexpected.add(operation);
        throw StateError(
            'No fixture for non-allowlisted operation: $operation');
    }
  }

  Map<String, dynamic> _catalog() => {
        'schema': kAssetCatalogSchema,
        'categories': [
          for (final category in VaultAssetCategory.values)
            {
              'id': category.id,
              'available': category == VaultAssetCategory.cryptocurrency ||
                  category == VaultAssetCategory.digitalGold ||
                  category == VaultAssetCategory.digitalSilver
            },
        ],
        'assets': [
          {
            'id': kPaxgAssetId,
            'category': 'digital_gold',
            'symbol': 'PAXG',
            'name': 'PAX Gold',
            'standard': 'ERC20',
            'network': 'ethereum_mainnet',
            'chainId': 1,
            'decimals': 18,
            'contractAddress': kPaxgContractAddress,
            'verified': true,
            'balanceEnabled': true,
            'receiveEnabled': true,
            'sendEnabled': true,
            'activityConnected': true,
            'verificationSource':
                'https://github.com/paxosglobal/paxos-gold-contract'
          },
          {
            'id': kKagAssetId,
            'category': 'digital_silver',
            'symbol': 'KAG',
            'name': 'KMS Labs KAG Silver',
            'standard': 'ERC20',
            'network': 'ethereum_mainnet',
            'chainId': 1,
            'decimals': 18,
            'contractAddress': kKagContractAddress,
            'verified': true,
            'balanceEnabled': true,
            'receiveEnabled': true,
            'sendEnabled': true,
            'activityConnected': true,
            'verificationSource': 'https://kmslabs.money/kms-labs-tcs/'
          },
        ],
      };

  // Clients created by top-level http.get/post can close their scoped wrapper.
  // Its owner closes the fixture only after the full native test ends.
  @override
  void close() {}
  void dispose() => disposed = true;
}

Widget _screen(AppState app, Widget page) =>
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: VaultTheme.dark(),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        routes: {
          '/pin': (_) => const Scaffold(body: Text('Demo vault locked')),
          '/login': (_) => const LoginPage(),
          '/signup': (_) => const SignupPage()
        },
        home: page,
      ),
    );

Future<void> _wait(
    WidgetTester tester, bool Function() ready, String step) async {
  final deadline = DateTime.now().add(const Duration(seconds: 35));
  while (!ready() && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  expect(ready(), true, reason: 'Native demo checkpoint: $step');
  await tester.pump();
}

Future<void> _settle(WidgetTester tester) => tester.pumpAndSettle(
    const Duration(milliseconds: 100),
    EnginePhase.sendSemanticsUpdate,
    const Duration(seconds: 12));

Future<void> _open(WidgetTester tester, String section) async {
  final tile = find.byKey(ValueKey('sidebar_section_$section'));
  if (tile.hitTestable().evaluate().isEmpty) {
    final menu = find.byIcon(Icons.menu_rounded).hitTestable();
    await _wait(tester, () => menu.evaluate().isNotEmpty, 'dashboard menu');
    await tester.tap(menu);
    await _settle(tester);
  }
  await _wait(tester, () => tile.evaluate().isNotEmpty, 'section $section');
  await tester.ensureVisible(tile);
  await _settle(tester);
  await tester.tap(tile.hitTestable());
  await _settle(tester);
}

Future<void> _send(WidgetTester tester, String message,
    {bool doubleTap = false}) async {
  final finder = find.byKey(const Key('chat_composer_field'));
  await _wait(tester, () => finder.evaluate().isNotEmpty, 'chat composer');
  final field = tester.widget<TextField>(finder);
  field.controller!.value = TextEditingValue(
      text: message,
      selection: TextSelection.collapsed(offset: message.length));
  field.onChanged?.call(message);
  await tester.pump();
  final button = find.descendant(
      of: find.byKey(const Key('composer_send_button')),
      matching: find.byType(InkWell));
  await _wait(tester, () => tester.widget<InkWell>(button).onTap != null,
      'send enabled');
  final callback = tester.widget<InkWell>(button).onTap!;
  callback();
  if (doubleTap) callback();
  await _wait(
      tester, () => field.controller!.text.isEmpty, 'message accepted once');
  await _settle(tester);
}

Future<void> _installDemoSession(AppState app, SecretKey mvk) async {
  app
    ..sessionToken = _token
    ..vaultId = _vaultId
    ..vaultName = _vaultName
    ..vaultHandle = _handle
    ..displayName = 'Demo'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingBlockCount = 1
    ..billingPurchasedBytes = 50 * kVaultStorageLimitBytes
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = 51 * kVaultStorageLimitBytes;
  await deriveAndInstallCryptoContext(
      vaultId: _vaultId,
      vaultName: _vaultName,
      pin: _pin,
      pinSaltBase64: base64Encode(List.filled(16, 13)),
      iterations: 1,
      source: 'store-screenshot-demo-only');
  ZkActiveMvk.set(mvk: mvk, vaultId: _vaultId, vaultHandle: _handle);
  setApiClientDeviceId(_device);
  app.unlocked = true;
  app.notifyListeners();
}

void main() {
  _DemoTransport? active;
  http.runWithClient(() {
    final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
    binding.scheduleForcedFrame();
    _register(binding, (fixture) => active = fixture);
  }, () {
    final fixture = active;
    if (fixture == null) throw StateError('Demo transport is not ready');
    return fixture;
  });
}

void _register(IntegrationTestWidgetsFlutterBinding binding,
    void Function(_DemoTransport?) bind) {
  testWidgets('native demo screenshots and encrypted local feature regression',
      (tester) async {
    expect(const bool.fromEnvironment('SVAULTAI_SCREENSHOT_DEMO'), true);
    expect(backendBaseUrl, 'http://127.0.0.1:18082');
    expect(kIsWeb || kReleaseMode, false);
    expect([TargetPlatform.iOS, TargetPlatform.android],
        contains(defaultTargetPlatform));
    final holdMs = const int.fromEnvironment('SVAULTAI_DEMO_CAPTURE_HOLD_MS',
        defaultValue: 2500);
    expect(holdMs >= 0 && holdMs <= 10000, true);
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
        const MethodChannel('com.llfbandit.record/messages'),
        (_) async => null);
    final app = AppState();
    final mvk = SecretKey(List.generate(32, (i) => i + 1));
    final network = _DemoTransport(await VaultKeyHierarchy(mvk).metadataKey());
    bind(network);
    binding.reportData = {
      'scope': 'native-ui-demo-in-process-only',
      'production_requests': 0,
      'account_auth_verified': false,
      'auth_scope':
          'empty local hydration; unsubmitted real auth forms; directly installed synthetic session',
      'wallets': 'absent-no-holdings-or-public-addresses',
      'transfer_or_purchase_verified': false,
      'storefront_prompt_verified': false,
      'release_contract': {
        'api': svaultAiCoreApiContract,
        'zk_v2_read': zkV2CredentialReadEnabled,
        'zk_v2_write': zkV2CredentialWriteEnabled,
        'memory_v2_read': memoryV2ReadEnabled,
        'memory_v2_write': memoryV2WriteEnabled,
        'file_v2_read': fileV2ReadEnabled,
        'file_v2_write': fileV2WriteEnabled,
        'private_vault_local_routing': privateVaultLocalRoutingEnabled,
      },
      'file_memory_protocol_scope':
          'pinned production defines; actual current client ciphertext memory and compatibility multipart file APIs; no unused V2 protocol simulated',
      'password_provider_scope':
          'in-process synthetic HIBP suffix count8; no external provider query; findings screenshot excluded from store selections',
      'file_content_encryption_scope':
          'fixture-simulated backend at-rest encryption; real client metadata AES; compatibility upload API, not production E2E proof',
      'inheritance_scope':
          'empty fixture; real configuration UI and cancelled beneficiary draft; no scheduling or recovery verification',
      'checkpoints': <String>[]
    };
    Future<void> shot(String name) async {
      FocusManager.instance.primaryFocus?.unfocus();
      // The real text preview can schedule recurring selection/caret frames.
      // Readiness is asserted by each checkpoint; capture a rendered frame
      // without waiting for all recurring native animations to stop forever.
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.takeException(), isNull,
          reason: 'Native rendering at $name');
      (binding.reportData!['checkpoints'] as List<String>).add(name);
      debugPrint('SVAULTAI_DEMO_SCREENSHOT_READY:$name');
      if (holdMs > 0) {
        await tester.runAsync(
            () => Future<void>.delayed(Duration(milliseconds: holdMs)));
      }
    }

    try {
      expect(zkV2CredentialReadEnabled, true);
      expect(zkV2CredentialWriteEnabled, false);
      expect(memoryV2ReadEnabled && memoryV2WriteEnabled, true);
      expect(fileV2ReadEnabled && fileV2WriteEnabled, true);
      expect(privateVaultLocalRoutingEnabled, false);
      // Complete only local empty-preference hydration. No token exists,
      // so this does not call /auth/me or perform any account authentication.
      await app.hydrate();
      expect(app.hydrated, true);
      expect(app.sessionToken, isNull);
      // These are real auth forms. No submit occurs and no account is created.
      await tester.pumpWidget(_screen(app, const SignupPage()));
      await _settle(tester);
      await tester.enterText(
          find.byKey(const Key('signup_vault_name_field')), _vaultName);
      await tester.enterText(
          find.byKey(const Key('signup_display_name_field')), 'Demo');
      await tester.enterText(find.byKey(const Key('signup_pin_field')), _pin);
      await tester.enterText(
          find.byKey(const Key('signup_confirm_pin_field')), _pin);
      await tester.tap(find.byKey(const Key('signup_risk_checkbox')));
      await shot('01-create-vault-demo-form-not-submitted');
      await tester.pumpWidget(const SizedBox.shrink());
      await _settle(tester);
      await _installDemoSession(app, mvk);
      final store = AssetLiveStore.instance..clear();
      for (final asset in kCryptoWalletEngineAssets) {
        store.applyState(
            source: 'native-demo',
            asset: asset,
            seq: store.claimSeq(asset),
            state: const DashboardAssetLiveState.noWallet());
      }
      await tester.pumpWidget(_screen(app, const ChatDashboardPage()));
      await _settle(tester);
      final viewport =
          MediaQuery.sizeOf(tester.element(find.byType(ChatDashboardPage)));
      binding.reportData!['viewport'] = {
        'width': viewport.width,
        'height': viewport.height,
        'platform': defaultTargetPlatform.name,
        'tablet': viewport.shortestSide >= 600
      };

      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await _settle(tester);
      // The genuine 1080x1920 Android viewport is only 411x731 logical
      // pixels. All choices and Cancel must remain reachable within the
      // bottom sheet's bounded height rather than overflow its Column.
      for (final key in const [
        'create_choice_login',
        'create_choice_file',
        'create_choice_memory',
        'create_menu_cancel',
      ]) {
        final choice = find.byKey(Key(key));
        await tester.ensureVisible(choice);
        await _settle(tester);
        expect(choice.hitTestable(), findsOneWidget,
            reason: 'Responsive Create menu action: $key');
        expect(tester.takeException(), isNull,
            reason: 'Responsive Create menu rendering: $key');
      }
      await tester.tap(find.byKey(const Key('create_menu_cancel')));
      await _settle(tester);
      expect(find.byKey(const Key('vault_create_menu')), findsNothing);
      binding.reportData!['responsive_create_menu_verified'] = true;
      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await _settle(tester);
      await shot('02-create-menu-digital-vault');
      await tester.tap(find.byKey(const Key('create_choice_login')));
      await _settle(tester);
      await tester.enterText(
          find.byKey(const Key('secure_item_edit_title')), _loginTitle);
      await tester.enterText(
          find.byKey(const Key('secure_item_edit_username')), _username);
      await tester.enterText(
          find.byKey(const Key('secure_item_edit_password')), _password);
      await shot('03-create-login-demo');
      final save = find.byKey(const Key('secure_item_edit_save'));
      await tester.tap(save);
      await _wait(
          tester,
          () =>
              network.items.length == 1 &&
              find.byKey(const Key('logins_page')).evaluate().isNotEmpty,
          'login saved');
      expect(network.count('POST /vault/ciphertext/vault-items'), 1);
      await _wait(tester, () => find.text(_loginTitle).evaluate().isNotEmpty,
          'login dashboard item');
      await shot('04-login-saved-dashboard');

      await _open(tester, 'chat');
      await _send(tester, 'Save my favorite color as teal', doubleTap: true);
      await _wait(
          tester,
          () =>
              network.memories.length == 1 &&
              find
                  .textContaining('Memory saved securely.')
                  .evaluate()
                  .isNotEmpty,
          'chat memory save');
      expect(network.count('POST /vault/ciphertext/vault-ai-memory'), 1,
          reason: 'A double Send callback must not duplicate the save');
      await shot('05-chat-save-memory-once');
      await _open(tester, 'memory');
      await _wait(tester, () => find.text(_memoryTitle).evaluate().isNotEmpty,
          'memory timeline');
      await shot('06-memory-timeline');

      // Upload uses the actual API metadata encryption. Synthetic storage
      // encrypts the harmless note, then actual file UI retrieves its metadata.
      final api = VaultAIClient(baseUrl: backendBaseUrl);
      await api.uploadVaultFile(
          vaultName: _vaultName,
          pin: _pin,
          authToken: _token,
          filename: _fileName,
          contentType: 'text/plain',
          fileBytes: Uint8List.fromList(utf8.encode(_fileText)));
      expect(
          utf8.decode(network.encryptedFileBytes['demo-note']!,
              allowMalformed: true),
          isNot(contains(_fileText)));
      await _open(tester, 'files');
      final refresh = find.byKey(const Key('files_empty_refresh_button'));
      if (find.text(_fileName).evaluate().isEmpty &&
          refresh.evaluate().isNotEmpty) {
        await tester.tap(refresh);
      }
      await _wait(tester, () => find.text(_fileName).evaluate().isNotEmpty,
          'file dashboard');
      await shot('07-encrypted-demo-file-dashboard');
      await _open(tester, 'chat');
      await _send(tester, 'Show my file $_fileName');
      final view = find.byKey(const Key('vault_file_card_view_btn'));
      await _wait(tester, () => view.evaluate().isNotEmpty, 'file chat card');
      await tester.ensureVisible(view);
      await _settle(tester);
      expect(tester.widget<FilledButton>(view).onPressed, isNotNull);
      final card = tester.widget<VaultFileCard>(find.byType(VaultFileCard));
      expect(card.msg.fileId, 'demo-note');
      expect(card.msg.fileName, _fileName);
      final contextSnapshot = VaultCryptoRegistry.current;
      binding.reportData!['file_view_preconditions'] = {
        'callback_present': tester
                .widget<ChatMessageList>(find.byType(ChatMessageList))
                .onOpenVaultFile !=
            null,
        'token_matches_demo': app.sessionToken == _token,
        'vault_id_matches_demo': app.vaultId == _vaultId,
        'vault_name_matches_demo': app.vaultName == _vaultName,
        'view_in_flight_before_tap': app.isFileViewInFlight('demo-note'),
        'pin_context_matches_demo': contextSnapshot?.pin == _pin,
        'context_vault_matches_demo': contextSnapshot?.vaultId == _vaultId,
      };
      await tester.tap(view);
      binding.reportData!['file_view_dispatch'] = 'real-widget-tap';
      await _wait(
          tester,
          () => find
              .byWidgetPredicate((widget) =>
                  widget is SelectableText && widget.data == _fileText)
              .evaluate()
              .isNotEmpty,
          'file view contents');
      await shot('08-retrieve-demo-file');
      await tester.tap(find.byKey(const Key('text_viewer_dialog_close')));
      await _settle(tester);

      await _open(tester, 'cryptoVault');
      await _wait(
          tester,
          () => find.textContaining('PAX Gold · PAXG').evaluate().isNotEmpty,
          'verified demo catalog');
      expect(VaultAssetCategory.values, hasLength(10));
      await shot('09-assets-supported-categories');
      final scrollable = find.descendant(
          of: find.byType(AssetsPage), matching: find.byType(Scrollable));
      for (final category in VaultAssetCategory.values) {
        final tile = find.byKey(Key('assets_category_${category.id}'));
        await tester.scrollUntilVisible(tile, 200, scrollable: scrollable);
        expect(find.descendant(of: tile, matching: find.text(category.label)),
            findsOneWidget);
        if (![
          VaultAssetCategory.cryptocurrency,
          VaultAssetCategory.digitalGold,
          VaultAssetCategory.digitalSilver
        ].contains(category)) {
          expect(find.descendant(of: tile, matching: find.text('Coming soon')),
              findsOneWidget);
        }
      }
      await shot('10-assets-coming-soon-categories');
      Future<void> openAsset(VaultAssetCategory category) async {
        final tile = find.byKey(Key('assets_category_${category.id}'));
        // The catalog is lazily built. Scroll back toward the supported
        // categories before asking for an element that may be off-screen.
        await tester.scrollUntilVisible(tile, -200, scrollable: scrollable);
        await tester.ensureVisible(tile);
        await Scrollable.ensureVisible(tester.element(tile), alignment: 0.5);
        await _settle(tester);
        await tester.tap(tile.hitTestable());
        await _settle(tester);
      }

      await openAsset(VaultAssetCategory.digitalGold);
      await _wait(
          tester,
          () => find
              .byKey(const Key(
                  'crypto_wallet_engine_asset_detail_address_no_wallet'))
              .evaluate()
              .isNotEmpty,
          'gold no-wallet detail');
      expect(find.byType(CryptoWalletEngineAssetDetailPage), findsOneWidget);
      await shot('11-digital-gold-no-invented-holdings');
      await tester.tap(find.byTooltip('Back').last);
      await _settle(tester);
      await openAsset(VaultAssetCategory.digitalSilver);
      await _wait(
          tester,
          () => find
              .byKey(const Key(
                  'crypto_wallet_engine_asset_detail_address_no_wallet'))
              .evaluate()
              .isNotEmpty,
          'silver no-wallet detail');
      await shot('12-digital-silver-issuer-terms');
      await tester.tap(find.byTooltip('Back').last);
      await _settle(tester);
      await openAsset(VaultAssetCategory.cryptocurrency);
      await _wait(
          tester,
          () => find
              .byKey(const Key('assets_cryptocurrency_route'))
              .evaluate()
              .isNotEmpty,
          'cryptocurrency route');
      expect(find.byType(CryptoWalletEnginePage), findsOneWidget);
      await shot('13-cryptocurrency-no-wallet-demo');
      await tester.tap(find.byKey(const Key('assets_cryptocurrency_back')));
      await _settle(tester);

      await _open(tester, 'concierge');
      await _wait(
          tester,
          () => find
              .textContaining('Free checks for exposed, weak and reused')
              .evaluate()
              .isNotEmpty,
          'free Concierge');
      expect(find.text('Email status:'), findsNothing);
      await shot('14-concierge-free-password-checks');
      await tester.ensureVisible(find.text('Manage checks'));
      await _settle(tester);
      await tester.tap(find.text('Manage checks'));
      await _settle(tester);
      expect(find.text('Email exposure checks'), findsNothing);
      await shot('15-concierge-password-only-opt-in');
      await tester.tap(find.text('Allow password exposure checks'));
      await tester.ensureVisible(find.text('Save choices'));
      await _settle(tester);
      await tester.tap(find.text('Save choices'));
      await _wait(
          tester,
          () =>
              network.conciergeCiphertext != null &&
              find.text('Save choices').evaluate().isEmpty,
          'encrypted consent');
      await tester.ensureVisible(find.text('Check now'));
      await _settle(tester);
      await tester.tap(find.text('Check now'));
      await _wait(
          tester,
          () =>
              find.textContaining('appears 8 times').evaluate().isNotEmpty &&
              network.revision >= 2,
          'demo exposure findings');
      expect(network.count('GET demo-password-range'), 1);
      await tester.ensureVisible(find.textContaining('appears 8 times'));
      await shot('16-concierge-demo-findings');

      await _open(tester, 'inheritance');
      await _wait(
          tester,
          () => find
              .byKey(const Key('inheritance_add_beneficiary_button'))
              .evaluate()
              .isNotEmpty,
          'inheritance configuration');
      await shot('17-inheritance-configuration');
      final add = find.byKey(const Key('inheritance_add_beneficiary_button'));
      await tester.ensureVisible(add);
      await _settle(tester);
      await tester.tap(add);
      await _settle(tester);
      await tester.enterText(
          find.byType(TextFormField), 'Demo trusted contact');
      await shot('18-inheritance-beneficiary-demo-form-not-submitted');
      await tester.tap(find.text('Cancel').last);
      await _settle(tester);

      await tester.pumpWidget(const SizedBox.shrink());
      await _settle(tester);
      await app.signOut();
      expect(app.sessionToken, isNull);
      expect(app.unlocked, false);
      expect(ZkActiveMvk.current(), isNull);
      expect(VaultCryptoRegistry.current, isNull);
      await tester.pumpWidget(_screen(app, const LoginPage()));
      await _settle(tester);
      // LoginPage itself reveals its form after the hydrated route guard.
      // Do not tap the global primary action: on tablet it is Sign up.
      await _wait(
          tester,
          () => find
              .byKey(const Key('auth_vault_name_field'))
              .evaluate()
              .isNotEmpty,
          'signed-out login form');
      await tester.enterText(
          find.byKey(const Key('auth_vault_name_field')), _vaultName);
      await shot('19-local-sign-out-auth-form-not-submitted');
      await tester.pumpWidget(const SizedBox.shrink());
      await _settle(tester);
      await _installDemoSession(app, mvk);
      await tester.pumpWidget(_screen(app, const ChatDashboardPage()));
      await _settle(tester);
      await _open(tester, 'logins');
      await _wait(tester, () => find.text(_loginTitle).evaluate().isNotEmpty,
          'login decrypt after synthetic session restore');
      await shot('20-login-restored-after-demo-session');
      await _open(tester, 'memory');
      await _wait(tester, () => find.text(_memoryTitle).evaluate().isNotEmpty,
          'memory decrypt after synthetic session restore');
      await shot('21-memory-restored-after-demo-session');
      await _open(tester, 'files');
      await _wait(tester, () => find.text(_fileName).evaluate().isNotEmpty,
          'file metadata decrypt after synthetic session restore');
      await _open(tester, 'concierge');
      await _wait(
          tester,
          () => find.textContaining('appears 8 times').evaluate().isNotEmpty,
          'Concierge encrypted findings restored');
      expect(network.count('GET demo-password-range'), 1);

      await _open(tester, 'chat');
      await _send(tester, 'Show my $_loginTitle login', doubleTap: true);
      await _wait(tester, () => find.text(_username).evaluate().isNotEmpty,
          'decrypted login card');
      expect(find.text('Show my $_loginTitle login'), findsOneWidget);
      await shot('22-retrieve-login-once');
      await _send(tester, 'Show my favorite color memory');
      await _wait(
          tester,
          () => find.textContaining('I remember').evaluate().isNotEmpty,
          'memory retrieve');
      await shot('23-retrieve-memory-chat');
      for (final (kind, label) in [
        ('memory', 'favorite color'),
        ('login', _loginTitle),
        ('file', _fileName)
      ]) {
        await _send(tester, 'Delete my $label $kind');
        await _wait(
            tester,
            () => find.textContaining('Reply yes or no.').evaluate().isNotEmpty,
            'delete $kind confirmation');
        await shot('24-delete-$kind-confirmation');
        await _send(tester, 'yes', doubleTap: true);
        await _wait(
            tester,
            () => switch (kind) {
                  'memory' => network.memories.isEmpty,
                  'login' => network.items.isEmpty,
                  _ => network.files.isEmpty,
                },
            'current $kind fixture deletion');
        await _wait(
            tester,
            () => find.textContaining('Deleted "').evaluate().isNotEmpty,
            'delete $kind completed');
      }
      expect(network.items, isEmpty);
      expect(network.memories, isEmpty);
      expect(network.files, isEmpty);
      expect(network.encryptedFileBytes, isEmpty);
      expect(network.count('POST /manage/file/delete'), 1);
      expect(
          network.operations.where(
              (op) => op.startsWith('DELETE /vault/ciphertext/vault-items/')),
          hasLength(1));
      expect(
          network.operations.where((op) =>
              op.startsWith('DELETE /vault/ciphertext/vault-ai-memory/')),
          hasLength(1));
      await shot('25-demo-deletions-completed');
      expect(network.unexpected, isEmpty);
      expect(
          network.operations.any((op) =>
              op.startsWith('POST /chat') ||
              op.contains('/send') ||
              op.startsWith('POST /auth/zk-')),
          false);
      binding.reportData!['operations'] = network.operations;
      binding.reportData![
              'client_encrypted_login_memory_file_metadata_workflows_verified'] =
          true;
      expect(tester.takeException(), isNull);
    } catch (_) {
      binding.reportData!['operations'] = network.operations;
      binding.reportData!['unexpected_operations'] = network.unexpected;
      debugPrint('SVAULTAI_DEMO_SCREENSHOT_READY:diagnostic-failed-journey');
      if (holdMs > 0) {
        await tester.runAsync(
            () => Future<void>.delayed(Duration(milliseconds: holdMs)));
      }
      rethrow;
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await _settle(tester);
      await app.clearSession(keepLastVaultName: false);
      app.dispose();
      network.dispose();
      bind(null);
      AssetLiveStore.instance.clear();
      ZkActiveMvk.clear();
      VaultCryptoRegistry.clear(reason: 'store-screenshot-demo-cleanup');
      setApiClientDeviceId('');
      NativeSecureStore.useSharedPreferencesForTesting = false;
      messenger.setMockMethodCallHandler(
          const MethodChannel('com.llfbandit.record/messages'), null);
    }
  }, timeout: const Timeout(Duration(minutes: 14)));
}
