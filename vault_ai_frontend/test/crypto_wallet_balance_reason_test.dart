


import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_balance_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';


class _BalanceSpyClient extends VaultAIClient {
  Map<String, dynamic> nextReceiveResponse = const {};
  Map<String, dynamic> nextBalanceResponse = const {};
  int balanceCallCount = 0;
  int receiveCallCount = 0;

  _BalanceSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCallCount += 1;
    return nextReceiveResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceCallCount += 1;
    return nextBalanceResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    receiveCallCount += 1;
    return nextReceiveResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalance({
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceCallCount += 1;
    return nextBalanceResponse;
  }
}


CryptoWalletFeatures _featuresAllOff() {
  return CryptoWalletFeatures.fromBackend({
    'walletEngineEnabled':       true,
    'sepoliaReceiveEnabled':     true,
    'sepoliaSendEnabled':        true,
    'mainnetReceiveEnabled':     false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':        false,
    'mainnetSendPaused':         false,
    'defaultNetwork':            'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'solanaEnabled':             false,
    'solanaReceiveEnabled':      false,
    'solanaBalanceEnabled':      false,
    'solanaSendEnabled':         false,
    'solanaSendPaused':          false,
    'solanaActivityConnected':   false,
    'solanaStatusReady':         false,
    'solanaFeeReady':            false,
    'tronEnabled':               false,
    'tronReceiveEnabled':        false,
    'tronBalanceEnabled':        false,
    'tronSendEnabled':           false,
    'tronSendPaused':            false,
    'tronActivityConnected':     false,
    'tronUsdtContractConfigured': false,
    'xmrEnabled':                false,
    'xmrReceiveEnabled':         false,
    'xmrBalanceEnabled':         false,
    'xmrSendEnabled':            false,
    'xmrActivityConnected':      false,
    'xmrScannerMode':            'none',
    'supportedNetworks':         const ['ethereum_sepolia'],
    'supportedAssetsByNetwork':  const {},
  });
}


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


Future<void> _buildDetail(
  WidgetTester tester,
  _BalanceSpyClient client,
  String asset, {
  String? network,
  CryptoWalletFeatures? features,
}) async {
  await tester.pumpWidget(_wrap(
    CryptoWalletEngineAssetDetailPage(
      asset: asset,
      authToken: 'test-token',
      apiClient: client,
      encryptForVault: (s) async => s,
      isVaultKeyAvailable: () => true,
      network: network,
      features: features ?? _featuresAllOff(),
    ),
  ));
  await tester.pumpAndSettle();
}


void main() {
  group('WalletBalanceReasonRender', () {

    test('no_wallet_yet maps to create-wallet copy', () {
      final r = walletBalanceReasonRender(
        reason: 'no_wallet_yet',
        asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyNoWallet);
      expect(r.bodyKey, kWalletBalanceReasonKeyNoWallet);
    });

    test('rpc_not_configured Ethereum copy is Ethereum-specific', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured',
        asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyRpcMissingEthereum);
    });

    test('rpc_not_configured Solana copy is Solana-specific', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured',
        asset: 'SOL',
        networkKind: WalletNetworkKind.solana,
      );
      expect(r.message, kWalletBalanceCopyRpcMissingSolana);
    });

    test('rpc_not_configured TRON copy is TRON-specific', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured',
        asset: 'USDT_TRC20',
        networkKind: WalletNetworkKind.tron,
      );
      expect(r.message, kWalletBalanceCopyRpcMissingTron);
    });

    test('rpc_not_configured Monero uses scanner-not-enabled copy', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured',
        asset: 'XMR',
        networkKind: WalletNetworkKind.monero,
      );
      expect(r.message, kWalletBalanceCopyRpcMissingMonero);
      expect(r.bodyKey, kWalletBalanceReasonKeyXmrScanner);
    });

    test('token_contract_not_configured maps to token contract copy', () {
      final r = walletBalanceReasonRender(
        reason: 'token_contract_not_configured',
        asset: 'USDT_ERC20',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyTokenContractMissing);
    });

    test('rpc_unreachable maps to Balance temporarily unavailable', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_unreachable',
        asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyRpcError);
    });

    test('contract_read_failed maps to Balance temporarily unavailable', () {
      final r = walletBalanceReasonRender(
        reason: 'contract_read_failed',
        asset: 'USDT_ERC20',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyRpcError);
    });

    test('feature_disabled maps to This asset is not enabled yet', () {
      final r = walletBalanceReasonRender(
        reason: 'feature_disabled',
        asset: 'SOL',
        networkKind: WalletNetworkKind.solana,
      );
      expect(r.message, kWalletBalanceCopyFeatureDisabled);
    });

    test('network_not_enabled also maps to feature-disabled copy', () {
      final r = walletBalanceReasonRender(
        reason: 'network_not_enabled',
        asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyFeatureDisabled);
    });

    test('xmr_scanner_not_enabled maps to Monero scanner copy', () {
      final r = walletBalanceReasonRender(
        reason: 'xmr_scanner_not_enabled',
        asset: 'XMR',
        networkKind: WalletNetworkKind.monero,
      );
      expect(r.message, kWalletBalanceCopyXmrScanner);
    });

    test('unknown reason falls back to Balance temporarily unavailable', () {
      final r = walletBalanceReasonRender(
        reason: 'something_the_backend_added_later',
        asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyRpcError);
    });

    test('walletBalanceRealZeroCopy uses the correct ticker per asset', () {
      expect(walletBalanceRealZeroCopy('ETH'), '0 ETH');
      expect(walletBalanceRealZeroCopy('SOL'), '0 SOL');
      expect(walletBalanceRealZeroCopy('USDT_ERC20'), '0 USDT');
      expect(walletBalanceRealZeroCopy('USDC_ERC20'), '0 USDC');
      expect(walletBalanceRealZeroCopy('USDT_TRC20'), '0 USDT');
      expect(walletBalanceRealZeroCopy('XMR'), '0 XMR');
    });

    test('unknown network kind for rpc_not_configured is honest', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured',
        asset: 'ETH',
        networkKind: WalletNetworkKind.unknown,
      );
      expect(r.message, kWalletBalanceCopyRpcError);
    });
  });


  group('WalletNetworkKind resolution', () {
    test('Ethereum assets map to WalletNetworkKind.ethereum', () {
      expect(
        walletNetworkKindFor(asset: 'ETH', network: null),
        WalletNetworkKind.ethereum,
      );
      expect(
        walletNetworkKindFor(asset: 'USDT_ERC20', network: null),
        WalletNetworkKind.ethereum,
      );
      expect(
        walletNetworkKindFor(asset: 'USDC_ERC20', network: null),
        WalletNetworkKind.ethereum,
      );
    });

    test('SOL maps to WalletNetworkKind.solana', () {
      expect(
        walletNetworkKindFor(asset: 'SOL', network: null),
        WalletNetworkKind.solana,
      );
    });

    test('USDT_TRC20 maps to WalletNetworkKind.tron', () {
      expect(
        walletNetworkKindFor(asset: 'USDT_TRC20', network: null),
        WalletNetworkKind.tron,
      );
    });

    test('XMR maps to WalletNetworkKind.monero', () {
      expect(
        walletNetworkKindFor(asset: 'XMR', network: null),
        WalletNetworkKind.monero,
      );
    });
  });


  group('CryptoWalletEngineAssetDetailPage balance card', () {

    testWidgets('renders no-wallet reason when receive returns no address',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'no_account',
        'publicAddress': '',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'no_wallet_yet',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_sepolia');
      expect(
        find.byKey(const Key(kWalletBalanceReasonKeyNoWallet)),
        findsOneWidget,
      );
      expect(find.text(kWalletBalanceCopyNoWallet), findsOneWidget);
      expect(client.balanceCallCount, 0);
    });

    testWidgets('renders Ethereum RPC missing copy when RPC not configured',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_not_configured',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(
        find.byKey(const Key(kWalletBalanceReasonKeyRpcMissing)),
        findsOneWidget,
      );
      expect(find.text(kWalletBalanceCopyRpcMissingEthereum), findsOneWidget);
    });

    testWidgets(
      'renders Solana RPC missing copy on SOL rpc_not_configured',
      (tester) async {
        final client = _BalanceSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress': 'SoLReceiveExamplePublicKey1234567890abcdefg',
        };
        client.nextBalanceResponse = {
          'balanceStatus': 'unavailable',
          'reason': 'rpc_not_configured',
        };
        await _buildDetail(tester, client, 'SOL',
            network: 'solana_mainnet');
        expect(find.text(kWalletBalanceCopyRpcMissingSolana), findsOneWidget);
      },
    );

    testWidgets('renders TRON API missing copy on TRC20 rpc_not_configured',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': 'TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_not_configured',
      };
      await _buildDetail(tester, client, 'USDT_TRC20',
          network: 'tron_mainnet');
      expect(find.text(kWalletBalanceCopyRpcMissingTron), findsOneWidget);
    });

    testWidgets(
      'renders token-contract-missing copy on USDT_ERC20 token_contract_not_configured',
      (tester) async {
        final client = _BalanceSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0x1111111111111111111111111111111111111111',
        };
        client.nextBalanceResponse = {
          'balanceStatus': 'unavailable',
          'reason': 'token_contract_not_configured',
        };
        await _buildDetail(tester, client, 'USDT_ERC20',
            network: 'ethereum_mainnet');
        expect(
          find.byKey(const Key(kWalletBalanceReasonKeyTokenContractMissing)),
          findsOneWidget,
        );
        expect(
          find.text(kWalletBalanceCopyTokenContractMissing),
          findsOneWidget,
        );
      },
    );

    testWidgets('renders Balance temporarily unavailable on RPC error',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_unreachable',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(find.text(kWalletBalanceCopyRpcError), findsOneWidget);
    });

    testWidgets('renders real balance number when backend returns available',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'available',
        'availableAmount': '1.5',
        'unit': 'ETH',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(find.text('1.5 ETH'), findsOneWidget);
    });

    testWidgets('renders real zero when backend returns zero from chain',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'available',
        'availableAmount': '0',
        'unit': 'ETH',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(find.text('0 ETH'), findsOneWidget);
    });

    testWidgets('never renders the vague not-connected copy when reason known',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_not_configured',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(find.text(kAssetDetailBalanceNotConnected), findsNothing);
    });

    testWidgets('refresh button triggers a fresh balance load',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_not_configured',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      final before = client.balanceCallCount;
      await tester.tap(
        find.byKey(const Key(kAssetDetailBalanceRefreshBtnKey)),
      );
      await tester.pumpAndSettle();
      expect(client.balanceCallCount, greaterThan(before));
    });

    testWidgets('refresh reflects newly-configured RPC without app rebuild',
        (tester) async {
      final client = _BalanceSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': '0x1111111111111111111111111111111111111111',
      };
      client.nextBalanceResponse = {
        'balanceStatus': 'unavailable',
        'reason': 'rpc_not_configured',
      };
      await _buildDetail(tester, client, 'ETH',
          network: 'ethereum_mainnet');
      expect(find.text(kWalletBalanceCopyRpcMissingEthereum), findsOneWidget);

      client.nextBalanceResponse = {
        'balanceStatus': 'available',
        'availableAmount': '0.5',
        'unit': 'ETH',
      };
      await tester.tap(
        find.byKey(const Key(kAssetDetailBalanceRefreshBtnKey)),
      );
      await tester.pumpAndSettle();
      expect(find.text('0.5 ETH'), findsOneWidget);
      expect(find.text(kWalletBalanceCopyRpcMissingEthereum), findsNothing);
    });

    testWidgets(
      'balance card fits without overflow at narrow mobile width',
      (tester) async {
        tester.view.physicalSize = const Size(360, 720);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.reset);

        final client = _BalanceSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0x1111111111111111111111111111111111111111',
        };
        client.nextBalanceResponse = {
          'balanceStatus': 'unavailable',
          'reason': 'rpc_not_configured',
        };
        await _buildDetail(tester, client, 'ETH',
            network: 'ethereum_mainnet');
        expect(tester.takeException(), isNull);
      },
    );
  });


  group('Copy hygiene', () {
    test('every honest copy line is short and matches spec', () {
      expect(kWalletBalanceCopyNoWallet, 'Create wallet to view balance.');
      expect(
        kWalletBalanceCopyRpcMissingEthereum,
        'Ethereum RPC is not configured.',
      );
      expect(
        kWalletBalanceCopyRpcMissingSolana,
        'Solana RPC is not configured.',
      );
      expect(
        kWalletBalanceCopyRpcMissingTron,
        'TRON API is not configured.',
      );
      expect(
        kWalletBalanceCopyTokenContractMissing,
        'Token contract is not configured.',
      );
      expect(
        kWalletBalanceCopyRpcError,
        'Balance temporarily unavailable.',
      );
      expect(
        kWalletBalanceCopyFeatureDisabled,
        'This asset is not enabled yet.',
      );
    });

    test('no honest copy contains marketing verbs', () {
      const forbidden = [
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
      ];
      for (final copy in [
        kWalletBalanceCopyNoWallet,
        kWalletBalanceCopyRpcMissingEthereum,
        kWalletBalanceCopyRpcMissingSolana,
        kWalletBalanceCopyRpcMissingTron,
        kWalletBalanceCopyRpcMissingMonero,
        kWalletBalanceCopyTokenContractMissing,
        kWalletBalanceCopyRpcError,
        kWalletBalanceCopyFeatureDisabled,
        kWalletBalanceCopyXmrScanner,
        kWalletBalanceCopyInvalidAddress,
      ]) {
        for (final v in forbidden) {
          expect(copy.toLowerCase(), isNot(contains(' $v ')));
        }
      }
    });
  });
}
