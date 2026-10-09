import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:integration_test/integration_test.dart';
import 'package:pointycastle/api.dart' show PublicKeyParameter;
import 'package:pointycastle/digests/keccak.dart';
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/ecc/curves/secp256k1.dart';
import 'package:pointycastle/signers/ecdsa_signer.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/device_id.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/ethereum_transaction.dart';
import 'package:vault_ai_frontend/services/local_outgoing_tx_store.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

// NON-PRODUCTION NATIVE TRANSACTION FIXTURE ONLY.
// Default: no socket client, account, keychain write, provider, RPC, explorer or
// financial transaction. Every HTTP operation is an in-process strict fixture,
// including engine-frame callbacks. Never run app.main()/Brain.
// Optional SVAULTAI_PAXG_REAL_STORE_FIXTURE enables ONLY a closed loopback QA
// health/envelope/draft/key/broadcast bridge below, with external RPC disabled.
// Public Ethereum test key 1 is deliberately compromised, never a funded key,
// and exists only in memory. Signed raw bytes are captured only in memory.
// This proves native client signing/UI boundaries, NOT backend control-store
// hydration, an actual mainnet transfer, token delivery or issuer availability.
const _base = 'http://paxg-native-fixture.invalid';
const _network = 'ethereum_mainnet';
const _token = 'paxg-native-fixture-session';
const _device = 'paxg-native-fixture-device';
const _publicTestKey =
    '0000000000000000000000000000000000000000000000000000000000000001';
const _sender = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const _recipient = '0x2222222222222222222222222222222222222222';
const _amount = '1.000000000000000001';
const _pin = '918273';
const _draftId = 'paxg-native-public-fixture-draft';
const _idempotency = 'paxg-native-public-fixture-attempt';
const _root = '/crypto/wallet/network/$_network';
const _paxg = '$_root/$kPaxgAssetId';
const _realStoreEnabled =
    bool.fromEnvironment('SVAULTAI_PAXG_REAL_STORE_FIXTURE');
const _screenshotHolds =
    bool.fromEnvironment('SVAULTAI_PAXG_QA_SCREENSHOT_HOLDS');

void _require(bool condition, String safeReason) {
  // HTTP callbacks may run outside the currently active tester.pump guard.
  // Never call guarded expect() here or include wire/key values in exceptions.
  if (!condition) throw StateError(safeReason);
}

/// Test-only bridge to the dedicated PostgreSQL/draft-verification fixture.
/// This is not an app transport adapter or a development-auth switch. Exact
/// loopback identity is checked before any ciphertext or signed bytes are sent.
class _RealStoreBridge {
  final HttpClient _client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 5)
    ..findProxy = ((_) => 'DIRECT');
  final List<String> operations = [];
  bool _verified = false;

  static const _allowed = {
    'GET /__qa/health',
    'POST /__qa/wallet-envelope',
    'POST $_paxg/send/draft',
    'GET $_paxg/encrypted-secret',
    'POST $_paxg/send/broadcast',
  };

  Future<http.Response> _request(String method, String path,
      {String? body}) async {
    _require(_realStoreEnabled && _allowed.contains('$method $path'),
        'Loopback bridge route not permitted');
    _require(_verified || '$method $path' == 'GET /__qa/health',
        'Loopback QA identity not verified');
    final uri = Uri(scheme: 'http', host: '127.0.0.1', port: 18082, path: path);
    _require(
        uri.host == '127.0.0.1' &&
            uri.port == 18082 &&
            uri.scheme == 'http' &&
            uri.query.isEmpty &&
            uri.userInfo.isEmpty,
        'Loopback QA destination changed');
    operations.add('$method $path');
    final request =
        await _client.openUrl(method, uri).timeout(const Duration(seconds: 5));
    request.followRedirects = false;
    request.maxRedirects = 0;
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    if (path != '/__qa/health') {
      request.headers.set(
          HttpHeaders.authorizationHeader, 'Bearer native-paxg-fixture-only');
      request.headers.set('X-Device-ID', 'native-paxg-fixture-device');
    }
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.add(utf8.encode(body));
    }
    final response = await request.close().timeout(const Duration(seconds: 10));
    _require(
        response.statusCode == 200 &&
            response.headers.contentType?.mimeType == 'application/json',
        'Loopback QA response unavailable; no fallback permitted');
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 10))) {
      bytes.addAll(chunk);
      _require(bytes.length <= 65536, 'Loopback QA response too large');
    }
    final content = utf8.decode(bytes);
    _require(jsonDecode(content) is Map<String, dynamic>,
        'Loopback QA response must be an object');
    return http.Response(content, 200,
        headers: {'content-type': 'application/json'});
  }

  Future<void> prepare(String encryptedKey) async {
    final health = jsonDecode((await _request('GET', '/__qa/health')).body)
        as Map<String, dynamic>;
    _require(
        health['isolated_qa'] == true &&
            health['native_fixture'] == true &&
            health['fixture'] == 'paxg-encrypted-draft-v1' &&
            health['database'] == 'svaultai_paxg_transaction_qa' &&
            health['network'] == _network &&
            health['chain_id'] == 1 &&
            health['external_rpc_disabled'] == true &&
            health['sender'] == _sender.toLowerCase(),
        'Wrong loopback QA process; refusing any writes');
    _verified = true;
    await _request('POST', '/__qa/wallet-envelope',
        body: jsonEncode({'encryptedWalletSecret': encryptedKey}));
  }

  Future<http.Response> forward(http.Request request) =>
      _request(request.method, request.url.path,
          body: request.method == 'POST' ? request.body : null);

  void close() => _client.close(force: true);
}

Map<String, dynamic> _catalog({String asset = kPaxgAssetId}) => {
      'schema': kAssetCatalogSchema,
      'categories': [
        {
          'id': asset == kKagAssetId ? 'digital_silver' : 'digital_gold',
          'available': true
        }
      ],
      'assets': [
        {
          'id': asset,
          'category': asset == kKagAssetId ? 'digital_silver' : 'digital_gold',
          'symbol': walletAssetSymbol(asset),
          'name': asset == kKagAssetId ? 'KMS Labs KAG Silver' : 'PAX Gold',
          'standard': 'ERC20',
          'network': _network,
          'chainId': 1,
          'contractAddress':
              asset == kKagAssetId ? kKagContractAddress : kPaxgContractAddress,
          'decimals': 18,
          'verified': true,
          'balanceEnabled': true,
          'receiveEnabled': true,
          'sendEnabled': true,
          'activityConnected': true,
          'transferNote':
              asset == kKagAssetId ? kKagTransferNote : kPaxgTransferNote,
        }
      ],
    };

String _transferData(String amount) => '0xa9059cbb'
    '${_recipient.substring(2).padLeft(64, '0')}'
    '${parseAssetBaseUnits(amount, 18).toRadixString(16).padLeft(64, '0')}';

class _TransactionFixture {
  _TransactionFixture._(this.metadataKey, this.encryptedKey, this.asset);
  final String asset;
  String get symbol => walletAssetSymbol(asset);
  String get contract =>
      asset == kKagAssetId ? kKagContractAddress : kPaxgContractAddress;
  String get assetPath => '$_root/$asset';
  final SecretKey metadataKey;
  final String encryptedKey;
  final LocalOutgoingTxStore outgoing = LocalOutgoingTxStore();
  final List<String> operations = [];
  final List<Map<String, dynamic>> broadcasts = [];
  final List<String> guardFailures = [];
  _RealStoreBridge? realStore;
  String draftId = _draftId;
  String idempotencyKey = _idempotency;
  bool unlocked = true;
  bool wrongContract = false;
  bool historyUnavailable = false;
  bool historyThrows = false;
  bool receiptThrows = false;
  String receiptStatus = 'pending';
  String broadcastStatus = 'submitted';
  bool malformedBroadcast = false;
  bool broadcastThrows = false;
  BigInt tokenBalance = BigInt.parse('3000000000000000003');
  BigInt ethBalance = BigInt.parse('1000000000000000000');
  BigInt refreshGasLimit = BigInt.from(60000);
  Completer<http.Response>? secretResponse;
  Completer<void>? decryptGate;
  Completer<http.Response>? broadcastResponse;
  int decryptCalls = 0;
  int exactTokenReads = 0;
  Map<String, dynamic>? encryptedDraft;
  Map<String, dynamic>? encryptedHistory;

  static Future<_TransactionFixture> create(
      {String asset = kPaxgAssetId}) async {
    _require(asset == kPaxgAssetId || asset == kKagAssetId,
        'Only pinned public token fixtures are permitted');
    final mvk = SecretKey(List<int>.generate(32, (i) => i + 1));
    ZkActiveMvk.set(
        mvk: mvk,
        vaultId: 'paxg-native-fixture-vault',
        vaultHandle: 'paxg-native-fixture-handle');
    final metadata = await VaultKeyHierarchy(mvk).metadataKey();
    final secret = await aesGcmWrap(
        metadata, Uint8List.fromList(utf8.encode(_publicTestKey)));
    return _TransactionFixture._(metadata, b64urlEncode(secret), asset);
  }

  late final VaultAIClient api =
      VaultAIClient(baseUrl: _base, walletResponseIsCurrent: () => unlocked);

  int count(String method, String path) =>
      operations.where((op) => op == '$method $path').length;

  http.Response json(Object? value, {int status = 200}) =>
      http.Response(jsonEncode(value), status,
          headers: {'content-type': 'application/json'});

  Future<Map<String, dynamic>> balance(String asset) =>
      api.getCryptoWalletBalanceNetwork(
          network: _network, asset: asset, authToken: _token, address: _sender);

  Future<double?> coarseTokenBalance() async =>
      double.parse('${(await balance(asset))['availableAmount']}');

  Future<double?> coarseEthBalance() async =>
      double.parse('${(await balance('ETH'))['availableAmount']}');

  Future<BigInt?> exactTokenBalance() async {
    exactTokenReads++;
    return BigInt.parse('${(await balance(asset))['baseUnits']}');
  }

  Future<BigInt?> exactEthBalance() async =>
      BigInt.parse('${(await balance('ETH'))['weiAmount']}');

  Future<String> decrypt(String cipher) async {
    decryptCalls++;
    _require(cipher == encryptedKey, 'Unexpected synthetic encrypted key');
    if (decryptGate != null) await decryptGate!.future;
    return utf8.decode(await aesGcmUnwrap(metadataKey, b64urlDecode(cipher)));
  }

  Map<String, dynamic> draft(String amount) => {
        'status': 'draft_ready',
        'draftId': _draftId,
        'asset': asset,
        'network': 'Ethereum Mainnet',
        'fromAddress': _sender,
        'destinationAddress': _recipient,
        'transactionTo': wrongContract ? _recipient : contract,
        'chainId': 1,
        'unit': symbol,
        'amount': amount,
        'amountBaseUnits': '${parseAssetBaseUnits(amount, 18)}',
        'decimals': 18,
        'transactionValueWei': '0',
        'dataHex': _transferData(amount),
        'nonce': '7',
        'gasLimit': '60000',
        'gasPrice': '1000000000',
        'confirmedBalanceWei': '$ethBalance',
        'spendableBalanceWei': '$ethBalance',
        'totalMaximumDebitWei': '60000000000000',
        'remainingBalanceWei': '${ethBalance - BigInt.from(60000000000000)}',
      };

  Future<http.Response> respond(http.Request request) async {
    try {
      final uri = request.url;
      final headers = {
        for (final entry in request.headers.entries)
          entry.key.toLowerCase(): entry.value
      };
      _require(
          uri.scheme == 'http' &&
              uri.host == 'paxg-native-fixture.invalid' &&
              uri.port == 80 &&
              uri.userInfo.isEmpty &&
              uri.fragment.isEmpty,
          'Refusing a non-fixture transaction destination');
      _require(headers['authorization'] == 'Bearer $_token',
          'Unexpected synthetic transaction session');
      _require(headers['x-device-id'] == _device,
          'Unexpected synthetic transaction device');
      _require(
          !request.body.contains(_publicTestKey) &&
              !request.body.contains(_pin),
          'Plaintext signing secret on fixture wire');
      final op = '${request.method} ${uri.path}';
      operations.add(op);
      _require(asset == kPaxgAssetId || !uri.path.startsWith('$_paxg/'),
          'A silver fixture cannot use a gold wallet endpoint');
      final dispatchOp = op.replaceFirst(assetPath, _paxg);
      switch (dispatchOp) {
        case 'GET /crypto/wallet/asset-catalog':
          return json(_catalog(asset: asset));
        case 'GET $_paxg/receive':
          return json({
            'wallet_engine': 'receive_ready',
            'publicAddress': _sender,
            'network': 'Ethereum Mainnet'
          });
        case 'GET $_paxg/balance':
        case 'GET $_root/ETH/balance':
          _require(uri.queryParameters['address'] == _sender,
              'Unexpected synthetic balance address');
          final isToken = uri.path == '$assetPath/balance';
          final base = isToken ? tokenBalance : ethBalance;
          return json({
            'asset': isToken ? asset : 'ETH',
            'networkId': _network,
            'chainId': 1,
            'decimals': 18,
            'tokenContract': isToken ? contract : null,
            'publicAddress': _sender,
            'balanceStatus': 'available',
            'availableAmount': _decimal(base),
            'unit': isToken ? symbol : 'ETH',
            'baseUnits': '$base',
            'weiAmount': '$base',
          });
        case 'POST $_paxg/send/draft':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          _require(
              body['fromAddress'] == _sender &&
                  body['destinationAddress'] == _recipient,
              'Unexpected synthetic transfer destination');
          final amount = body['amountEth'] as String;
          _require(
              body['draftPayloadCiphertext'] is String &&
                  body['senderAddressLookupHash'] is String,
              'Adopted native test must use encrypted draft metadata');
          final plain = await aesGcmUnwrap(metadataKey,
              b64urlDecode(body['draftPayloadCiphertext'] as String));
          encryptedDraft =
              Map<String, dynamic>.from(jsonDecode(utf8.decode(plain)) as Map);
          _require(
              encryptedDraft!['fromAddress'] == _sender &&
                  encryptedDraft!['destinationAddress'] == _recipient &&
                  encryptedDraft!['asset'] == asset &&
                  encryptedDraft!['amountEth'] == amount,
              'Encrypted synthetic draft does not match the reviewed transfer');
          if (realStore != null) {
            final response = await realStore!.forward(request);
            final issued = jsonDecode(response.body) as Map<String, dynamic>;
            _require(
                issued['status'] == 'draft_ready' &&
                    issued['draftId'] is String &&
                    (issued['draftId'] as String).isNotEmpty,
                'Real QA backend did not issue a draft; no fixture fallback');
            draftId = issued['draftId'] as String;
            return response;
          }
          return json(draft(amount));
        case 'POST $_root/send/fee_estimate':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          _require(
              body['asset'] == asset &&
                  body['fromAddress'] == _sender &&
                  body['destinationAddress'] == _recipient &&
                  body['amountEth'] == _amount,
              'Unexpected synthetic gas quote request');
          return json({
            'status': 'fee_estimate_ready',
            'asset': asset,
            'network': 'ethereum_mainnet',
            'chainId': 1,
            'amountBaseUnits': '${parseAssetBaseUnits(_amount, 18)}',
            'gasLimit': '$refreshGasLimit',
            'gasPriceWei': '1000000000',
            'authorizedMaxFeeBaseUnits':
                '${refreshGasLimit * BigInt.from(1000000000)}',
            'feeSource': 'in-process-fixture-not-rpc',
          });
        case 'GET $_paxg/encrypted-secret':
          if (realStore != null) {
            final response = await realStore!.forward(request);
            final key = jsonDecode(response.body) as Map<String, dynamic>;
            _require(key['encryptedWalletSecret'] == encryptedKey,
                'Real QA encrypted key envelope changed');
            return response;
          }
          if (secretResponse != null) return secretResponse!.future;
          return json({
            'status': 'encrypted_secret_ready',
            'encryptedWalletSecret': encryptedKey
          });
        case 'POST $_paxg/send/broadcast':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          _require(
              setEquals(body.keys.toSet(),
                  {'signedTransaction', 'idempotencyKey', 'draftId'}),
              'Unexpected synthetic broadcast fields');
          _require(
              body['idempotencyKey'] == idempotencyKey &&
                  body['draftId'] == draftId,
              'Synthetic broadcast attempt identity changed');
          _require(body['signedTransaction'] is String,
              'Missing synthetic signed bytes');
          broadcasts.add(Map<String, dynamic>.from(body));
          if (realStore != null) return realStore!.forward(request);
          if (broadcastResponse != null) return broadcastResponse!.future;
          if (broadcastThrows) {
            throw StateError('Synthetic broadcast transport unavailable');
          }
          if (malformedBroadcast) return json({'unexpected': true});
          return json({
            'status': broadcastStatus,
            'txHash':
                computeLocalEthTxHash(body['signedTransaction'] as String),
            if (broadcastStatus != 'submitted')
              'reason': 'synthetic_fixture_outcome',
          });
        case 'POST /vault/ciphertext/crypto-history':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          _require(
              setEquals(body.keys.toSet(), {
                'network',
                'signature_lookup_hash',
                'outcome_payload_ciphertext'
              }),
              'Outgoing history must be opaque on fixture wire');
          final plain = await aesGcmUnwrap(metadataKey,
              b64urlDecode(body['outcome_payload_ciphertext'] as String));
          encryptedHistory =
              Map<String, dynamic>.from(jsonDecode(utf8.decode(plain)) as Map);
          return json({'created': true});
        case 'GET $_paxg/transactions':
          if (historyThrows) {
            throw StateError('Synthetic activity transport unavailable');
          }
          return json({
            'transactionsStatus':
                historyUnavailable ? 'unavailable' : 'available',
            'reason': historyUnavailable ? 'upstream_error' : null,
            'transactions': []
          });
        default:
          if (request.method == 'GET' &&
              broadcasts.isNotEmpty &&
              uri.path ==
                  '$assetPath/transaction/${computeLocalEthTxHash(broadcasts.single['signedTransaction'] as String)}') {
            if (receiptThrows) {
              throw StateError('Synthetic receipt transport unavailable');
            }
            return json({'status': receiptStatus});
          }
          throw StateError(
              'Refusing non-allowlisted synthetic transaction operation');
      }
    } catch (error) {
      // Static error kind only; no request values, raw transaction, PIN or key.
      guardFailures.add(error.runtimeType.toString());
      rethrow;
    }
  }
}

String _decimal(BigInt base) {
  final scale = BigInt.from(10).pow(18);
  return '${base ~/ scale}.${(base % scale).toString().padLeft(18, '0')}';
}

Future<void> _wait(
    WidgetTester tester, bool Function() ready, String label) async {
  final deadline = DateTime.now().add(const Duration(seconds: 20));
  while (!ready() && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  expect(ready(), true,
      reason: 'Synthetic native transaction checkpoint: $label');
  await tester.pump();
}

Future<void> _tap(WidgetTester tester, Key key) async {
  final finder = find.byKey(key);
  await tester.ensureVisible(finder);
  await _wait(tester, () => finder.hitTestable().evaluate().isNotEmpty,
      'tappable native control');
  await tester.tap(finder.hitTestable());
  await tester.pump();
}

Future<void> _mount(WidgetTester tester, _TransactionFixture fixture) async {
  final catalog =
      await fixture.api.getCryptoWalletAssetCatalog(authToken: _token);
  final registered = VaultAssetCatalog.fromJson(catalog).assetFor(
      fixture.asset == kKagAssetId
          ? VaultAssetCategory.digitalSilver
          : VaultAssetCategory.digitalGold)!;
  await tester.pumpWidget(MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: Scaffold(
        body: CryptoWalletEngineSendPanel(
      authToken: _token,
      fromAddress: _sender,
      client: fixture.api,
      decryptForVault: fixture.decrypt,
      isVaultKeyAvailable: () => fixture.unlocked,
      verifyPin: (value) async => value == _pin,
      asset: fixture.asset,
      registeredAsset: registered,
      network: _network,
      mainnetSendEnabled: true,
      fetchAvailableBalance: fixture.coarseTokenBalance,
      fetchEthBalance: fixture.coarseEthBalance,
      fetchAvailableBalanceWei: fixture.exactTokenBalance,
      fetchEthBalanceWei: fixture.exactEthBalance,
      idempotencyKeyGenerator: () => fixture.idempotencyKey,
      outgoingTxStore: fixture.outgoing,
    )),
  ));
  await tester.pumpAndSettle();
  expect(
      MediaQuery.sizeOf(
              tester.element(find.byType(CryptoWalletEngineSendPanel)))
          .shortestSide,
      lessThan(600),
      reason: 'Use an actual iPhone viewport, not an iPad override');
}

Future<void> _review(WidgetTester tester,
    {String amount = _amount, String recipient = _recipient}) async {
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_destination_input')), recipient);
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_amount_input')), amount);
  await _tap(tester, const Key('eth_send_panel_review_btn'));
  await _wait(
      tester,
      () =>
          find
              .byKey(const Key('eth_send_panel_review_stage'))
              .evaluate()
              .isNotEmpty ||
          find
              .byKey(const Key('eth_send_panel_error_banner'))
              .evaluate()
              .isNotEmpty,
      'draft response completed');
}

Future<void> _pinAndSign(WidgetTester tester,
    {String pin = _pin, bool repeatReviewTap = false}) async {
  // A wrong-PIN result can be visible before the previous dialog's pop
  // animation finishes. Complete that transition before a new confirm tap.
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('eth_send_panel_pin_dialog')), findsNothing);
  final key = const Key('eth_send_panel_confirm_btn');
  await tester.ensureVisible(find.byKey(key));
  final callback = tester.widget<ButtonStyleButton>(find.byKey(key)).onPressed;
  await _tap(tester, key);
  if (repeatReviewTap) callback?.call();
  await _wait(
      tester,
      () => find
          .byKey(const Key('eth_send_panel_pin_input'))
          .evaluate()
          .isNotEmpty,
      'PIN dialog');
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('eth_send_panel_pin_dialog')), findsOneWidget);
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_pin_input')), pin);
  await _tap(tester, const Key('eth_send_panel_pin_confirm'));
}

Widget _activity(_TransactionFixture fixture) => MaterialApp(
    key: const ValueKey('paxg-fixture-activity-app'),
    theme: ThemeData.dark(useMaterial3: true),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: Scaffold(
      body: SingleChildScrollView(
          child: CryptoWalletActivityCard(
        asset: fixture.asset,
        network: _network,
        authToken: _token,
        apiClient: fixture.api,
        localStore: fixture.outgoing,
        responseIsCurrent: () => fixture.unlocked,
      )),
    ));

Future<void> _screenshotCheckpoint(WidgetTester tester, String label) async {
  if (!_realStoreEnabled || !_screenshotHolds) return;
  // Test-only stable UI checkpoint; no wire values, credentials or keys.
  debugPrint('PAXG_QA_CHECKPOINT $label');
  await tester.pump(const Duration(seconds: 8));
}

// Small independent RLP decoder/encoder for the exact signed legacy envelope.
// No wallet/account API and no transaction submission is used by this verifier.
List<int> _hexBytes(String value) {
  final hex = value.startsWith('0x') ? value.substring(2) : value;
  _require(
      hex.isNotEmpty &&
          hex.length.isEven &&
          RegExp(r'^[0-9a-fA-F]+$').hasMatch(hex),
      'Invalid synthetic signed transaction encoding');
  return List.generate(hex.length ~/ 2,
      (i) => int.parse(hex.substring(i * 2, i * 2 + 2), radix: 16));
}

BigInt _integer(List<int> bytes) =>
    bytes.fold(BigInt.zero, (value, byte) => (value << 8) + BigInt.from(byte));
String _hex(List<int> bytes) =>
    bytes.map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();

List<List<int>> _decodeLegacy(String raw) {
  final bytes = _hexBytes(raw);
  final tag = bytes.first;
  _require(tag >= 0xc0, 'Expected a legacy RLP list');
  final lengthBytes = tag <= 0xf7 ? 0 : tag - 0xf7;
  final start = 1 + lengthBytes;
  final length =
      lengthBytes == 0 ? tag - 0xc0 : _integer(bytes.sublist(1, start)).toInt();
  _require(
      start + length == bytes.length, 'Synthetic signed RLP trailing data');
  var cursor = start;
  final fields = <List<int>>[];
  while (cursor < bytes.length) {
    final prefix = bytes[cursor++];
    if (prefix < 0x80) {
      fields.add([prefix]);
      continue;
    }
    _require(prefix < 0xc0, 'Nested signed transaction field');
    var size = prefix - 0x80;
    if (prefix > 0xb7) {
      final n = prefix - 0xb7;
      _require(cursor + n <= bytes.length, 'Truncated synthetic RLP length');
      size = _integer(bytes.sublist(cursor, cursor + n)).toInt();
      cursor += n;
    }
    _require(cursor + size <= bytes.length, 'Truncated synthetic RLP field');
    fields.add(bytes.sublist(cursor, cursor + size));
    cursor += size;
  }
  _require(fields.length == 9, 'Legacy transaction field count mismatch');
  return fields;
}

List<int> _lengthBytes(int value) {
  final bytes = <int>[];
  while (value > 0) {
    bytes.insert(0, value & 255);
    value >>= 8;
  }
  return bytes;
}

List<int> _encodeBytes(List<int> bytes) {
  if (bytes.length == 1 && bytes.first < 0x80) return bytes;
  if (bytes.length <= 55) return [0x80 + bytes.length, ...bytes];
  final length = _lengthBytes(bytes.length);
  return [0xb7 + length.length, ...length, ...bytes];
}

Uint8List _encodeList(List<List<int>> fields) {
  final payload = fields.expand(_encodeBytes).toList();
  if (payload.length <= 55) {
    return Uint8List.fromList([0xc0 + payload.length, ...payload]);
  }
  final length = _lengthBytes(payload.length);
  return Uint8List.fromList([0xf7 + length.length, ...length, ...payload]);
}

void _assertSignedTransfer(_TransactionFixture fixture) {
  expect(fixture.broadcasts, hasLength(1));
  final raw = fixture.broadcasts.single['signedTransaction'] as String;
  _assertRawTransfer(raw, contract: fixture.contract);
  expect(fixture.encryptedDraft?['amountEth'], _amount);
  expect(fixture.outgoing.all.single.txHash, computeLocalEthTxHash(raw));
}

void _assertRawTransfer(String raw, {String contract = kPaxgContractAddress}) {
  final fields = _decodeLegacy(raw);
  expect(_integer(fields[0]), BigInt.from(7));
  expect(_integer(fields[1]), BigInt.from(1000000000));
  expect(_integer(fields[2]), BigInt.from(60000));
  expect('0x${_hex(fields[3])}', contract.toLowerCase());
  expect(_integer(fields[4]), BigInt.zero);
  expect('0x${_hex(fields[5])}', _transferData(_amount));
  expect(_integer(fields[6]), anyOf(BigInt.from(37), BigInt.from(38)),
      reason: 'EIP-155 signature must bind Ethereum Mainnet chain 1');
  final curve = ECCurve_secp256k1();
  final signer = ECDSASigner()
    ..init(false, PublicKeyParameter<ECPublicKey>(ECPublicKey(curve.G, curve)));
  final hash = KeccakDigest(256).process(_encodeList([
    ...fields.take(6),
    [1],
    [],
    []
  ]));
  expect(
      signer.verifySignature(
          hash, ECSignature(_integer(fields[7]), _integer(fields[8]))),
      true,
      reason:
          'Signature must verify against public test key 1, not a real wallet');
  expect(_integer(fields[8]) <= (curve.n >> 1), true);
}

void main() {
  _TransactionFixture? active;
  http.runWithClient(() {
    final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
    binding.scheduleForcedFrame();
    _register((fixture) => active = fixture);
  },
      () => MockClient((request) {
            final fixture = active;
            if (fixture == null) {
              throw StateError('Synthetic transaction fixture not ready');
            }
            return fixture.respond(request);
          }));
}

void _register(void Function(_TransactionFixture?) bind) {
  test('offline public signing envelope verifies chain, calldata and signature',
      () {
    final raw = signLegacyEthTransaction(
        nonce: BigInt.from(7),
        gasPrice: BigInt.from(1000000000),
        gasLimit: BigInt.from(60000),
        toAddress: kPaxgContractAddress,
        valueWei: BigInt.zero,
        dataHex: _transferData(_amount),
        chainId: 1,
        privateKeyHex: _publicTestKey);
    _assertRawTransfer(raw);
    final otherChain = signLegacyEthTransaction(
        nonce: BigInt.from(7),
        gasPrice: BigInt.from(1000000000),
        gasLimit: BigInt.from(60000),
        toAddress: kPaxgContractAddress,
        valueWei: BigInt.zero,
        dataHex: _transferData(_amount),
        chainId: 11155111,
        privateKeyHex: _publicTestKey);
    expect(_integer(_decodeLegacy(otherChain)[6]),
        isNot(anyOf(BigInt.from(37), BigInt.from(38))));
  });

  Future<void> scenario(
      WidgetTester tester, Future<void> Function(_TransactionFixture) run,
      {bool realStore = false, String asset = kPaxgAssetId}) async {
    expect(const bool.fromEnvironment('SVAULTAI_PAXG_NATIVE_FIXTURE'), true);
    expect(kIsWeb || kReleaseMode, false);
    expect(defaultTargetPlatform, TargetPlatform.iOS);
    expect(ZkActiveMvk.current(), isNull);
    expect(currentDeviceId(), isNull);
    for (final key in [
      'session_token',
      'last_vault_name',
      'last_vault_handle',
      deviceIdStorageKey
    ]) {
      expect(await NativeSecureStore.readString(key), isNull,
          reason: 'Refusing any Simulator with existing vault/device state');
    }
    final fixture = await _TransactionFixture.create(asset: asset);
    bind(fixture);
    setApiClientDeviceId(_device);
    try {
      if (realStore) {
        _require(asset == kPaxgAssetId, 'Real store bridge remains PAXG-only');
        fixture.realStore = _RealStoreBridge();
        fixture.idempotencyKey =
            'paxg-native-public-fixture-${DateTime.now().microsecondsSinceEpoch}';
        await fixture.realStore!.prepare(fixture.encryptedKey);
      }
      await http.runWithClient(() async {
        await _mount(tester, fixture);
        await run(fixture);
      }, () => MockClient(fixture.respond));
    } finally {
      fixture.realStore?.close();
      fixture.unlocked = false;
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
      fixture.outgoing.dispose();
      ZkActiveMvk.clear();
      setApiClientDeviceId('');
      bind(null);
    }
  }

  testWidgets(
      'native PAXG real isolated encrypted draft verifies the signed transaction once',
      (tester) async {
    await scenario(tester, (fixture) async {
      await _review(tester);
      expect(fixture.encryptedDraft, isNotNull);
      expect(fixture.draftId, isNot(_draftId),
          reason: 'Draft identity must come from the real isolated store');
      await _screenshotCheckpoint(tester, 'review');
      await _pinAndSign(tester, repeatReviewTap: true);
      await _wait(tester, () => fixture.broadcasts.length == 1,
          'real isolated verified broadcast');
      _assertSignedTransfer(fixture);
      await _wait(
          tester,
          () =>
              fixture.outgoing.all.single.status ==
              LocalOutgoingTxStatus.submitted,
          'real isolated submission outcome');
      await _screenshotCheckpoint(tester, 'submitted');
      expect(fixture.broadcasts.single['draftId'], fixture.draftId);
      expect(fixture.realStore!.operations, [
        'GET /__qa/health',
        'POST /__qa/wallet-envelope',
        'POST $_paxg/send/draft',
        'GET $_paxg/encrypted-secret',
        'POST $_paxg/send/broadcast',
      ]);
      expect(fixture.decryptCalls, 1);
      expect(fixture.broadcasts, hasLength(1));
      expect(find.text('Confirmed'), findsNothing);
      expect(fixture.guardFailures, isEmpty);
    }, realStore: true);
  }, skip: !_realStoreEnabled);

  testWidgets(
      'native KAG displays verified holding, receive address and honest history',
      (tester) async {
    await scenario(tester, (fixture) async {
      final registered =
          VaultAssetCatalog.fromJson(_catalog(asset: kKagAssetId))
              .digitalSilver!;
      await tester.pumpWidget(MaterialApp(
        key: const ValueKey('kag-fixture-detail-app'),
        theme: ThemeData.dark(useMaterial3: true),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        home: CryptoWalletEngineAssetDetailPage(
          asset: kKagAssetId,
          network: _network,
          registeredAsset: registered,
          authToken: _token,
          apiClient: fixture.api,
          features: CryptoWalletFeatures.fromBackend({
            'walletEngineEnabled': true,
            'mainnetReceiveEnabled': true,
            'mainnetErc20ReceiveEnabled': true,
            'mainnetSendEnabled': true
          }),
          encryptForVault: (_) async =>
              throw StateError('Existing fixture wallet must not be recreated'),
          isVaultKeyAvailable: () => fixture.unlocked,
          decryptForVault: fixture.decrypt,
          verifyPin: (_) async => true,
          loadFromAddress: (_) async => _sender,
        ),
      ));
      await _wait(
          tester,
          () => find.text('3.000000000000000003 KAG').evaluate().isNotEmpty,
          'verified silver native holding');
      await _wait(
          tester,
          () => fixture.count('GET', '${fixture.assetPath}/transactions') == 1,
          'silver native history request');
      expect(find.byKey(const Key('kag_issuer_terms_link')), findsOneWidget);
      await _tap(
          tester, const Key('crypto_wallet_engine_asset_detail_receive_btn'));
      await _wait(
          tester,
          () => find
              .byKey(const Key('eth_receive_panel_ready_state'))
              .evaluate()
              .isNotEmpty,
          'silver native receive address');
      expect(find.byType(CryptoWalletEngineReceivePanel), findsOneWidget);
      expect(
          find.textContaining('KAG uses your Ethereum Mainnet wallet address'),
          findsOneWidget);
      expect(find.textContaining('PAXG uses'), findsNothing);
      expect(fixture.broadcasts, isEmpty);
      expect(fixture.decryptCalls, 0);
      expect(fixture.guardFailures, isEmpty);
    }, asset: kKagAssetId);
  });

  testWidgets(
      'native KAG signs the pinned silver transfer once and encrypts history',
      (tester) async {
    await scenario(tester, (fixture) async {
      expect(
          find.byKey(const Key('kag_issuer_eligibility_note')), findsOneWidget);
      expect(find.byKey(const Key('kag_issuer_terms_link')), findsOneWidget);
      await _review(tester);
      expect(find.text('$_amount KAG'), findsOneWidget);
      expect(find.textContaining('not direct ownership of silver bars'),
          findsOneWidget);
      await _pinAndSign(tester, repeatReviewTap: true);
      await _wait(
          tester, () => fixture.broadcasts.length == 1, 'silver signed once');
      _assertSignedTransfer(fixture);
      await _wait(tester, () => fixture.encryptedHistory != null,
          'silver encrypted history');
      expect(fixture.encryptedDraft!['asset'], kKagAssetId);
      expect(fixture.encryptedHistory!['asset'], kKagAssetId);
      expect(fixture.decryptCalls, 1);
      expect(fixture.broadcasts, hasLength(1));
      expect(
          fixture.outgoing.all.single.status, LocalOutgoingTxStatus.submitted);
      expect(find.text('Confirmed'), findsNothing);
      expect(fixture.guardFailures, isEmpty);
    }, asset: kKagAssetId);
  });

  testWidgets(
      'native KAG replaced contract and exact gas shortfall never access key',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.wrongContract = true;
      await _review(tester);
      expect(find.textContaining('The token transfer could not be verified.'),
          findsOneWidget);
      expect(fixture.decryptCalls, 0);
      expect(fixture.broadcasts, isEmpty);
    }, asset: kKagAssetId);
    await scenario(tester, (fixture) async {
      await _review(tester);
      fixture.ethBalance = BigInt.zero;
      await _pinAndSign(tester);
      await _wait(
          tester,
          () => find
              .text(kMainnetSendExactFeeInsufficientGasEthError)
              .evaluate()
              .isNotEmpty,
          'silver exact gas shortfall');
      expect(fixture.count('GET', '${fixture.assetPath}/encrypted-secret'), 0);
      expect(fixture.broadcasts, isEmpty);
    }, asset: kKagAssetId);
  });

  testWidgets('native KAG locked key response cannot sign or broadcast',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.secretResponse = Completer<http.Response>();
      await _review(tester);
      await _pinAndSign(tester);
      await _wait(
          tester,
          () =>
              fixture.count('GET', '${fixture.assetPath}/encrypted-secret') ==
              1,
          'silver key response pending');
      fixture.unlocked = false;
      ZkActiveMvk.clear();
      fixture.secretResponse!.complete(fixture.json({
        'status': 'encrypted_secret_ready',
        'encryptedWalletSecret': fixture.encryptedKey
      }));
      await _wait(
          tester,
          () => find
              .text(kEthSendErrorSigningKeyUnavailable)
              .evaluate()
              .isNotEmpty,
          'silver locked signing refused');
      expect(fixture.decryptCalls, 0);
      expect(fixture.broadcasts, isEmpty);
    }, asset: kKagAssetId);
  });

  testWidgets(
      'native KAG uncertain outcome and unavailable history never claim confirmed',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.malformedBroadcast = true;
      await _review(tester);
      await _pinAndSign(tester);
      await _wait(
          tester,
          () => find.text(kEthSendResultHeadingUncertain).evaluate().isNotEmpty,
          'silver conservative unknown outcome');
      _assertSignedTransfer(fixture);
      expect(fixture.outgoing.all.single.status,
          LocalOutgoingTxStatus.submissionUncertain);
      fixture.historyUnavailable = true;
      await tester.pumpWidget(_activity(fixture));
      await tester.pumpAndSettle();
      expect(find.text(kActivityStatusSubmissionUncertain), findsOneWidget);
      expect(find.text(kActivityStatusConfirmed), findsNothing);
      expect(fixture.broadcasts, hasLength(1));
      expect(fixture.guardFailures, isEmpty);
    }, asset: kKagAssetId);
  });

  testWidgets('native PAXG validates amount and recipient before any draft/key',
      (tester) async {
    await scenario(tester, (fixture) async {
      for (final invalid in ['0.0000000000000000001', '1e-18']) {
        await _review(tester, amount: invalid);
        expect(fixture.count('POST', '$_paxg/send/draft'), 0);
      }
      await _review(tester, recipient: _sender);
      expect(find.text(kEthSendFormValidationSelfSend), findsOneWidget);
      expect(fixture.decryptCalls, 0);
      expect(fixture.broadcasts, isEmpty);
    });
  });

  testWidgets(
      'native PAXG signs exact 18-decimal pinned transfer and duplicate tap broadcasts once',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.broadcastResponse = Completer<http.Response>();
      await _review(tester);
      expect(
          find.byKey(const Key('eth_send_panel_review_stage')), findsOneWidget);
      expect(find.text('$_amount PAXG'), findsOneWidget);
      expect(find.byKey(const Key('send_asset_issuer_transfer_note')),
          findsOneWidget);
      await _pinAndSign(tester, repeatReviewTap: true);
      await _wait(tester, () => fixture.broadcasts.length == 1,
          'signed fixture broadcast');
      _assertSignedTransfer(fixture);
      expect(fixture.decryptCalls, 1);
      expect(fixture.count('POST', '$_paxg/send/draft'), 1);
      expect(
          fixture.outgoing.all.single.status, LocalOutgoingTxStatus.submitting);
      fixture.broadcastResponse!.complete(fixture.json({
        'status': 'submitted',
        'txHash': fixture.outgoing.all.single.txHash
      }));
      await _wait(
          tester,
          () => find.text(kEthSendResultHeadingSubmitted).evaluate().isNotEmpty,
          'honest submitted result');
      await _wait(tester, () => fixture.encryptedHistory != null,
          'encrypted outgoing history');
      expect(
          fixture.outgoing.all.single.status, LocalOutgoingTxStatus.submitted);
      expect(fixture.encryptedHistory?['asset'], kPaxgAssetId);
      expect(fixture.encryptedHistory?['amount'], _amount);
      expect(fixture.encryptedHistory?['destinationAddress'], _recipient);
      expect(fixture.broadcasts, hasLength(1));
      expect(find.text('Confirmed'), findsNothing);
      expect(fixture.guardFailures, isEmpty);
    });
  });

  testWidgets(
      'native PAXG replaced contract is rejected before wallet key access',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.wrongContract = true;
      await _review(tester);
      expect(find.textContaining('The token transfer could not be verified.'),
          findsOneWidget);
      expect(fixture.count('GET', '$_paxg/encrypted-secret'), 0);
      expect(fixture.broadcasts, isEmpty);
    });
  });

  testWidgets(
      'native PAXG ETH gas balance decreasing after review blocks before signing',
      (tester) async {
    await scenario(tester, (fixture) async {
      await _review(tester);
      fixture.ethBalance = BigInt.zero;
      await _pinAndSign(tester);
      await _wait(
          tester,
          () => find
              .text(kMainnetSendExactFeeInsufficientGasEthError)
              .evaluate()
              .isNotEmpty,
          'post-PIN exact ETH gas balance gate');
      expect(fixture.count('GET', '$_paxg/encrypted-secret'), 0);
      expect(fixture.broadcasts, isEmpty);
    });
  });

  testWidgets(
      'native PAXG changed gas quote and wrong PIN do not fetch a signing key',
      (tester) async {
    await scenario(tester, (fixture) async {
      await _review(tester);
      await _pinAndSign(tester, pin: '000000');
      await _wait(
          tester,
          () => find.text(kEthSendErrorPinWrong).evaluate().isNotEmpty,
          'wrong PIN refusal');
      expect(fixture.count('GET', '$_paxg/encrypted-secret'), 0);
      fixture.refreshGasLimit = BigInt.from(70000);
      await _pinAndSign(tester);
      await _wait(
          tester,
          () =>
              find.text(kMainnetSendFeeQuoteChangedError).evaluate().isNotEmpty,
          'changed quote requires review');
      expect(fixture.count('GET', '$_paxg/encrypted-secret'), 0);
      expect(fixture.broadcasts, isEmpty);
    });
  });

  testWidgets(
      'native PAXG token balance decreasing after review blocks before signing',
      (tester) async {
    await scenario(tester, (fixture) async {
      await _review(tester);
      fixture.tokenBalance = BigInt.zero;
      await _pinAndSign(tester);
      await _wait(
          tester,
          () =>
              find
                  .text(kMainnetSendExactFeeInsufficientTokenError)
                  .evaluate()
                  .isNotEmpty ||
              fixture.broadcasts.isNotEmpty,
          'post-PIN exact token balance gate');
      expect(fixture.exactTokenReads, greaterThan(0));
      expect(find.text(kMainnetSendExactFeeInsufficientTokenError),
          findsOneWidget);
      expect(fixture.count('GET', '$_paxg/encrypted-secret'), 0);
      expect(fixture.broadcasts, isEmpty);
    });
  });

  for (final duringDecrypt in [false, true]) {
    testWidgets(
        'native PAXG lock during ${duringDecrypt ? 'decrypt' : 'key fetch'} prevents signing',
        (tester) async {
      await scenario(tester, (fixture) async {
        if (duringDecrypt) {
          fixture.decryptGate = Completer<void>();
        } else {
          fixture.secretResponse = Completer<http.Response>();
        }
        await _review(tester);
        await _pinAndSign(tester);
        await _wait(
            tester,
            () => duringDecrypt
                ? fixture.decryptCalls == 1
                : fixture.count('GET', '$_paxg/encrypted-secret') == 1,
            'guarded key operation pending');
        fixture.unlocked = false;
        ZkActiveMvk.clear();
        if (duringDecrypt) {
          fixture.decryptGate!.complete();
        } else {
          fixture.secretResponse!.complete(fixture.json({
            'status': 'encrypted_secret_ready',
            'encryptedWalletSecret': fixture.encryptedKey
          }));
        }
        await _wait(
            tester,
            () => find
                .text(kEthSendErrorSigningKeyUnavailable)
                .evaluate()
                .isNotEmpty,
            'locked signing refused');
        expect(fixture.broadcasts, isEmpty);
        expect(fixture.outgoing.all, isEmpty);
        expect(tester.takeException(), isNull);
      });
    });
  }

  testWidgets(
      'native PAXG uncertain broadcast, receipt failure and unavailable history never claim confirmed',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.broadcastStatus = 'submission_uncertain';
      await _review(tester);
      await _pinAndSign(tester);
      await _wait(
          tester,
          () => find.text(kEthSendResultHeadingUncertain).evaluate().isNotEmpty,
          'uncertain result');
      _assertSignedTransfer(fixture);
      fixture.receiptThrows = true;
      await _tap(tester, const Key('eth_send_panel_check_status_btn'));
      await tester.pumpAndSettle();
      expect(fixture.outgoing.all.single.status,
          LocalOutgoingTxStatus.submissionUncertain);
      expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
      fixture.receiptThrows = false;
      fixture.receiptStatus = 'pending';
      await _tap(tester, const Key('eth_send_panel_check_status_btn'));
      await _wait(
          tester,
          () =>
              fixture.outgoing.all.single.status ==
              LocalOutgoingTxStatus.pending,
          'receipt pending');
      fixture.historyUnavailable = true;
      await tester.pumpWidget(_activity(fixture));
      await tester.pumpAndSettle();
      expect(fixture.count('GET', '$_paxg/transactions'), 1);
      expect(find.text(kActivityStatusPending), findsOneWidget);
      expect(find.text(kActivityStatusConfirmed), findsNothing);
      expect(fixture.outgoing.all.single.status, LocalOutgoingTxStatus.pending);
      expect(fixture.broadcasts, hasLength(1));
    });
  });

  testWidgets(
      'native PAXG malformed broadcast outcome remains uncertain, not a fresh-send invitation',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.malformedBroadcast = true;
      await _review(tester);
      await _pinAndSign(tester);
      await _wait(
          tester,
          () =>
              fixture.broadcasts.isNotEmpty &&
              find
                  .byKey(const Key('eth_send_panel_signing'))
                  .evaluate()
                  .isEmpty,
          'opaque broadcast outcome');
      expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
      expect(fixture.outgoing.all.single.status,
          LocalOutgoingTxStatus.submissionUncertain);
      expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
    });
  });

  testWidgets(
      'native PAXG late broadcast after lock/dispose cannot publish old results',
      (tester) async {
    await scenario(tester, (fixture) async {
      fixture.broadcastResponse = Completer<http.Response>();
      await _review(tester);
      await _pinAndSign(tester);
      await _wait(tester, () => fixture.broadcasts.length == 1,
          'broadcast response pending');
      final pendingHash = fixture.outgoing.all.single.txHash;
      expect(
          fixture.outgoing.all.single.status, LocalOutgoingTxStatus.submitting);
      fixture.unlocked = false;
      ZkActiveMvk.clear();
      await tester.pumpWidget(MaterialApp(
          key: const ValueKey('paxg-fixture-locked-app'),
          theme: ThemeData.dark(useMaterial3: true),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('en'),
          home: const Scaffold(body: Text('Synthetic vault locked'))));
      await tester.pumpAndSettle();
      fixture.broadcastResponse!.complete(fixture.json({
        'status': 'submitted',
        'txHash': fixture.outgoing.all.single.txHash
      }));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();
      expect(find.text('Synthetic vault locked'), findsOneWidget);
      expect(find.text(kEthSendResultHeadingSubmitted), findsNothing);
      expect(fixture.outgoing.all.single.txHash, pendingHash);
      expect(
          fixture.outgoing.all.single.status, LocalOutgoingTxStatus.submitting);
      expect(tester.takeException(), isNull);
    });
  });
}
