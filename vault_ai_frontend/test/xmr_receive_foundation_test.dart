

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_receive_panel.dart';


const String _kXmrDonationAddr =
    '44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb'
    '98uNbr2VBBEt7f2wfn3RVGQBEP3A';


class _MoneroReceiveSpyClient extends VaultAIClient {
  Map<String, dynamic> nextReceiveResponse = {};
  final List<String> receiveCalls = [];

  _MoneroReceiveSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCalls.add('$network/$asset');
    return nextReceiveResponse;
  }
}


CryptoWalletFeatures _features({
  bool xmrOn = true,
  String scannerMode = 'none',
}) {
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
    'xmrEnabled':                xmrOn,
    'xmrReceiveEnabled':         xmrOn,
    'xmrBalanceEnabled':         false,
    'xmrSendEnabled':            false,
    'xmrActivityConnected':      false,
    'xmrScannerMode':            scannerMode,
    'supportedNetworks':         xmrOn
        ? const ['ethereum_sepolia', 'ethereum_mainnet', 'monero_mainnet']
        : const ['ethereum_sepolia', 'ethereum_mainnet'],
    'supportedAssetsByNetwork':  xmrOn
        ? const {
            'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'monero_mainnet':   ['XMR'],
          }
        : const {
            'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
            'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
          },
  });
}


void main() {
  group('MoneroWalletFeatures', () {
    test('unknown has XMR off + scanner none', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.xmrEnabled, isFalse);
      expect(f.xmrReceiveEnabled, isFalse);
      expect(f.xmrBalanceEnabled, isFalse);
      expect(f.xmrSendEnabled, isFalse);
      expect(f.xmrActivityConnected, isFalse);
      expect(f.xmrScannerMode, 'none');
    });

    test('backend can turn XMR on', () {
      final f = _features(xmrOn: true);
      expect(f.xmrEnabled, isTrue);
      expect(f.xmrReceiveEnabled, isTrue);
      expect(f.xmrBalanceEnabled, isFalse);
      expect(f.xmrSendEnabled, isFalse);
      expect(f.xmrActivityConnected, isFalse);
    });

    test('supportedAssetsByNetwork lists XMR only on monero', () {
      final f = _features(xmrOn: true);
      expect(f.supportedAssetsByNetwork['monero_mainnet'],
          equals(const ['XMR']));
    });
  });


  group('MoneroAddressShape', () {
    test('valid 95-char primary donation address passes', () {
      expect(
        isValidMoneroPrimaryAddressShape(_kXmrDonationAddr),
        isTrue,
      );
    });

    test('ethereum address rejected', () {
      expect(
        isValidMoneroPrimaryAddressShape('0x${'a' * 40}'),
        isFalse,
      );
    });

    test('empty and null rejected', () {
      expect(isValidMoneroPrimaryAddressShape(''), isFalse);
      expect(isValidMoneroPrimaryAddressShape(null), isFalse);
    });

    test('wrong length rejected', () {
      expect(
        isValidMoneroPrimaryAddressShape(
          _kXmrDonationAddr.substring(0, 94),
        ),
        isFalse,
      );
    });
  });


  group('MoneroWalletAdapter', () {
    test('NullMoneroWalletAdapter is unavailable', () {
      const adapter = NullMoneroWalletAdapter();
      expect(adapter.isAvailable, isFalse);
      expect(adapter.unavailableReason, isNotEmpty);
    });

    test('null adapter throws MoneroWalletGenerationBlocked', () async {
      const adapter = NullMoneroWalletAdapter();
      expect(
        () => adapter.generate(
          restoreHeight: 3220000,
          encryptForVault: (p) async => p,
        ),
        throwsA(isA<MoneroWalletGenerationBlocked>()),
      );
    });

    test('InjectedMoneroWalletAdapter forwards to generator', () async {
      final adapter = InjectedMoneroWalletAdapter(
        generator: ({
          required int restoreHeight,
          required Future<String> Function(String plaintext) encryptForVault,
          Uint8List? seedForTests,
        }) async {
          return GeneratedMoneroWallet(
            publicAddress: _kXmrDonationAddr,
            restoreHeight: restoreHeight,
            encryptedWalletSecretPayload: 'ct',
          );
        },
      );
      expect(adapter.isAvailable, isTrue);
      final w = await adapter.generate(
        restoreHeight: 3220000,
        encryptForVault: (p) async => p,
      );
      expect(w.publicAddress, _kXmrDonationAddr);
      expect(w.restoreHeight, 3220000);
    });
  });


  group('MoneroReceivePanel', () {
    testWidgets(
      'shows disabled banner when XMR support off',
      (t) async {
        final client = _MoneroReceiveSpyClient();
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroReceivePanel(
              authToken: 'tok',
              client: client,
              features: _features(xmrOn: false),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kMoneroReceivePanelDisabledKey)),
          findsOneWidget,
        );
        expect(client.receiveCalls, isEmpty);
      },
    );

    testWidgets(
      'shows generation-pending banner when no wallet exists yet',
      (t) async {
        final client = _MoneroReceiveSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'create_xmr_wallet_first',
          'network':       'monero_mainnet',
          'networkLabel':  'Monero',
        };
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroReceivePanel(
              authToken: 'tok',
              client: client,
              features: _features(xmrOn: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(
            kMoneroReceivePanelGenerationPendingKey,
          )),
          findsOneWidget,
        );
        expect(client.receiveCalls, equals(['monero_mainnet/XMR']));
      },
    );

    testWidgets(
      'shows real address, warning, and privacy note when receive_ready',
      (t) async {
        final client = _MoneroReceiveSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine':  'receive_ready',
          'network':        'monero_mainnet',
          'networkLabel':   'Monero',
          'walletLabel':    'My Monero wallet',
          'publicAddress':  _kXmrDonationAddr,
          'restoreHeight':  3220000,
          'warning':        'Only send XMR on Monero to this address.',
          'privacyNote':    'Monero balance and activity require '
                            'wallet scanning. Scanning is not enabled '
                            'yet.',
        };
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroReceivePanel(
              authToken: 'tok',
              client: client,
              features: _features(xmrOn: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kMoneroReceivePanelQrKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelAddressTextKey)),
          findsOneWidget,
        );
        expect(find.text(_kXmrDonationAddr), findsOneWidget);
        expect(
          find.byKey(const Key(kMoneroReceivePanelWarningKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelPrivacyNoteKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelRestoreHeightKey)),
          findsOneWidget,
        );
        expect(
          find.textContaining('XMR on Monero'), findsOneWidget,
        );
        expect(
          find.textContaining('scanning'), findsOneWidget,
        );
      },
    );
  });


  group('MoneroActivityCard', () {
    testWidgets(
      'disabled state renders planned copy',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroActivityCard(
              features: _features(xmrOn: false),
            ),
          ),
        ));
        expect(
          find.byKey(const Key(kMoneroActivityDisabledKey)),
          findsOneWidget,
        );
        expect(find.text(kMoneroActivityDisabledCopy), findsOneWidget);
      },
    );

    testWidgets(
      'enabled but scanner not ready renders honest unavailable',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroActivityCard(
              features: _features(xmrOn: true),
            ),
          ),
        ));
        expect(
          find.byKey(const Key(
            kMoneroActivityScannerNotEnabledKey,
          )),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroActivityScannerNotEnabledCopy),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'no fake tx row rendered',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroActivityCard(
              features: _features(xmrOn: true),
            ),
          ),
        ));
        for (final banned in const [
          'Confirmed', 'Pending', 'Sent', 'Received',
          '+', 'XMR ', '0.0',
        ]) {
          expect(find.textContaining(banned), findsNothing,
              reason: 'activity card leaked "$banned"');
        }
      },
    );
  });


  group('MoneroBalanceCard', () {
    testWidgets(
      'disabled state renders planned copy',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroBalanceCard(
              features: _features(xmrOn: false),
            ),
          ),
        ));
        expect(
          find.byKey(const Key(kMoneroBalanceDisabledKey)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'enabled but scanner not ready renders honest unavailable',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroBalanceCard(
              features: _features(xmrOn: true),
            ),
          ),
        ));
        expect(
          find.byKey(const Key(
            kMoneroBalanceScannerNotEnabledKey,
          )),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroBalanceScannerNotEnabledCopy),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'no fake zero balance rendered',
      (t) async {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMoneroBalanceCard(
              features: _features(xmrOn: true),
            ),
          ),
        ));
        for (final banned in const [
          '0 XMR', '0.0 XMR', '0.00 XMR', '0.000 XMR',
        ]) {
          expect(find.text(banned), findsNothing,
              reason: 'balance card leaked fake zero "$banned"');
        }
      },
    );
  });


  group('MoneroCopyIntegrity', () {
    test('receive panel copy never mentions other chains', () {
      for (final s in const [
        kMoneroReceivePanelTitle,
        kMoneroReceiveNetworkBadge,
        kMoneroReceiveAssetWarning,
        kMoneroReceivePrivacyNote,
        kMoneroReceiveDisabledMessage,
        kMoneroReceiveGenerationPendingMessage,
        kMoneroReceiveNonCustodialAttestation,
      ]) {
        expect(s.toLowerCase().contains('ethereum'), isFalse,
            reason: 'copy leaked ethereum: $s');
        expect(s.toLowerCase().contains('solana'), isFalse,
            reason: 'copy leaked solana: $s');
        expect(s.toLowerCase().contains('sepolia'), isFalse,
            reason: 'copy leaked sepolia: $s');
        expect(s.toLowerCase().contains('erc20'), isFalse,
            reason: 'copy leaked erc20: $s');
        expect(s.toLowerCase().contains('trc20'), isFalse,
            reason: 'copy leaked trc20: $s');
        expect(s.toLowerCase().contains('tron'), isFalse,
            reason: 'copy leaked tron: $s');
      }
    });

    test('copy never mentions buy/sell/swap/trade/stake/bridge', () {
      for (final s in const [
        kMoneroReceivePanelTitle,
        kMoneroReceiveNetworkBadge,
        kMoneroReceiveAssetWarning,
        kMoneroReceivePrivacyNote,
        kMoneroReceiveDisabledMessage,
        kMoneroReceiveGenerationPendingMessage,
        kMoneroReceiveNonCustodialAttestation,
        kMoneroActivityDisabledCopy,
        kMoneroActivityScannerNotEnabledCopy,
        kMoneroBalanceDisabledCopy,
        kMoneroBalanceScannerNotEnabledCopy,
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

    test(
      'copy never asks user for seed/spend/view key/mnemonic',
      () {
        for (final s in const [
          kMoneroReceivePanelTitle,
          kMoneroReceiveNetworkBadge,
          kMoneroReceiveAssetWarning,
          kMoneroReceivePrivacyNote,
          kMoneroReceiveDisabledMessage,
          kMoneroReceiveGenerationPendingMessage,
          kMoneroReceiveNonCustodialAttestation,
        ]) {
          final low = s.toLowerCase();
          expect(low.contains('enter your seed'), isFalse,
              reason: 'copy asks for seed: $s');
          expect(low.contains('enter your mnemonic'), isFalse,
              reason: 'copy asks for mnemonic: $s');
          expect(low.contains('enter your spend key'), isFalse,
              reason: 'copy asks for spend key: $s');
          expect(low.contains('enter your view key'), isFalse,
              reason: 'copy asks for view key: $s');
        }
      },
    );
  });
}
