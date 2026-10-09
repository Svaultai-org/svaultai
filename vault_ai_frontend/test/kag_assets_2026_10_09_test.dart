import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/ethereum_transaction.dart';
import 'package:vault_ai_frontend/services/local_outgoing_tx_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/kag_issuer_notice.dart';

import 'asset_catalog_2026_10_09_test.dart' show catalogFixture;

// Offline-only, public compromised key 1. No account, provider or RPC use.
const _key = '0000000000000000000000000000000000000000000000000000000000000001';
const _sender = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const _recipient = '0x2222222222222222222222222222222222222222';
const _amount = '1.000000000000000001';
const _network = 'ethereum_mainnet';
final _features = CryptoWalletFeatures.fromBackend({
  'walletEngineEnabled': true,
  'mainnetReceiveEnabled': true,
  'mainnetErc20ReceiveEnabled': true,
  'mainnetSendEnabled': true,
});

Map<String, dynamic> kagCatalogFixture(
    {Map<String, dynamic> overrides = const {}}) {
  final raw = catalogFixture();
  (raw['categories'] as List).add({'id': 'digital_silver', 'available': true});
  (raw['assets'] as List).add({
    'id': kKagAssetId,
    'category': 'digital_silver',
    'symbol': 'KAG',
    'name': 'KMS Labs KAG Silver',
    'standard': 'ERC20',
    'network': _network,
    'chainId': 1,
    'decimals': 18,
    'contractAddress': kKagContractAddress,
    'verified': true,
    'balanceEnabled': true,
    'receiveEnabled': true,
    'sendEnabled': true,
    'activityConnected': true,
    'verificationSource': kKagIssuerTermsUrl,
    ...overrides,
  });
  return raw;
}

Map<String, dynamic> _balance(String asset) => {
      'asset': asset,
      'networkId': _network,
      'chainId': 1,
      'publicAddress': _sender,
      'balanceStatus': 'available',
      'decimals': 18,
      'unit': asset == 'ETH' ? 'ETH' : 'KAG',
      'tokenContract': asset == 'ETH' ? null : kKagContractAddress,
      'availableAmount': '2',
      'baseUnits': '2000000000000000000',
      'weiAmount': '2000000000000000000',
      'spendableBalanceWei': '2000000000000000000',
    };

Map<String, dynamic> _draft(String amount) => {
      'status': 'draft_ready',
      'draftId': 'offline-kag-draft',
      'asset': kKagAssetId,
      'chainId': 1,
      'fromAddress': _sender,
      'destinationAddress': _recipient,
      'transactionTo': kKagContractAddress,
      'transactionValueWei': '0',
      'unit': 'KAG',
      'amount': amount,
      'amountBaseUnits': '${parseAssetBaseUnits(amount, 18)}',
      'decimals': 18,
      'nonce': '7',
      'gasLimit': '60000',
      'gasPrice': '1000000000',
      'dataHex': '0xa9059cbb${_recipient.substring(2).padLeft(64, '0')}'
          '${parseAssetBaseUnits(amount, 18).toRadixString(16).padLeft(64, '0')}',
    };

class _Client extends VaultAIClient {
  _Client() : super(baseUrl: 'http://kag-offline.invalid');
  int keyCalls = 0;
  int broadcasts = 0;
  int receiveCalls = 0;
  int createCalls = 0;
  int historyCalls = 0;
  String? createdAsset;
  String? createdNetwork;
  String? signed;
  String? quoteAmount;
  BigInt exactEth = BigInt.parse('2000000000000000000');
  bool noWallet = false;
  bool malformedBroadcast = false;
  Map<String, dynamic> catalogOverrides = {};
  Map<String, dynamic> draftOverrides = {};
  Map<String, dynamic> feeOverrides = {};
  Map<String, dynamic> balanceOverrides = {};
  Completer<Map<String, dynamic>>? secretGate;
  final balanceAssets = <String>[];
  final receiveAssets = <String>[];

  @override
  Future<Map<String, dynamic>> getCryptoWalletAssetCatalog({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async =>
      kagCatalogFixture(overrides: catalogOverrides);
  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async =>
      {
        'walletEngineEnabled': true,
        'mainnetReceiveEnabled': true,
        'mainnetErc20ReceiveEnabled': true,
        'mainnetSendEnabled': true
      };
  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCalls++;
    receiveAssets.add(asset);
    return {
      'wallet_engine': noWallet ? 'create_eth_wallet_first' : 'receive_ready',
      if (!noWallet) 'publicAddress': _sender
    };
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccountNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String encryptedWalletSecret,
    int? restoreHeight,
    String? scannerMode,
  }) async {
    createCalls++;
    createdAsset = asset;
    createdNetwork = network;
    expect(encryptedWalletSecret, 'ciphertext-only');
    return {'wallet_engine': 'receive_ready', 'publicAddress': publicAddress};
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    String? address,
  }) async {
    balanceAssets.add(asset);
    return {..._balance(asset), ...balanceOverrides};
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    historyCalls++;
    return {'transactionsStatus': 'available', 'transactions': []};
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraftNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    String? amountEth,
    String? amountSol,
    String? amountUsdt,
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async =>
      {..._draft(amountEth!), ...draftOverrides};
  @override
  Future<Map<String, dynamic>> postCryptoWalletKagSendFeeEstimateNetwork({
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
    required String authToken,
  }) async {
    quoteAmount = amountEth;
    return {
      'status': 'fee_estimate_ready',
      'asset': kKagAssetId,
      'network': _network,
      'chainId': 1,
      'amountBaseUnits': '${parseAssetBaseUnits(amountEth, 18)}',
      'gasLimit': '60000',
      'gasPriceWei': '1000000000',
      'authorizedMaxFeeBaseUnits': '60000000000000',
      ...feeOverrides
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    keyCalls++;
    return secretGate != null
        ? secretGate!.future
        : {
            'status': 'encrypted_secret_ready',
            'encryptedWalletSecret': 'offline-ciphertext'
          };
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcasts++;
    signed = signedTransaction as String;
    return malformedBroadcast
        ? {'unexpected': true}
        : {'status': 'submitted', 'txHash': computeLocalEthTxHash(signed!)};
  }
}

Widget _app(Widget child) => MaterialApp(
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: Scaffold(body: child));

RegisteredVaultAsset get _kag =>
    VaultAssetCatalog.fromJson(kagCatalogFixture()).digitalSilver!;

Future<void> _send(
  WidgetTester tester,
  _Client client, {
  BigInt? tokens,
  BigInt? eth,
  bool Function()? unlocked,
  LocalOutgoingTxStore? outgoing,
}) async {
  await tester.pumpWidget(_app(CryptoWalletEngineSendPanel(
    authToken: 'offline-session',
    fromAddress: _sender,
    client: client,
    asset: kKagAssetId,
    network: _network,
    registeredAsset: _kag,
    mainnetSendEnabled: true,
    decryptForVault: (_) async => _key,
    isVaultKeyAvailable: unlocked ?? () => true,
    verifyPin: (_) async => true,
    fetchAvailableBalance: () async => 2,
    fetchEthBalance: () async => 2,
    fetchAvailableBalanceWei: () async =>
        tokens ?? BigInt.parse('2000000000000000000'),
    fetchEthBalanceWei: () async => eth ?? client.exactEth,
    outgoingTxStore: outgoing,
  )));
  await tester.pumpAndSettle();
  expect(find.text(kKagEligibilityNote), findsOneWidget);
  expect(find.text(kKagIssuerTermsUrl), findsOneWidget);
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_destination_input')), _recipient);
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_amount_input')), _amount);
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.pumpAndSettle();
}

Future<void> _confirm(WidgetTester tester) async {
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.pumpAndSettle();
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_pin_input')), '918273');
  await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
  for (var i = 0; i < 8; i++) {
    await tester.pump();
  }
}

void main() {
  setUp(() {
    ZkActiveMvk.clear();
    AssetLiveStore.instance.resetForTest();
  });
  tearDown(() {
    ZkActiveMvk.clear();
    AssetLiveStore.instance.resetForTest();
  });

  test(
      'gold and issuer-verified KAG remain independent pinned registry entries',
      () {
    final catalog = VaultAssetCatalog.fromJson(kagCatalogFixture());
    expect(catalog.digitalGoldAvailable, isTrue);
    expect(catalog.digitalSilverAvailable, isTrue);
    expect(_kag.id, kKagAssetId);
    expect(_kag.name, 'KMS Labs KAG Silver');
    expect(_kag.symbol, 'KAG');
    expect(_kag.decimals, 18);
    expect(_kag.contractAddress, kKagContractAddress);
    expect(_kag.verificationSource, kKagIssuerTermsUrl);
    expect(_kag.transferNote, contains('not direct ownership of silver bars'));
    expect(erc20AssetSpec(kKagAssetId)!.decimals, 18);
  });
  for (final override in [
    {'chainId': 11155111},
    {'chainId': '1'},
    {'network': 'kinesis_mainnet'},
    {'contractAddress': kPaxgContractAddress},
    {'decimals': 6},
    {'standard': 'ERC721'},
    {'category': 'digital_gold'},
    {'symbol': 'PAXG'},
    {'name': 'Silver bars'},
    {'verified': false},
  ]) {
    test('KAG rejects unexpected issuer tuple $override without disabling gold',
        () {
      final catalog =
          VaultAssetCatalog.fromJson(kagCatalogFixture(overrides: override));
      expect(catalog.digitalSilver, isNull);
      expect(catalog.digitalSilverAvailable, isFalse);
      expect(catalog.digitalGoldAvailable, isTrue);
    });
  }
  test('duplicate silver or disabled capabilities never grant usable wallets',
      () {
    final duplicate = kagCatalogFixture();
    (duplicate['assets'] as List).add((duplicate['assets'] as List).last);
    expect(VaultAssetCatalog.fromJson(duplicate).digitalSilver, isNull);
    expect(
        VaultAssetCatalog.fromJson(
                kagCatalogFixture(overrides: {'balanceEnabled': false}))
            .digitalSilverAvailable,
        isFalse);
    expect(
        VaultAssetCatalog.fromJson(
                kagCatalogFixture(overrides: {'receiveEnabled': false}))
            .digitalSilverAvailable,
        isTrue,
        reason: 'Paused transfers must not hide verified existing holdings');
  });
  test('KAG validates exact 18-decimal integer balance and transfer, not gold',
      () {
    expect(_kag.validatesBalance(_balance(kKagAssetId), _sender), isTrue);
    expect(
        _kag.validatesBalance(
            {..._balance(kKagAssetId), 'tokenContract': kPaxgContractAddress},
            _sender),
        isFalse);
    expect(
        _kag.validatesTransferDraft(_draft(_amount),
            fromAddress: _sender, destination: _recipient, amount: _amount),
        isTrue);
    for (final mutation in [
      {'transactionTo': kPaxgContractAddress},
      {'chainId': 11155111},
      {'unit': 'PAXG'},
      {'amountBaseUnits': '1'},
      {'transactionValueWei': '1'},
      {'decimals': 6},
      {'dataHex': '0xa9059cbb'},
    ]) {
      expect(
          _kag.validatesTransferDraft({..._draft(_amount), ...mutation},
              fromAddress: _sender, destination: _recipient, amount: _amount),
          isFalse);
    }
  });
  test('KAG source URL is issuer HTTPS only, never a signing capability', () {
    for (final url in [
      'http://kmslabs.money/documents/',
      'https://kmslabs.money.evil.invalid/',
      'https://user@kmslabs.money/'
    ]) {
      expect(
          VaultAssetCatalog.fromJson(
                  kagCatalogFixture(overrides: {'verificationSource': url}))
              .digitalSilver!
              .verificationSource,
          isNull);
    }
  });
  test(
      'closed KAG gas route transmits the exact amount without arbitrary contract',
      () async {
    await http.runWithClient(() async {
      await VaultAIClient(baseUrl: 'http://kag-offline.invalid')
          .postCryptoWalletKagSendFeeEstimateNetwork(
              fromAddress: _sender,
              destinationAddress: _recipient,
              amountEth: _amount,
              authToken: 'offline-session');
    },
        () => MockClient((request) async {
              expect(request.url.host, 'kag-offline.invalid');
              expect(request.url.path,
                  '/crypto/wallet/network/ethereum_mainnet/send/fee_estimate');
              expect(jsonDecode(request.body), {
                'fromAddress': _sender,
                'destinationAddress': _recipient,
                'asset': kKagAssetId,
                'amountEth': _amount
              });
              return http.Response('{}', 200);
            }));
  });
  for (final amount in ['0', '-1', ' 1', '1e3', '0.0000000000000000001']) {
    test('invalid KAG quote $amount fails before request', () async {
      var calls = 0;
      await http.runWithClient(() async {
        expect(
            () => VaultAIClient(baseUrl: 'http://kag-offline.invalid')
                .postCryptoWalletKagSendFeeEstimateNetwork(
                    fromAddress: _sender,
                    destinationAddress: _recipient,
                    amountEth: amount,
                    authToken: 'offline-session'),
            throwsFormatException);
      },
          () => MockClient((_) async {
                calls++;
                return http.Response('{}', 200);
              }));
      expect(calls, 0);
    });
  }
  testWidgets(
      'verified silver detail shows real balance/history and eligibility before wallet actions',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(AssetsPage(
      cryptocurrency: const Text('Existing crypto'),
      authToken: 'offline-session',
      apiClient: client,
      isVaultKeyAvailable: () => true,
      encryptForVault: (_) async => 'ciphertext-only',
      decryptForVault: (_) async => _key,
      verifyPin: (_) async => true,
      loadFromAddress: (_) async => _sender,
    )));
    await tester.pumpAndSettle();
    await tester
        .ensureVisible(find.byKey(const Key('assets_category_digital_silver')));
    await tester.tap(find.byKey(const Key('assets_category_digital_silver')));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<Text>(find
                .byKey(const Key('crypto_wallet_engine_asset_detail_title')))
            .data,
        'KMS Labs KAG Silver');
    expect(find.text('2 KAG'), findsOneWidget);
    expect(find.text(kKagEligibilityNote), findsOneWidget);
    expect(find.byKey(const Key('kag_issuer_terms_link')), findsOneWidget);
    expect(client.balanceAssets, contains(kKagAssetId));
    expect(client.historyCalls, 1);
    expect(find.text('Buy'), findsNothing);
    expect(find.text('Trade'), findsNothing);
  });
  testWidgets(
      'unsupported inventory and securities say Coming soon and have no wallet actions',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(AssetsPage(
        cryptocurrency: const Text('Existing crypto'),
        authToken: 'offline-session',
        apiClient: client)));
    await tester.pumpAndSettle();
    for (final category in [
      VaultAssetCategory.inventory,
      VaultAssetCategory.securities
    ]) {
      await tester.scrollUntilVisible(
          find.byKey(Key('assets_category_${category.id}')), 250,
          scrollable: find.descendant(
              of: find.byType(AssetsPage), matching: find.byType(Scrollable)));
      await tester.tap(find.byKey(Key('assets_category_${category.id}')));
      await tester.pumpAndSettle();
      expect(find.text('Coming soon'), findsOneWidget);
      expect(find.text('Receive'), findsNothing);
      expect(find.text('Send'), findsNothing);
      await tester.pageBack();
      await tester.pumpAndSettle();
    }
    expect(client.receiveCalls, 0);
    expect(client.balanceAssets, isEmpty);
  });
  testWidgets('KAG receive creates only encrypted parent ETH wallet',
      (tester) async {
    final client = _Client()..noWallet = true;
    await tester.pumpWidget(_app(CryptoWalletEngineReceivePanel(
        authToken: 'offline-session',
        client: client,
        asset: kKagAssetId,
        network: _network,
        registeredAsset: _kag,
        encryptForVault: (_) async => 'ciphertext-only',
        isVaultKeyAvailable: () => true)));
    await tester.pumpAndSettle();
    expect(find.textContaining('receive KAG'), findsOneWidget);
    expect(find.text(kKagEligibilityNote), findsOneWidget);
    await tester
        .ensureVisible(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.pumpAndSettle();
    expect(client.createCalls, 1);
    expect(client.createdAsset, 'ETH');
    expect(client.createdNetwork, _network);
  });
  testWidgets(
      'paused KAG keeps balance/history readable but receive/send disabled',
      (tester) async {
    final client = _Client()
      ..catalogOverrides = {'receiveEnabled': false, 'sendEnabled': false};
    await tester.pumpWidget(_app(AssetsPage(
        cryptocurrency: const Text('Existing crypto'),
        authToken: 'offline-session',
        apiClient: client,
        isVaultKeyAvailable: () => true,
        encryptForVault: (_) async => 'ciphertext-only',
        decryptForVault: (_) async => _key,
        verifyPin: (_) async => true,
        loadFromAddress: (_) async => _sender)));
    await tester.pumpAndSettle();
    await tester
        .ensureVisible(find.byKey(const Key('assets_category_digital_silver')));
    await tester.tap(find.byKey(const Key('assets_category_digital_silver')));
    await tester.pumpAndSettle();
    expect(find.text('2 KAG'), findsOneWidget);
    expect(client.historyCalls, 1);
    expect(client.receiveAssets, ['ETH']);
    expect(
        tester
            .widget<ElevatedButton>(find.byKey(
                const Key('crypto_wallet_engine_asset_detail_receive_btn')))
            .onPressed,
        isNull);
    expect(
        tester
            .widget<ElevatedButton>(find
                .byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')))
            .onPressed,
        isNull);
    expect(
        find.text('Receiving is unavailable under the current issuer rules.'),
        findsOneWidget);
  });
  testWidgets('unregistered KAG receives no address and makes no API request',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(CryptoWalletEngineReceivePanel(
        authToken: 'offline-session',
        client: client,
        asset: kKagAssetId,
        network: _network,
        encryptForVault: (_) async => 'ciphertext-only',
        isVaultKeyAvailable: () => true)));
    await tester.pumpAndSettle();
    expect(client.receiveCalls, 0);
    expect(find.byKey(const Key('eth_receive_panel_create_btn')), findsNothing);
  });
  testWidgets(
      'KAG detail supplies fresh exact token and ETH balances, not cached display',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(CryptoWalletEngineAssetDetailPage(
        asset: kKagAssetId,
        network: _network,
        authToken: 'offline-session',
        registeredAsset: _kag,
        apiClient: client,
        features: _features,
        encryptForVault: (_) async => 'ciphertext-only',
        isVaultKeyAvailable: () => true,
        decryptForVault: (_) async => _key,
        verifyPin: (_) async => true,
        loadFromAddress: (_) async => _sender)));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
    await tester.tap(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
    await tester.pumpAndSettle();
    final panel = tester.widget<CryptoWalletEngineSendPanel>(
        find.byType(CryptoWalletEngineSendPanel));
    final before = client.balanceAssets.length;
    expect(await panel.fetchAvailableBalanceWei!(),
        BigInt.parse('2000000000000000000'));
    expect(
        await panel.fetchEthBalanceWei!(), BigInt.parse('2000000000000000000'));
    expect(client.balanceAssets.skip(before), [kKagAssetId, 'ETH']);
    client.balanceOverrides = {'tokenContract': kPaxgContractAddress};
    expect(await panel.fetchAvailableBalanceWei!(), isNull);
  });
  testWidgets('KAG signs exact pinned amount after exact gas authorization',
      (tester) async {
    final client = _Client();
    await _send(tester, client);
    await _confirm(tester);
    await tester.pumpAndSettle();
    expect(client.quoteAmount, _amount);
    expect(client.keyCalls, 1);
    expect(client.broadcasts, 1);
    expect(client.signed!.toLowerCase(),
        contains(kKagContractAddress.substring(2).toLowerCase()));
    expect(
        client.signed!,
        contains(parseAssetBaseUnits(_amount, 18)
            .toRadixString(16)
            .padLeft(64, '0')));
    expect(find.text(kEthSendResultHeadingSubmitted), findsOneWidget);
    expect(find.text('Confirmed'), findsNothing);
  });
  for (final override in [
    {'asset': kPaxgAssetId},
    {'amountBaseUnits': '1'},
    {'chainId': 11155111},
    {'authorizedMaxFeeBaseUnits': '0'},
    {'gasLimit': null},
    {'gasPriceWei': '-1'},
  ]) {
    testWidgets('KAG invalid exact fee $override never fetches signing key',
        (tester) async {
      final client = _Client()..feeOverrides = override;
      await _send(tester, client);
      await _confirm(tester);
      await tester.pumpAndSettle();
      expect(client.keyCalls, 0);
      expect(client.broadcasts, 0);
    });
  }
  testWidgets('KAG post-review ETH shortfall prevents signing', (tester) async {
    final client = _Client();
    await _send(tester, client);
    client.exactEth = BigInt.zero;
    await _confirm(tester);
    await tester.pumpAndSettle();
    expect(client.keyCalls, 0);
    expect(client.broadcasts, 0);
    expect(
        find.text(kMainnetSendExactFeeInsufficientGasEthError), findsOneWidget);
  });
  testWidgets(
      'KAG lock while encrypted key awaits prevents decryption/broadcast',
      (tester) async {
    final client = _Client()..secretGate = Completer<Map<String, dynamic>>();
    var unlocked = true;
    await _send(tester, client, unlocked: () => unlocked);
    await _confirm(tester);
    expect(client.keyCalls, 1);
    unlocked = false;
    client.secretGate!.complete({
      'status': 'encrypted_secret_ready',
      'encryptedWalletSecret': 'offline-ciphertext'
    });
    await tester.pumpAndSettle();
    expect(client.broadcasts, 0);
  });
  testWidgets('opaque KAG broadcast retains the signed hash as uncertain',
      (tester) async {
    final client = _Client()..malformedBroadcast = true;
    final store = LocalOutgoingTxStore();
    addTearDown(store.dispose);
    await _send(tester, client, outgoing: store);
    await _confirm(tester);
    await tester.pumpAndSettle();
    expect(store.all.single.txHash, computeLocalEthTxHash(client.signed!));
    expect(store.all.single.status, LocalOutgoingTxStatus.submissionUncertain);
    expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
    expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
  });
}
