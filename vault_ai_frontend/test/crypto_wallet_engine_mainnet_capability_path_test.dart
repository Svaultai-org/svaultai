import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

class _CapabilityClient extends VaultAIClient {
  Map<String, dynamic> featuresResponse;

  int featuresCalls = 0;
  final List<String> receiveNetworkCalls = [];

  _CapabilityClient(this.featuresResponse)
      : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
  }) async {
    featuresCalls += 1;
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
}

Map<String, dynamic> _mainnetFeatures({
  required bool mainnetSendEnabled,
  required bool mainnetSendPaused,
}) {
  return {
    'status': 'ok',
    'schema': 'crypto_wallet_features_v1',
    'walletEngineEnabled': true,
    'mainnetReceiveEnabled': true,
    'mainnetErc20ReceiveEnabled': true,
    'mainnetSendEnabled': mainnetSendEnabled,
    'mainnetSendPaused': mainnetSendPaused,
    'defaultNetwork': kEvmNetworkEthereumMainnet,
    'defaultNetworkConfigValid': true,
    'supportedNetworks': const [
      kEvmNetworkEthereumSepolia,
      kEvmNetworkEthereumMainnet,
    ],
    'supportedAssetsByNetwork': const {
      kEvmNetworkEthereumMainnet: ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
    },
  };
}

Future<void> _pumpWallet(
  WidgetTester tester, {
  required _CapabilityClient client,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoWalletEnginePage(
          authToken: 'tok',
          apiClient: client,
          encryptForVault: (plaintext) async => 'ct:$plaintext',
          decryptForVault: (ciphertext) async => 'pk',
          isVaultKeyAvailable: () => true,
          verifyPin: (_) async => true,
          loadFromAddress: (_) async =>
              '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf',
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('mainnet capability JSON drives wallet page send state', () {
    testWidgets(
      'enabled=true paused=false hides top banner and enables ETH/ERC20 Send',
      (tester) async {
        final client = _CapabilityClient(_mainnetFeatures(
          mainnetSendEnabled: true,
          mainnetSendPaused: false,
        ));

        await _pumpWallet(tester, client: client);

        expect(client.featuresCalls, 1);
        expect(
          find.byKey(const Key(kCryptoWalletEngineSendPausedKey)),
          findsNothing,
        );
        for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
          expect(
            find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset')),
            findsOneWidget,
            reason: '$asset Send should be visible when backend enables '
                'mainnet send and pause is false',
          );
        }
        expect(
          find.text('Mainnet sending is temporarily paused.'),
          findsNothing,
        );
      },
    );

    testWidgets(
      'enabled=true paused=true shows top banner and blocks ETH/ERC20 Send',
      (tester) async {
        final client = _CapabilityClient(_mainnetFeatures(
          mainnetSendEnabled: true,
          mainnetSendPaused: true,
        ));

        await _pumpWallet(tester, client: client);

        expect(
          find.byKey(const Key(kCryptoWalletEngineSendPausedKey)),
          findsOneWidget,
        );
        for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
          expect(
            find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset')),
            findsNothing,
            reason: '$asset Send should be hidden while backend pause is true',
          );
        }
        expect(
          find.text('Mainnet sending is temporarily paused.'),
          findsWidgets,
        );
      },
    );
  });
}
