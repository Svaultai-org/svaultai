

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_receive_panel.dart';


const String _kTronUsdtContract = 'TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj';


class _TronReceiveSpyClient extends VaultAIClient {
  Map<String, dynamic> nextReceiveResponse = {};
  final List<String> receiveCalls = [];
  Map<String, dynamic>? capturedCreatePayload;

  _TronReceiveSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCalls.add('$network/$asset');
    return nextReceiveResponse;
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
    capturedCreatePayload = {
      'network':               network,
      'asset':                 asset,
      'walletLabel':           walletLabel,
      'publicAddress':         publicAddress,
      'encryptedWalletSecret': encryptedWalletSecret,
    };
    return {'wallet_engine': 'created'};
  }
}


CryptoWalletFeatures _features({bool tron = true}) {
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
    'tronEnabled':               tron,
    'tronReceiveEnabled':        tron,
    'tronBalanceEnabled':        tron,
    'tronSendEnabled':           false,
    'tronActivityConnected':     false,
    'tronUsdtContractConfigured': tron,
    'supportedNetworks':         tron
        ? const ['ethereum_sepolia', 'ethereum_mainnet', 'tron_mainnet']
        : const ['ethereum_sepolia', 'ethereum_mainnet'],
    'supportedAssetsByNetwork':  tron
        ? const {
            'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'tron_mainnet':     ['USDT_TRC20'],
          }
        : const {
            'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
          },
  });
}


void main() {
  group('TronWalletFeatures', () {
    test('unknown has TRON off by default', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.tronEnabled, isFalse);
      expect(f.tronReceiveEnabled, isFalse);
      expect(f.tronBalanceEnabled, isFalse);
      expect(f.tronSendEnabled, isFalse);
      expect(f.tronActivityConnected, isFalse);
    });

    test('backend can turn TRON on', () {
      final f = _features(tron: true);
      expect(f.tronEnabled, isTrue);
      expect(f.tronReceiveEnabled, isTrue);
      expect(f.tronBalanceEnabled, isTrue);
      expect(f.tronSendEnabled, isFalse);
      expect(f.tronActivityConnected, isFalse);
    });

    test('supportedAssetsByNetwork lists USDT_TRC20 only on TRON', () {
      final f = _features(tron: true);
      expect(f.supportedAssetsByNetwork['tron_mainnet'],
          equals(const ['USDT_TRC20']));
    });
  });


  group('TronAddressValidation', () {
    test('valid known USDT contract address passes', () {
      expect(isValidTronAddress(_kTronUsdtContract), isTrue);
    });

    test('short address rejected', () {
      expect(isValidTronAddress('T' * 3), isFalse);
    });

    test('ethereum address rejected', () {
      expect(isValidTronAddress('0x${'a' * 40}'), isFalse);
    });

    test('empty and null rejected', () {
      expect(isValidTronAddress(''), isFalse);
      expect(isValidTronAddress(null), isFalse);
    });

    test('bad checksum rejected', () {
      final broken =
          _kTronUsdtContract.substring(
              0, _kTronUsdtContract.length - 1) +
              (_kTronUsdtContract.endsWith('j') ? 'k' : 'j');
      expect(isValidTronAddress(broken), isFalse);
    });

    test('wrong prefix rejected', () {
      expect(
        isValidTronAddress('A${_kTronUsdtContract.substring(1)}'),
        isFalse,
      );
    });
  });


  group('TronWalletGeneration', () {
    test('generateTronWallet yields valid Base58Check T-address', () {
      final w = generateTronWallet();
      expect(w.publicAddress.startsWith('T'), isTrue);
      expect(isValidTronAddress(w.publicAddress), isTrue);
      expect(w.privateKeyHex.length, 64);
    });

    test('two generations produce distinct addresses', () {
      final a = generateTronWallet();
      final b = generateTronWallet();
      expect(a.publicAddress == b.publicAddress, isFalse);
      expect(a.privateKeyHex == b.privateKeyHex, isFalse);
    });

    test(
      'deriveTronAddressFromPrivateKeyHex reproduces the same address',
      () {
        final w = generateTronWallet();
        final again =
            deriveTronAddressFromPrivateKeyHex(w.privateKeyHex);
        expect(again, w.publicAddress);
      },
    );
  });


  group('TronReceivePanel', () {
    testWidgets(
      'shows disabled banner when TRON support off',
      (t) async {
        final client = _TronReceiveSpyClient();
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronReceivePanel(
              authToken: 'tok',
              client: client,
              encryptForVault: (_) async => 'ct',
              isVaultKeyAvailable: () => true,
              features: _features(tron: false),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(find.byKey(const Key(kTronReceivePanelDisabledKey)),
            findsOneWidget);
        expect(client.receiveCalls, isEmpty);
      },
    );

    testWidgets(
      'shows create button when no TRON wallet exists',
      (t) async {
        final client = _TronReceiveSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'create_tron_wallet_first',
          'network':       'tron_mainnet',
          'networkLabel':  'TRON',
          'tokenStandard': 'TRC20',
        };
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronReceivePanel(
              authToken: 'tok',
              client: client,
              encryptForVault: (_) async => 'ct',
              isVaultKeyAvailable: () => true,
              features: _features(tron: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
            findsOneWidget);
        expect(client.receiveCalls, equals(['tron_mainnet/USDT_TRC20']));
      },
    );

    testWidgets(
      'shows real address and warning when receive_ready',
      (t) async {
        final client = _TronReceiveSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine':  'receive_ready',
          'network':        'tron_mainnet',
          'networkLabel':   'TRON',
          'tokenStandard':  'TRC20',
          'walletLabel':    'My TRON wallet',
          'publicAddress':  _kTronUsdtContract,
          'warning':        'Only send USDT TRC20 on TRON to this address.',
          'gasNote':        'Sending later requires TRX for network fees.',
        };
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronReceivePanel(
              authToken: 'tok',
              client: client,
              encryptForVault: (_) async => 'ct',
              isVaultKeyAvailable: () => true,
              features: _features(tron: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(find.byKey(const Key(kTronReceivePanelQrKey)),
            findsOneWidget);
        expect(
          find.byKey(const Key(kTronReceivePanelAddressTextKey)),
          findsOneWidget,
        );
        expect(
          find.text(_kTronUsdtContract), findsOneWidget,
        );
        expect(
          find.byKey(const Key(kTronReceivePanelWarningKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kTronReceivePanelGasNoteKey)),
          findsOneWidget,
        );
        expect(
          find.textContaining('USDT TRC20 on TRON'), findsOneWidget,
        );
      },
    );

    testWidgets(
      'no-vault-key snackbar blocks creation',
      (t) async {
        final client = _TronReceiveSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'create_tron_wallet_first',
        };
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronReceivePanel(
              authToken: 'tok',
              client: client,
              encryptForVault: (_) async => 'ct',
              isVaultKeyAvailable: () => false,
              features: _features(tron: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.tap(find.byKey(
          const Key(kTronReceivePanelCreateBtnKey),
        ));
        await t.pump();
        expect(
          find.byKey(const Key(kTronReceivePanelNoKeySnackKey)),
          findsOneWidget,
        );
        expect(client.capturedCreatePayload, isNull);
      },
    );
  });


  group('TronActivityCard', () {
    testWidgets(
      'disabled state renders planned copy',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronActivityCard(
              features: _features(tron: false),
            ),
          ),
        ));
        expect(find.byKey(const Key(kTronActivityDisabledKey)),
            findsOneWidget);
        expect(find.text(kTronActivityDisabledCopy),
            findsOneWidget);
      },
    );

    testWidgets(
      'enabled but not connected renders honest unavailable',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineTronActivityCard(
              features: _features(tron: true),
            ),
          ),
        ));
        expect(
          find.byKey(const Key(kTronActivityNotConnectedKey)),
          findsOneWidget,
        );
        expect(
          find.text(kTronActivityNotConnectedCopy),
          findsOneWidget,
        );
      },
    );
  });


  group('TronCopyIntegrity', () {
    test('receive panel copy never mentions other chains', () {
      for (final s in const [
        kTronReceivePanelTitle,
        kTronReceiveNetworkBadge,
        kTronReceiveAssetWarning,
        kTronReceiveGasNote,
        kTronReceiveDisabledMessage,
        kTronReceiveCreateButtonLabel,
        kTronReceiveNonCustodialAttestation,
      ]) {
        expect(s.toLowerCase().contains('ethereum'), isFalse,
            reason: 'copy leaked ethereum: $s');
        expect(s.toLowerCase().contains('solana'), isFalse,
            reason: 'copy leaked solana: $s');
        expect(s.toLowerCase().contains('sepolia'), isFalse,
            reason: 'copy leaked sepolia: $s');
        expect(s.toLowerCase().contains('erc20'), isFalse,
            reason: 'copy leaked erc20: $s');
      }
    });

    test('receive copy never mentions buy/sell/swap/trade/stake/bridge',
        () {
      for (final s in const [
        kTronReceivePanelTitle,
        kTronReceiveNetworkBadge,
        kTronReceiveAssetWarning,
        kTronReceiveGasNote,
        kTronReceiveDisabledMessage,
        kTronReceiveCreateButtonLabel,
        kTronReceiveNonCustodialAttestation,
        kTronActivityDisabledCopy,
        kTronActivityNotConnectedCopy,
      ]) {
        final low = s.toLowerCase();
        for (final w in const [
          'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
          'market', 'profit', 'loss', 'exchange',
        ]) {
          expect(low.contains(w), isFalse,
              reason: 'copy leaked "$w": $s');
        }
      }
    });
  });
}
