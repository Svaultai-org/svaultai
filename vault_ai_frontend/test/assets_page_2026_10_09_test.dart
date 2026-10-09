import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/ui/assets_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

import 'asset_catalog_2026_10_09_test.dart'
    show catalogFixture, paxgDraftFixture;

const _features = <String, dynamic>{
  'walletEngineEnabled': true,
  'mainnetReceiveEnabled': true,
  'mainnetErc20ReceiveEnabled': true,
  'mainnetSendEnabled': true,
  'mainnetSendPaused': false,
};

class _Client extends VaultAIClient {
  _Client(
      {Map<String, dynamic>? catalog,
      this.catalogCompleter,
      this.noWallet = false,
      this.invalidDraft = false,
      this.keyCompleter,
      this.keyReady = false})
      : catalog = catalog ?? catalogFixture(),
        super(baseUrl: 'https://test.invalid');
  final Map<String, dynamic> catalog;
  final Completer<Map<String, dynamic>>? catalogCompleter;
  final bool noWallet;
  final bool invalidDraft;
  final Completer<Map<String, dynamic>>? keyCompleter;
  final bool keyReady;
  int receiveCalls = 0;
  int balanceCalls = 0;
  int historyCalls = 0;
  int createCalls = 0;
  int draftCalls = 0;
  int keyCalls = 0;
  int broadcastCalls = 0;
  String? lastCreateAsset;
  String? lastCreateNetwork;
  String? lastAmount;

  @override
  Future<Map<String, dynamic>> getCryptoWalletAssetCatalog(
          {required String authToken,
          bool Function()? responseIsCurrent}) async =>
      catalogCompleter?.future ?? catalog;
  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures(
          {required String authToken,
          bool Function()? responseIsCurrent}) async =>
      _features;
  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCalls++;
    return noWallet
        ? {'wallet_engine': 'create_eth_wallet_first'}
        : {
            'wallet_engine': 'receive_ready',
            'publicAddress': '0x1111111111111111111111111111111111111111',
            'network': 'Ethereum Mainnet',
          };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    String? address,
  }) async {
    balanceCalls++;
    return {
      'asset': asset,
      'networkId': network,
      'chainId': 1,
      'decimals': 18,
      'tokenContract': kPaxgContractAddress,
      'publicAddress': address,
      'balanceStatus': 'available',
      'availableAmount': '1.234567890123456789',
      'unit': asset == 'ETH' ? 'ETH' : 'PAXG',
      'baseUnits': '1234567890123456789',
      'weiAmount': '1234567890123456789',
    };
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    historyCalls++;
    return {'transactionsStatus': 'available', 'transactions': <dynamic>[]};
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
    lastCreateAsset = asset;
    lastCreateNetwork = network;
    return {'status': 'created'};
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
  }) async {
    draftCalls++;
    lastAmount = amountEth;
    return {
      ...paxgDraftFixture(amount: amountEth!),
      'status': 'draft_ready',
      'nonce': '0',
      'gasLimit': '60000',
      'gasPrice': '1000000000',
      if (invalidDraft)
        'transactionTo': '0x1111111111111111111111111111111111111111',
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    keyCalls++;
    if (keyCompleter != null) return keyCompleter!.future;
    if (keyReady) {
      return {
        'status': 'encrypted_secret_ready',
        'encryptedWalletSecret': 'synthetic-encrypted-wallet-secret'
      };
    }
    throw StateError('Test must not access or sign a wallet key');
  }

  @override
  Future<Map<String, dynamic>> postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
  }) async =>
      {
        'status': 'fee_estimate_ready',
        'chainId': 1,
        'gasLimit': '60000',
        'gasPriceWei': '1000000000',
        'authorizedMaxFeeBaseUnits': '60000000000000',
        'feeSource': 'synthetic-test-fixture',
      };

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcastCalls++;
    throw StateError('Tests must never broadcast a transaction');
  }
}

Widget _app(Widget child) => MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate
      ],
      supportedLocales: const [Locale('en')],
      home: child,
    );

AssetsPage _page(_Client client, {String token = 'test-session'}) => AssetsPage(
      authToken: token,
      apiClient: client,
      cryptocurrency: Scaffold(
          appBar: AppBar(), body: const Text('Existing cryptocurrency page')),
      encryptForVault: (_) async => 'test-ciphertext',
      isVaultKeyAvailable: () => true,
      decryptForVault: (_) async => 'not-used',
      loadFromAddress: (_) async => null,
    );

Future<void> _pumpPaxgSend(
  WidgetTester tester,
  _Client client, {
  required bool Function() unlocked,
  required Future<String> Function(String) decrypt,
}) async {
  final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
  await tester.pumpWidget(_app(Scaffold(
      body: CryptoWalletEngineSendPanel(
    authToken: 'synthetic-test-session',
    client: client,
    fromAddress: '0x1111111111111111111111111111111111111111',
    asset: kPaxgAssetId,
    network: 'ethereum_mainnet',
    registeredAsset: token,
    mainnetSendEnabled: true,
    decryptForVault: decrypt,
    isVaultKeyAvailable: unlocked,
    verifyPin: (_) async => true,
    fetchAvailableBalance: () async => 1,
    fetchEthBalance: () async => 1,
    fetchAvailableBalanceWei: () async => BigInt.from(1000000000000000000),
    fetchEthBalanceWei: () async => BigInt.from(1000000000000000000),
  ))));
  await tester.pumpAndSettle();
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_destination_input')),
      '0x2222222222222222222222222222222222222222');
  await tester.enterText(find.byKey(const Key('eth_send_panel_amount_input')),
      '0.000000000000000001');
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('eth_send_panel_review_stage')), findsOneWidget);
}

Future<void> _startPaxgPin(WidgetTester tester) async {
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.pumpAndSettle();
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_pin_input')), '123456');
  await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

void main() {
  testWidgets(
      'PAXG Max uses all 18 decimal token units without subtracting ETH gas',
      (tester) async {
    final client = _Client();
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    await tester.pumpWidget(_app(Scaffold(
        body: CryptoWalletEngineSendPanel(
      authToken: 'test',
      client: client,
      fromAddress: '0x1111111111111111111111111111111111111111',
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      registeredAsset: token,
      mainnetSendEnabled: true,
      decryptForVault: (_) async => 'not-used',
      isVaultKeyAvailable: () => true,
      fetchAvailableBalance: () async => 2,
      fetchEthBalance: () async => 1,
      fetchAvailableBalanceWei: () async => BigInt.parse('1234567890123456789'),
      fetchEthBalanceWei: () async => BigInt.from(1000000000000000000),
    ))));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
    await tester.pumpAndSettle();
    final amount = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')));
    expect(amount.controller!.text, '1.234567890123456789');
    expect(client.draftCalls, 0);
    expect(client.keyCalls, 0);
  });

  testWidgets(
      'valid PAXG transfer reaches review with token debit and issuer warning, not a real broadcast',
      (tester) async {
    final client = _Client();
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    await tester.pumpWidget(_app(Scaffold(
        body: CryptoWalletEngineSendPanel(
      authToken: 'test',
      client: client,
      fromAddress: '0x1111111111111111111111111111111111111111',
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      registeredAsset: token,
      mainnetSendEnabled: true,
      decryptForVault: (_) async => 'not-used',
      isVaultKeyAvailable: () => true,
      fetchAvailableBalance: () async => 1,
      fetchEthBalance: () async => 1,
      fetchAvailableBalanceWei: () async => BigInt.from(1000000000000000000),
      fetchEthBalanceWei: () async => BigInt.from(1000000000000000000),
    ))));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        '0x2222222222222222222222222222222222222222');
    await tester.enterText(find.byKey(const Key('eth_send_panel_amount_input')),
        '0.000000000000000001');
    await tester
        .ensureVisible(find.byKey(const Key('eth_send_panel_review_btn')));
    await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
    await tester.pumpAndSettle();
    expect(
        find.byKey(const Key('eth_send_panel_review_stage')), findsOneWidget);
    expect(find.text('0.000000000000000001 PAXG'), findsOneWidget);
    expect(find.byKey(const Key('send_asset_issuer_transfer_note')),
        findsOneWidget);
    expect(client.draftCalls, 1);
    expect(client.keyCalls, 0);
  });

  testWidgets(
      'eight categories preserve Cryptocurrency and unavailable categories have no actions',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(_page(client)));
    await tester.pumpAndSettle();
    expect(find.text('Assets'), findsOneWidget);
    await tester.tap(find.byKey(const Key('assets_category_cryptocurrency')));
    await tester.pumpAndSettle();
    expect(find.text('Existing cryptocurrency page'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester
        .ensureVisible(find.byKey(const Key('assets_category_digital_silver')));
    await tester.tap(find.byKey(const Key('assets_category_digital_silver')));
    await tester.pumpAndSettle();
    expect(find.text('Unavailable'), findsOneWidget);
    expect(find.text('Receive'), findsNothing);
    expect(find.text('Send'), findsNothing);
    expect(client.receiveCalls, 0);
    expect(client.balanceCalls, 0);
  });

  testWidgets(
      'missing verified catalog leaves Digital Gold unavailable with no balance request',
      (tester) async {
    final client = _Client(catalog: {});
    await tester.pumpWidget(_app(_page(client)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('assets_category_digital_gold')));
    await tester.pumpAndSettle();
    expect(find.text('Unavailable'), findsOneWidget);
    expect(client.receiveCalls, 0);
    expect(find.text('0 PAXG'), findsNothing);
  });

  testWidgets(
      'verified Digital Gold shows real precision, network, receive/send and issuer warning',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(_page(client)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('assets_category_digital_gold')));
    await tester.pumpAndSettle();
    expect(find.text('PAX Gold'), findsWidgets);
    expect(find.text('Ethereum Mainnet · ERC20'), findsOneWidget);
    expect(find.text('1.234567890123456789 PAXG'), findsOneWidget);
    expect(find.text('Receive'), findsOneWidget);
    expect(find.text('Send'), findsOneWidget);
    expect(find.byKey(const Key('asset_issuer_transfer_note')), findsOneWidget);
    expect(client.historyCalls, 1);
    expect(client.balanceCalls, greaterThanOrEqualTo(2));
  });

  testWidgets(
      'independent missing Send/history capabilities remain disabled without fake activity',
      (tester) async {
    final client = _Client(
        catalog: catalogFixture(tokenOverrides: {
      'sendEnabled': false,
      'activityConnected': false,
    }));
    await tester.pumpWidget(_app(_page(client)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('assets_category_digital_gold')));
    await tester.pumpAndSettle();
    final button = tester.widget<ElevatedButton>(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
    expect(button.onPressed, isNull);
    expect(find.byKey(const Key('asset_activity_unavailable')), findsOneWidget);
    expect(client.historyCalls, 0);
  });

  testWidgets('late catalog from an older account cannot enable Digital Gold',
      (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final oldClient = _Client(catalogCompleter: pending);
    await tester.pumpWidget(_app(_page(oldClient, token: 'old')));
    await tester.pump();
    final newClient = _Client(catalog: {});
    await tester.pumpWidget(_app(_page(newClient, token: 'new')));
    await tester.pumpAndSettle();
    pending.complete(catalogFixture());
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('assets_category_digital_gold')));
    await tester.pumpAndSettle();
    expect(find.text('Unavailable'), findsOneWidget);
  });

  testWidgets(
      'PAXG receive can create only the parent Ethereum Mainnet encrypted wallet',
      (tester) async {
    final client = _Client(noWallet: true);
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    await tester.pumpWidget(_app(Scaffold(
        body: CryptoWalletEngineReceivePanel(
      authToken: 'test',
      client: client,
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      registeredAsset: token,
      encryptForVault: (_) async => 'ciphertext-only',
      isVaultKeyAvailable: () => true,
    ))));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.pumpAndSettle();
    expect(client.createCalls, 1);
    expect(client.lastCreateAsset, 'ETH');
    expect(client.lastCreateNetwork, 'ethereum_mainnet');
  });

  testWidgets(
      'PAXG without catalog metadata cannot load an address or enable signing',
      (tester) async {
    final client = _Client();
    await tester.pumpWidget(_app(CryptoWalletEngineAssetDetailPage(
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      authToken: 'test',
      apiClient: client,
      encryptForVault: (_) async => 'cipher',
      isVaultKeyAvailable: () => true,
      features: CryptoWalletFeatures.fromBackend(_features),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Unavailable'), findsWidgets);
    expect(client.receiveCalls, 0);
    expect(find.text('Send'), findsNothing);
  });

  testWidgets(
      'PAXG send accepts 18 decimals but rejects a replaced contract before key access',
      (tester) async {
    final client = _Client(invalidDraft: true);
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    await tester.pumpWidget(_app(Scaffold(
        body: CryptoWalletEngineSendPanel(
      authToken: 'test',
      client: client,
      fromAddress: '0x1111111111111111111111111111111111111111',
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      registeredAsset: token,
      mainnetSendEnabled: true,
      decryptForVault: (_) async => 'not-used',
      isVaultKeyAvailable: () => true,
      fetchAvailableBalance: () async => 1,
      fetchEthBalance: () async => 1,
      fetchAvailableBalanceWei: () async => BigInt.from(1000000000000000000),
      fetchEthBalanceWei: () async => BigInt.from(1000000000000000000),
    ))));
    await tester.pumpAndSettle();
    expect(find.text('Amount (PAXG)'), findsOneWidget);
    await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        '0x2222222222222222222222222222222222222222');
    await tester.enterText(find.byKey(const Key('eth_send_panel_amount_input')),
        '0.000000000000000001');
    await tester
        .ensureVisible(find.byKey(const Key('eth_send_panel_review_btn')));
    await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
    await tester.pumpAndSettle();
    expect(client.lastAmount, '0.000000000000000001');
    expect(client.draftCalls, 1);
    expect(client.keyCalls, 0);
    expect(find.textContaining('No transaction was signed'), findsOneWidget);
  });

  testWidgets(
      'PAXG receive never creates a wallet after lock during encryption',
      (tester) async {
    final client = _Client(noWallet: true);
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    final encrypted = Completer<String>();
    var unlocked = true;
    var encryptCalls = 0;
    await tester.pumpWidget(_app(Scaffold(
        body: CryptoWalletEngineReceivePanel(
      authToken: 'synthetic-test-session',
      client: client,
      asset: kPaxgAssetId,
      network: 'ethereum_mainnet',
      registeredAsset: token,
      encryptForVault: (_) {
        encryptCalls++;
        return encrypted.future;
      },
      isVaultKeyAvailable: () => unlocked,
    ))));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.pump();
    expect(encryptCalls, 1);
    unlocked = false;
    encrypted.complete('synthetic-ciphertext-for-old-session');
    await tester.pumpAndSettle();
    expect(client.createCalls, 0);
    expect(find.text(kEthReceiveCreateBlockedNoVaultKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'PAXG lock while fetching a key prevents decryption and broadcast',
      (tester) async {
    final keyResponse = Completer<Map<String, dynamic>>();
    final client = _Client(keyCompleter: keyResponse);
    var unlocked = true;
    var decryptCalls = 0;
    await _pumpPaxgSend(tester, client,
        unlocked: () => unlocked,
        decrypt: (_) async {
          decryptCalls++;
          throw StateError('Locked transaction must not decrypt a wallet key');
        });
    await _startPaxgPin(tester);
    expect(client.keyCalls, 1);
    unlocked = false;
    keyResponse.complete({
      'status': 'encrypted_secret_ready',
      'encryptedWalletSecret': 'synthetic-ciphertext-for-old-session',
    });
    await tester.pumpAndSettle();
    expect(decryptCalls, 0);
    expect(client.broadcastCalls, 0);
    expect(find.text(kEthSendErrorSigningKeyUnavailable), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('PAXG lock during decryption discards key before local signing',
      (tester) async {
    final client = _Client(keyReady: true);
    final plaintext = Completer<String>();
    var unlocked = true;
    var decryptCalls = 0;
    await _pumpPaxgSend(tester, client,
        unlocked: () => unlocked,
        decrypt: (_) {
          decryptCalls++;
          return plaintext.future;
        });
    await _startPaxgPin(tester);
    expect(client.keyCalls, 1);
    expect(decryptCalls, 1);
    unlocked = false;
    // Deliberately invalid: if this reaches the real local signer, its separate
    // local-signing failure would make the required locked-session assertion
    // fail. No usable private key or signed transaction exists in this test.
    plaintext.complete('invalid-key-must-never-reach-local-signer');
    await tester.pumpAndSettle();
    expect(client.broadcastCalls, 0);
    expect(find.text(kEthSendErrorSigningKeyUnavailable), findsOneWidget);
    expect(find.text(kEthSendErrorLocalSigningFailed), findsNothing);
    expect(tester.takeException(), isNull);
  });

  for (final path in [
    '/crypto/wallet/asset-catalog',
    '/crypto/wallet/features'
  ]) {
    testWidgets('late coded 401 from old Assets $path cannot end a newer vault',
        (tester) async {
      final termination = SessionTermination.instance..reset();
      var terminations = 0;
      termination.setHandler((_) async => terminations++);
      addTearDown(() {
        termination.reset();
        termination.setHandler((_) async {});
      });
      final oldResponse = Completer<http.Response>();
      var delayedCalls = 0;
      final client = VaultAIClient(baseUrl: 'https://synthetic.invalid');
      AssetsPage page(String token) => AssetsPage(
          authToken: token,
          apiClient: client,
          isVaultKeyAvailable: () => true,
          cryptocurrency:
              const Scaffold(body: Text('Existing cryptocurrency')));
      await http.runWithClient(() async {
        await tester.pumpWidget(_app(page('old-synthetic-session')));
        await tester.pump();
        expect(delayedCalls, 1);
        await tester.pumpWidget(_app(page('new-synthetic-session')));
        await tester.pumpAndSettle();
        oldResponse.complete(http.Response(
            jsonEncode({
              'detail': {'code': 'session_superseded'}
            }),
            401));
        await tester.pumpAndSettle();
        expect(terminations, 0);
        expect(termination.isTerminated, isFalse);
        expect(find.byType(AssetsPage), findsOneWidget);
        await tester.tap(find.byKey(const Key('assets_category_digital_gold')));
        await tester.pumpAndSettle();
        expect(find.text('Unavailable'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
          () => MockClient((request) async {
                expect(request.url.host, 'synthetic.invalid');
                if (request.headers['Authorization'] ==
                        'Bearer old-synthetic-session' &&
                    request.url.path == path) {
                  delayedCalls++;
                  return oldResponse.future;
                }
                final body = request.url.path == '/crypto/wallet/features'
                    ? _features
                    : <String, dynamic>{};
                return http.Response(jsonEncode(body), 200);
              }));
    });
  }
}
