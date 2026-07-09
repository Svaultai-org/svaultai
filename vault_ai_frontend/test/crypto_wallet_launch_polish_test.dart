


import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_readiness_panel.dart';


class _ReadinessSpyClient extends VaultAIClient {
  Map<String, dynamic> nextFeatures = const {};
  Map<String, dynamic>? nextDiagnosis;
  Object? diagnosisError;
  int featuresCallCount = 0;
  int diagnosisCallCount = 0;

  _ReadinessSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
  }) async {
    featuresCallCount += 1;
    return nextFeatures;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletDiagnosis({
    required String authToken,
    String? adminToken,
  }) async {
    diagnosisCallCount += 1;
    if (diagnosisError != null) throw diagnosisError!;
    if (nextDiagnosis == null) {
      throw Exception('diagnosis not set');
    }
    return nextDiagnosis!;
  }
}


Map<String, dynamic> _fullyReadyDiagnosis() {
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
        'asset': 'ETH',
        'displayName': 'Ethereum Mainnet',
        'network': 'ethereum_mainnet',
        'featureEnabled': true,
        'featureFlagEnvVar': 'VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED',
        'rpcConfigured': true,
        'rpcEnvVar': 'ETHEREUM_MAINNET_RPC_URL',
        'tokenContractRequired': false,
        'tokenContractConfigured': true,
        'tokenContractEnvVar': '',
        'balanceRouteReady': true,
        'lastBalanceReason': 'ready',
      },
      {
        'rowId': 'ethereum_mainnet_usdt_erc20',
        'asset': 'USDT_ERC20',
        'displayName': 'USDT (ERC20)',
        'featureEnabled': true,
        'rpcConfigured': true,
        'rpcEnvVar': 'ETHEREUM_MAINNET_RPC_URL',
        'tokenContractRequired': true,
        'tokenContractConfigured': true,
        'tokenContractEnvVar': 'ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS',
        'balanceRouteReady': true,
        'lastBalanceReason': 'ready',
      },
      {
        'rowId': 'ethereum_mainnet_usdc_erc20',
        'asset': 'USDC_ERC20',
        'featureEnabled': true,
        'rpcConfigured': true,
        'tokenContractRequired': true,
        'tokenContractConfigured': true,
        'tokenContractEnvVar': 'ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS',
        'balanceRouteReady': true,
        'lastBalanceReason': 'ready',
      },
      {
        'rowId': 'solana_mainnet_sol',
        'asset': 'SOL',
        'featureEnabled': true,
        'rpcConfigured': true,
        'rpcEnvVar': 'SOLANA_RPC_URL',
        'balanceRouteReady': true,
        'lastBalanceReason': 'ready',
      },
      {
        'rowId': 'tron_mainnet_usdt_trc20',
        'asset': 'USDT_TRC20',
        'featureEnabled': true,
        'rpcConfigured': true,
        'rpcEnvVar': 'TRON_API_BASE_URL',
        'tokenContractRequired': true,
        'tokenContractConfigured': true,
        'tokenContractEnvVar': 'TRON_USDT_CONTRACT_ADDRESS',
        'balanceRouteReady': true,
        'lastBalanceReason': 'ready',
      },
      {
        'rowId': 'monero_mainnet_xmr',
        'asset': 'XMR',
        'featureEnabled': true,
        'rpcConfigured': false,
        'scannerMode': 'none',
        'walletGenerationStatus': 'client_side_ready',
        'xmrClientScannerSupported': false,
        'xmrBackendScannerEnabled': false,
        'xmrBalanceReason': 'xmr_scanner_client_required',
        'balanceRouteReady': false,
        'lastBalanceReason': 'xmr_scanner_client_required',
      },
    ],
  };
}


Map<String, dynamic> _fullyReadyFeatures() {
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


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


void main() {

  group('ReadinessPanel — happy path', () {

    testWidgets('renders all six asset rows with a READY badge',
        (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client,
          authToken: 'tok',
          adminToken: 'admin',
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kReadinessPanelKey)),
        findsOneWidget,
      );
      for (final cfg in kReadinessDisplayOrder) {
        expect(
          find.byKey(Key('$kReadinessPanelRowKeyPrefix${cfg.rowId}')),
          findsOneWidget,
          reason: 'must render row ${cfg.rowId}',
        );
      }
    });

    testWidgets('renders "5 of 6 assets ready" summary chip',
        (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client,
          authToken: 'tok',
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('5 of 6 assets ready'), findsOneWidget);
    });

    testWidgets(
      'refresh button re-calls features + diagnosis',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyReadyFeatures();
        client.nextDiagnosis = _fullyReadyDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client,
            authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        final beforeF = client.featuresCallCount;
        final beforeD = client.diagnosisCallCount;
        await tester.tap(
          find.byKey(const Key(kReadinessPanelRefreshBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.featuresCallCount, greaterThan(beforeF));
        expect(client.diagnosisCallCount, greaterThan(beforeD));
      },
    );

    testWidgets(
      'renders secret-safe attestation footer text',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyReadyFeatures();
        client.nextDiagnosis = _fullyReadyDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.text(kReadinessPanelSecretSafeAttestation),
          findsOneWidget,
        );
      },
    );
  });


  group('ReadinessPanel — 403 forbidden', () {
    testWidgets(
      'when diagnosis returns 403, the panel shows the honest forbidden line',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyReadyFeatures();
        client.diagnosisError = Exception('403 forbidden');
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client,
            authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(kReadinessPanelErrorKey)),
          findsOneWidget,
        );
        expect(
          find.text(kReadinessPanelForbiddenLabel),
          findsOneWidget,
        );
      },
    );
  });


  group('ReadinessPanel — never renders raw secrets', () {

    testWidgets('never renders raw RPC URL string', (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok', adminToken: 'admin',
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('https://'), findsNothing);
      expect(find.textContaining('mainnet-rpc'), findsNothing);
    });

    testWidgets('never renders a raw contract address hex', (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok', adminToken: 'admin',
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('0xdAC17F958D2ee523a2206206994597C13D831ec7'),
        findsNothing,
      );
      expect(find.textContaining('TXLAQ63Xg1NAzck'), findsNothing);
    });

    testWidgets('never renders a raw private-key or seed identifier',
        (tester) async {
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok', adminToken: 'admin',
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('privateSpendKey'), findsNothing);
      expect(find.textContaining('privateViewKey'), findsNothing);
      expect(find.textContaining('mnemonic'), findsNothing);
      expect(find.textContaining('encryptedWalletSecret'), findsNothing);
    });
  });


  group('ReadinessPanel — partial config', () {

    testWidgets(
      'when ETH RPC missing, the ETH row shows the honest reason',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyReadyFeatures();
        final diag = _fullyReadyDiagnosis();
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
        expect(
          find.byKey(const Key(
            'crypto_wallet_readiness_reason_ethereum_mainnet_eth',
          )),
          findsOneWidget,
        );
        expect(
          find.textContaining('rpc_not_configured'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'XMR always renders as NOT READY (client scanner required)',
      (tester) async {
        final client = _ReadinessSpyClient();
        client.nextFeatures = _fullyReadyFeatures();
        client.nextDiagnosis = _fullyReadyDiagnosis();
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineReadinessPanel(
            client: client, authToken: 'tok',
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.text('xmr_scanner_client_required'),
          findsOneWidget,
        );
      },
    );
  });


  group('ReadinessPanel — mobile layout', () {
    testWidgets('renders without overflow at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok',
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders without overflow at 420 x 800',
        (tester) async {
      tester.view.physicalSize = const Size(420, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final client = _ReadinessSpyClient();
      client.nextFeatures = _fullyReadyFeatures();
      client.nextDiagnosis = _fullyReadyDiagnosis();
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineReadinessPanel(
          client: client, authToken: 'tok',
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });


  group('Copy polish — main page never uses exchange language', () {

    test('Portfolio heading is renamed to "Vault balance"', () {
      expect(kCryptoWalletEnginePortfolioHeading, 'Vault balance');
    });

    test('Assets heading is renamed to "Stored assets"', () {
      expect(kCryptoWalletEngineAssetsHeading, 'Stored assets');
    });

    test('Activity heading is renamed to "Vault activity"', () {
      expect(kCryptoWalletEngineActivityHeading, 'Vault activity');
    });

    test('no exchange verbs appear in crypto wallet engine copy', () {
      const forbiddenWithSpaces = [
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ', ' bridge ',
        ' exchange ', ' market ', ' portfolio ',
      ];
      for (final copy in const [
        kCryptoWalletEngineHeading,
        kCryptoWalletEngineSubheading,
        kCryptoWalletEnginePortfolioHeading,
        kCryptoWalletEnginePortfolioNoWalletsBody,
        kCryptoWalletEnginePortfolioHonestSubcopy,
        kCryptoWalletEnginePortfolioBalancesUnavailable,
        kCryptoWalletEngineAssetsHeading,
        kCryptoWalletEngineActivityHeading,
        kCryptoWalletEngineActivityHonestEmpty,
        kCryptoWalletEnginePortfolioLiveBalancesNoteMainnet,
        kCryptoWalletEnginePortfolioLiveBalancesNoteSepolia,
        kCryptoWalletEnginePortfolioActivityNote,
      ]) {
        for (final v in forbiddenWithSpaces) {
          expect(
            ' ${copy.toLowerCase()} ', isNot(contains(v)),
            reason: 'copy must not use "$v" as a verb: $copy',
          );
        }
      }
    });

    test(
      'readiness panel copy uses vault language, not exchange language',
      () {
        const forbiddenWithSpaces = [
          ' buy ', ' sell ', ' swap ', ' trade ', ' stake ', ' bridge ',
          ' exchange ', ' market ',
        ];
        for (final copy in const [
          kReadinessPanelTitle,
          kReadinessPanelSubtitle,
          kReadinessPanelLoadingLabel,
          kReadinessPanelForbiddenLabel,
          kReadinessPanelUnknownErrorLabel,
          kReadinessPanelSecretSafeAttestation,
        ]) {
          for (final v in forbiddenWithSpaces) {
            expect(
              ' ${copy.toLowerCase()} ', isNot(contains(v)),
              reason: 'copy must not use "$v": $copy',
            );
          }
        }
      },
    );
  });
}
