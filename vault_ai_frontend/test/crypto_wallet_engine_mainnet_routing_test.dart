

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';


class _RoutingSpyClient extends VaultAIClient {
  final List<String> receiveNetworkCalls = [];
  final List<String> receiveLegacyCalls = [];
  final List<String> balanceNetworkCalls = [];
  final List<String> balanceLegacyCalls = [];
  final List<String> transactionsNetworkCalls = [];
  final List<String> transactionsLegacyCalls = [];
  final List<String> createNetworkCalls = [];
  final List<String> createLegacyCalls = [];
  Map<String, dynamic> featuresResponse = const {};

  _RoutingSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
  }) async {
    return featuresResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveNetworkCalls.add('$network/$asset');
    return {
      'schema': 'crypto_wallet_receive_v1',
      'wallet_engine': 'no_account',
      'publicAddress': '',
      'walletLabel': '',
      'network': network,
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    receiveLegacyCalls.add(asset);
    return {
      'schema': 'crypto_wallet_receive_v1',
      'wallet_engine': 'no_account',
      'publicAddress': '',
      'walletLabel': '',
      'network': 'ethereum_sepolia',
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceNetworkCalls.add('$network/$asset');
    return {'balanceStatus': 'unavailable', 'reason': 'no_wallet_yet'};
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalance({
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceLegacyCalls.add(asset);
    return {'balanceStatus': 'unavailable', 'reason': 'no_wallet_yet'};
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    transactionsNetworkCalls.add('$network/$asset');
    return {
      'transactionsStatus': 'unavailable',
      'reason': 'indexer_not_configured',
      'transactions': [],
    };
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactions({
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    transactionsLegacyCalls.add(asset);
    return {
      'transactionsStatus': 'unavailable',
      'reason': 'indexer_not_configured',
      'transactions': [],
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
    createNetworkCalls.add('$network/$asset');
    return {'walletId': 'wid-mainnet'};
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccount({
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String network,
    required String encryptedWalletSecret,
  }) async {
    createLegacyCalls.add('$network/$asset');
    return {'walletId': 'wid-legacy'};
  }
}


Future<void> _pumpReceivePanel(
  WidgetTester tester, {
  required _RoutingSpyClient client,
  required String asset,
  String? network,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: CryptoWalletEngineReceivePanel(
          authToken: 'test-token',
          client: client,
          encryptForVault: (p) async => 'ct-$p',
          isVaultKeyAvailable: () => true,
          asset: asset,
          network: network,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


Future<void> _pumpActivityCard(
  WidgetTester tester, {
  required _RoutingSpyClient client,
  required String asset,
  String? network,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: CryptoWalletActivityCard(
          asset: asset,
          apiClient: client,
          authToken: 'test-token',
          network: network,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('receive panel — mainnet default routing', () {
    testWidgets(
      'ETH receive with network=mainnet uses mainnet endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumMainnet,
        );
        expect(client.receiveNetworkCalls,
            equals(['ethereum_mainnet/ETH']));
        expect(client.receiveLegacyCalls, isEmpty,
            reason: 'Legacy sepolia route must not be called when '
                'network=mainnet');
      },
    );

    testWidgets(
      'USDT_ERC20 receive with network=mainnet uses mainnet endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'USDT_ERC20',
          network: kEvmNetworkEthereumMainnet,
        );
        expect(client.receiveNetworkCalls,
            equals(['ethereum_mainnet/USDT_ERC20']));
        expect(client.receiveLegacyCalls, isEmpty);
      },
    );

    testWidgets(
      'USDC_ERC20 receive with network=mainnet uses mainnet endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'USDC_ERC20',
          network: kEvmNetworkEthereumMainnet,
        );
        expect(client.receiveNetworkCalls,
            equals(['ethereum_mainnet/USDC_ERC20']));
        expect(client.receiveLegacyCalls, isEmpty);
      },
    );

    testWidgets(
      'ETH receive with network=sepolia uses sepolia network endpoint '
      '(not legacy)',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumSepolia,
        );
        expect(client.receiveNetworkCalls,
            equals(['ethereum_sepolia/ETH']));
      },
    );

    testWidgets(
      'ETH receive with no network arg falls back to legacy endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'ETH',
          network: null,
        );
        expect(client.receiveLegacyCalls, equals(['ETH']));
        expect(client.receiveNetworkCalls, isEmpty);
      },
    );

    testWidgets(
      'mainnet ETH receive panel warning says only send ETH on '
      'Ethereum Mainnet',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumMainnet,
        );
        expect(
          receivePanelAssetWarningFor(
              kEvmNetworkEthereumMainnet, 'ETH'),
          contains('Ethereum Mainnet'),
        );
      },
    );

    testWidgets(
      'mainnet receive panel does not surface Sepolia network badge',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpReceivePanel(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumMainnet,
        );
        final badge = receivePanelNetworkBadgeFor(
          kEvmNetworkEthereumMainnet,
        );
        expect(badge.toLowerCase(), isNot(contains('sepolia')));
        expect(badge.toLowerCase(), isNot(contains('testnet')));
      },
    );
  });

  group('activity card — mainnet routing', () {
    testWidgets(
      'activity with network=mainnet uses mainnet transactions endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpActivityCard(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumMainnet,
        );
        expect(client.transactionsNetworkCalls,
            equals(['ethereum_mainnet/ETH']));
        expect(client.transactionsLegacyCalls, isEmpty);
      },
    );

    testWidgets(
      'activity with network=sepolia uses sepolia transactions endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpActivityCard(
          tester,
          client: client,
          asset: 'ETH',
          network: kEvmNetworkEthereumSepolia,
        );
        expect(client.transactionsNetworkCalls,
            equals(['ethereum_sepolia/ETH']));
        expect(client.transactionsLegacyCalls, isEmpty);
      },
    );

    testWidgets(
      'activity with no network falls back to legacy transactions endpoint',
      (tester) async {
        final client = _RoutingSpyClient();
        await _pumpActivityCard(
          tester,
          client: client,
          asset: 'ETH',
          network: null,
        );
        expect(client.transactionsLegacyCalls, equals(['ETH']));
        expect(client.transactionsNetworkCalls, isEmpty);
      },
    );
  });

  group('non-exchange surface', () {
    test('receive panel constants never contain buy/sell/swap language', () {
      final blobs = [
        kEthReceiveAssetWarning,
        kEthReceiveAssetWarningMainnet,
        kTokenReceiveSharedAddressBanner,
        kTokenReceiveSharedAddressBannerMainnet,
        kTokenReceiveGasNoteMainnet,
        kTokenReceiveAssetWarningMainnetTemplate,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap', 'stake', 'bridge',
                              'trade', 'buy ', 'sell ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'Copy leaked banned language: $b');
        }
      }
    });

    test('receive panel constants never reference lite / saved-record', () {
      for (final b in [
        kEthReceiveAssetWarning,
        kEthReceiveAssetWarningMainnet,
        kTokenReceiveSharedAddressBanner,
        kTokenReceiveSharedAddressBannerMainnet,
      ]) {
        expect(b.toLowerCase(), isNot(contains('crypto vault lite')));
        expect(b.toLowerCase(),
            isNot(contains('receive qr only shows saved addresses')));
      }
    });
  });
}
