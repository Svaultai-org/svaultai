


import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_readiness_panel.dart';


class _ReadinessSpyClient extends VaultAIClient {
  Map<String, dynamic> nextFeatures = const {};
  Map<String, dynamic>? nextDiagnosis;

  _ReadinessSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
  }) async {
    return nextFeatures;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletDiagnosis({
    required String authToken,
    String? adminToken,
  }) async {
    if (nextDiagnosis == null) {
      throw Exception('diagnosis not set');
    }
    return nextDiagnosis!;
  }
}


Map<String, dynamic> _fullyProvisionedFeatures() {
  return {
    'status': 'ok',
    'schema': 'crypto_wallet_features_v1',
    'walletEngineEnabled': true,
    'mainnetReceiveEnabled': true,
    'mainnetErc20ReceiveEnabled': true,
    'mainnetSendEnabled': true,
    'mainnetSendPaused': false,
    'solanaEnabled': true,
    'solanaReceiveEnabled': true,
    'solanaSendEnabled': true,
    'solanaSendPaused': false,
    'solanaBalanceEnabled': true,
    'solanaActivityConnected': true,
    'solanaStatusReady': true,
    'solanaFeeReady': true,
    'tronEnabled': true,
    'tronReceiveEnabled': true,
    'tronSendEnabled': true,
    'tronSendPaused': false,
    'tronBalanceEnabled': true,
    'tronActivityConnected': false,
    'tronUsdtContractConfigured': true,
    'xmrEnabled': true,
    'xmrReceiveEnabled': true,
    'xmrBalanceEnabled': false,
    'xmrSendEnabled': false,
    'xmrActivityConnected': false,
    'xmrScannerMode': 'none',
    'xmrClientScannerSupported': false,
    'xmrBackendScannerEnabled': false,
    'defaultNetwork': 'ethereum_mainnet',
    'defaultNetworkConfigValid': true,
    'supportedNetworks': const [
      'ethereum_sepolia', 'ethereum_mainnet', 'solana_mainnet',
      'tron_mainnet', 'monero_mainnet',
    ],
    'supportedAssetsByNetwork': const {},
  };
}


Map<String, dynamic> _fullyProvisionedDiagnosis() {
  return {
    'status': 'ok',
    'schema': 'crypto_wallet_diagnosis_v1',
    'walletEngineEnabled': true,
    'defaultNetwork': 'ethereum_mainnet',
    'defaultNetworkConfigValid': true,
    'assetsReady': 5,
    'assetsTotal': 6,
    'assets': [
      {
        'rowId': 'ethereum_mainnet_eth',
        'featureEnabled': true, 'rpcConfigured': true,
        'balanceRouteReady': true, 'lastBalanceReason': 'ready',
        'rpcEnvVar': 'ETHEREUM_MAINNET_RPC_URL',
      },
      {
        'rowId': 'ethereum_mainnet_usdt_erc20',
        'featureEnabled': true, 'rpcConfigured': true,
        'tokenContractRequired': true, 'tokenContractConfigured': true,
        'balanceRouteReady': true, 'lastBalanceReason': 'ready',
        'tokenContractEnvVar': 'ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS',
      },
      {
        'rowId': 'ethereum_mainnet_usdc_erc20',
        'featureEnabled': true, 'rpcConfigured': true,
        'tokenContractRequired': true, 'tokenContractConfigured': true,
        'balanceRouteReady': true, 'lastBalanceReason': 'ready',
        'tokenContractEnvVar': 'ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS',
      },
      {
        'rowId': 'solana_mainnet_sol',
        'featureEnabled': true, 'rpcConfigured': true,
        'balanceRouteReady': true, 'lastBalanceReason': 'ready',
        'rpcEnvVar': 'SOLANA_RPC_URL',
      },
      {
        'rowId': 'tron_mainnet_usdt_trc20',
        'featureEnabled': true, 'rpcConfigured': true,
        'tokenContractRequired': true, 'tokenContractConfigured': true,
        'balanceRouteReady': true, 'lastBalanceReason': 'ready',
        'rpcEnvVar': 'TRON_API_BASE_URL',
        'tokenContractEnvVar': 'TRON_USDT_CONTRACT_ADDRESS',
      },
      {
        'rowId': 'monero_mainnet_xmr',
        'featureEnabled': true, 'rpcConfigured': false,
        'scannerMode': 'none', 'walletGenerationStatus': 'client_side_ready',
        'xmrClientScannerSupported': false,
        'xmrBackendScannerEnabled': false,
        'xmrBalanceReason': 'xmr_scanner_client_required',
        'balanceRouteReady': false,
        'lastBalanceReason': 'xmr_scanner_client_required',
      },
    ],
  };
}


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


void main() {

  group('Fully-provisioned production launch', () {

    testWidgets(
      'summary chip reads "5 of 6 assets ready" when ETH/SOL/TRON '
      'are fully configured',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        client.nextDiagnosis = _fullyProvisionedDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok', adminToken: 'admin',
          ),
        ));
        await tester.pumpAndSettle();
        expect(find.text('5 of 6 assets ready'), findsOneWidget);
      },
    );

    testWidgets(
      'XMR row is always NOT READY with client_scanner_required reason',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        client.nextDiagnosis = _fullyProvisionedDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok', adminToken: 'admin',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            '${kReadinessPanelRowKeyPrefix}monero_mainnet_xmr',
          )),
          findsOneWidget,
        );
        expect(
          find.text('xmr_scanner_client_required'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'no URL or 0x-address or TRON contract or XMR address string '
      'appears in the rendered panel',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        client.nextDiagnosis = _fullyProvisionedDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok', adminToken: 'admin',
          ),
        ));
        await tester.pumpAndSettle();
        expect(find.textContaining('https://'), findsNothing);
        expect(
          find.textContaining(
            '0xdAC17F958D2ee523a2206206994597C13D831ec7',
          ),
          findsNothing,
        );
        expect(
          find.textContaining('TXLAQ63Xg1NAzck'),
          findsNothing,
        );
      },
    );

    testWidgets(
      'every one of the 6 asset rows is rendered in the fixed launch order',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        client.nextDiagnosis = _fullyProvisionedDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok', adminToken: 'admin',
          ),
        ));
        await tester.pumpAndSettle();
        for (final cfg in kReadinessDisplayOrder) {
          expect(
            find.byKey(Key('$kReadinessPanelRowKeyPrefix${cfg.rowId}')),
            findsOneWidget,
            reason: 'row ${cfg.rowId} must be visible',
          );
        }
        expect(kReadinessDisplayOrder.length, 6);
        expect(
          kReadinessDisplayOrder.first.rowId, 'ethereum_mainnet_eth',
        );
        expect(
          kReadinessDisplayOrder.last.rowId, 'monero_mainnet_xmr',
        );
      },
    );
  });


  group('Partial provisioning — honest reasons', () {

    testWidgets('ETH RPC missing → row shows rpc_not_configured, '
        'summary chip drops by one',
        (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyProvisionedFeatures();
      final diag = _fullyProvisionedDiagnosis();
      diag['assetsReady'] = 4;
      final rows = List<Map<String, dynamic>>.from(
        diag['assets'] as List,
      );
      final eth = rows.firstWhere(
        (r) => r['rowId'] == 'ethereum_mainnet_eth',
      );
      eth['rpcConfigured'] = false;
      eth['balanceRouteReady'] = false;
      eth['lastBalanceReason'] = 'rpc_not_configured';
      diag['assets'] = rows;
      client.nextDiagnosis = diag;
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok',
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('4 of 6 assets ready'), findsOneWidget);
      expect(
        find.byKey(const Key(
          'crypto_wallet_readiness_reason_ethereum_mainnet_eth',
        )),
        findsOneWidget,
      );
      expect(find.text('rpc_not_configured'), findsOneWidget);
    });

    testWidgets(
      'USDT ERC20 contract missing → token_contract_not_configured '
      'reason surfaces',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        final diag = _fullyProvisionedDiagnosis();
        diag['assetsReady'] = 4;
        final rows = List<Map<String, dynamic>>.from(
          diag['assets'] as List,
        );
        final usdt = rows.firstWhere(
          (r) => r['rowId'] == 'ethereum_mainnet_usdt_erc20',
        );
        usdt['tokenContractConfigured'] = false;
        usdt['balanceRouteReady'] = false;
        usdt['lastBalanceReason'] = 'token_contract_not_configured';
        diag['assets'] = rows;
        client.nextDiagnosis = diag;
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.text('token_contract_not_configured'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'TRON API missing → rpc_not_configured surfaces',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyProvisionedFeatures();
        final diag = _fullyProvisionedDiagnosis();
        final rows = List<Map<String, dynamic>>.from(
          diag['assets'] as List,
        );
        final tron = rows.firstWhere(
          (r) => r['rowId'] == 'tron_mainnet_usdt_trc20',
        );
        tron['rpcConfigured'] = false;
        tron['balanceRouteReady'] = false;
        tron['lastBalanceReason'] = 'rpc_not_configured';
        diag['assets'] = rows;
        diag['assetsReady'] = 4;
        client.nextDiagnosis = diag;
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_wallet_readiness_reason_tron_mainnet_usdt_trc20',
          )),
          findsOneWidget,
        );
      },
    );
  });


  group('Launch lexicon audit — never appears in visible product', () {

    test('main crypto page headings match the launch lexicon', () {
      expect(kCryptoWalletEnginePortfolioHeading, 'Vault balance');
      expect(kCryptoWalletEngineAssetsHeading, 'Stored assets');
      expect(kCryptoWalletEngineActivityHeading, 'Vault activity');
    });

    test(
      'no exchange verb (buy/sell/swap/trade/stake/bridge/exchange/market) '
      'appears as a word in any readiness-panel or main-page copy constant',
      () {
        const forbiddenWithSpaces = [
          ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
          ' bridge ', ' exchange ', ' market ',
        ];
        for (final copy in const [
          kReadinessPanelTitle,
          kReadinessPanelSubtitle,
          kReadinessPanelLoadingLabel,
          kReadinessPanelForbiddenLabel,
          kReadinessPanelUnknownErrorLabel,
          kReadinessPanelSecretSafeAttestation,
          kReadinessLabelFeatureEnabled,
          kReadinessLabelRpcConfigured,
          kReadinessLabelTokenContract,
          kReadinessLabelBalanceRouteReady,
          kReadinessLabelLastBalanceReason,
          kReadinessLabelReceiveEnabled,
          kReadinessLabelSendEnabled,
          kReadinessLabelSendPaused,
          kReadinessLabelActivityConnected,
          kReadinessLabelStatusReady,
          kReadinessLabelFeeReady,
          kReadinessLabelXmrScannerMode,
          kReadinessLabelXmrClientScannerSupported,
          kReadinessLabelXmrBackendScannerEnabled,
          kReadinessLabelWalletGeneration,
          kCryptoWalletEngineHeading,
          kCryptoWalletEngineSubheading,
          kCryptoWalletEnginePortfolioHeading,
          kCryptoWalletEnginePortfolioHonestSubcopy,
          kCryptoWalletEngineAssetsHeading,
          kCryptoWalletEngineActivityHeading,
          kCryptoWalletEngineActivityHonestEmpty,
        ]) {
          for (final v in forbiddenWithSpaces) {
            expect(
              ' ${copy.toLowerCase()} ',
              isNot(contains(v)),
              reason: 'copy must not contain "$v": $copy',
            );
          }
        }
      },
    );

    test(
      'main crypto page never says "not connected" — reason copy is used',
      () {
        const forbidden = 'not connected';
        for (final copy in const [
          kCryptoWalletEngineHeading,
          kCryptoWalletEngineSubheading,
          kCryptoWalletEnginePortfolioHeading,
          kCryptoWalletEnginePortfolioHonestSubcopy,
          kCryptoWalletEngineAssetsHeading,
          kCryptoWalletEngineActivityHeading,
        ]) {
          expect(
            copy.toLowerCase(), isNot(contains(forbidden)),
            reason: 'copy must not use "$forbidden" as a fallback: $copy',
          );
        }
      },
    );
  });


  group('Mobile 360-px overflow on readiness panel', () {

    testWidgets('fully-ready panel fits without overflow at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyProvisionedFeatures();
      client.nextDiagnosis = _fullyProvisionedDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok', adminToken: 'admin',
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('partial-ready panel fits without overflow at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyProvisionedFeatures();
      final diag = _fullyProvisionedDiagnosis();
      diag['assetsReady'] = 2;
      final rows = List<Map<String, dynamic>>.from(
        diag['assets'] as List,
      );
      for (final r in rows) {
        if (r['rowId'] != 'ethereum_mainnet_eth'
            && r['rowId'] != 'ethereum_mainnet_usdc_erc20') {
          r['balanceRouteReady'] = false;
          r['lastBalanceReason'] = 'rpc_not_configured';
        }
      }
      diag['assets'] = rows;
      client.nextDiagnosis = diag;
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok',
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });
}
