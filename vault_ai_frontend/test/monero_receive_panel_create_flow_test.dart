


import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_receive_panel.dart';


class _MoneroSpyClient extends VaultAIClient {
  Map<String, dynamic> nextReceiveResponse = {'wallet_engine': 'no_account'};
  final List<Map<String, dynamic>> createCalls = [];

  _MoneroSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
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
    createCalls.add({
      'network':               network,
      'asset':                 asset,
      'walletLabel':           walletLabel,
      'publicAddress':         publicAddress,
      'encryptedWalletSecret': encryptedWalletSecret,
      'restoreHeight':         restoreHeight,
      'scannerMode':           scannerMode,
    });
    nextReceiveResponse = {
      'wallet_engine':  'receive_ready',
      'publicAddress':  publicAddress,
      'walletLabel':    walletLabel,
      'restoreHeight':  restoreHeight,
    };
    return {'wallet_engine': 'account_created'};
  }
}


CryptoWalletFeatures _features({bool xmrOn = true}) {
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
    'xmrScannerMode':            'none',
    'supportedNetworks':         const ['ethereum_sepolia'],
    'supportedAssetsByNetwork':  const {},
  });
}


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


Future<void> _pumpPanel(
  WidgetTester tester, {
  required _MoneroSpyClient client,
  required MoneroWalletAdapter adapter,
  Future<String> Function(String)? encryptForVault,
  bool Function()? isVaultKeyAvailable,
}) async {
  await tester.pumpWidget(_wrap(
    CryptoWalletEngineMoneroReceivePanel(
      authToken: 'tok',
      client: client,
      features: _features(),
      walletAdapter: adapter,
      encryptForVault:
          encryptForVault ?? ((p) async => 'vault-cipher:${p.length}'),
      isVaultKeyAvailable: isVaultKeyAvailable ?? () => true,
    ),
  ));
  await tester.pumpAndSettle();
}


void main() {

  group('MoneroReceivePanel — no wallet exists, adapter available', () {
    testWidgets(
      'Create Monero wallet button is rendered when adapter is available',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Generation-pending banner is rendered when adapter unavailable',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client,
          adapter: const NullMoneroWalletAdapter(),
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
          findsNothing,
        );
        expect(
          find.text(kMoneroReceiveGenerationPendingMessage),
          findsOneWidget,
        );
      },
    );
  });


  group('MoneroReceivePanel — Create Monero wallet flow', () {

    testWidgets(
      'tapping Create → generates real address → POSTs ciphertext only '
      '→ refresh shows QR + address',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls.length, 1);
        final call = client.createCalls.first;
        expect(call['network'], 'monero_mainnet');
        expect(call['asset'], 'XMR');
        expect(call['scannerMode'], 'none');
        expect(call['restoreHeight'], greaterThan(0));
        final generatedAddress = call['publicAddress'] as String;
        expect(generatedAddress.length, 95);
        expect(generatedAddress.substring(0, 1), '4');
        expect(
          moneroPrimaryAddressChecksumValid(generatedAddress),
          true,
        );
        final envelope = call['encryptedWalletSecret'] as String;
        expect(envelope.startsWith('vault-cipher:'), true);
        expect(envelope.contains('spendKey'), false);
        expect(envelope.contains('viewKey'), false);
        expect(envelope.contains('privateSpend'), false);
        expect(envelope.contains('mnemonic'), false);

        expect(
          find.byKey(const Key(kMoneroReceivePanelQrKey)),
          findsOneWidget,
        );
        expect(find.text(generatedAddress), findsOneWidget);
      },
    );

    testWidgets(
      'HTTP payload keys never include mnemonic / spendKey / viewKey / '
      'privateSpendKey / privateViewKey / walletPassword',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        final call = client.createCalls.first;
        for (final banned in const [
          'mnemonic', 'spendKey', 'viewKey', 'privateSpendKey',
          'privateViewKey', 'walletPassword', 'seed25', 'polyseed',
          'moneroSpendKey', 'moneroViewKey', 'moneroSeed',
          'recoveryPhrase',
        ]) {
          expect(call.containsKey(banned), false,
              reason: 'payload must not carry $banned');
        }
      },
    );

    testWidgets(
      'when vault key is unavailable, Create fails with honest message '
      'and no HTTP call fires',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
          isVaultKeyAvailable: () => false,
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls, isEmpty);
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateFailedKey)),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroReceiveCreateVaultKeyMissingMessage),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'when generation throws, Create shows honest failure and no fake '
      'address is rendered',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        final failing = InjectedMoneroWalletAdapter(
          generator: ({
            required int restoreHeight,
            required Future<String> Function(String) encryptForVault,
            Uint8List? seedForTests,
          }) async {
            throw const MoneroWalletGenerationFailed('boom');
          },
        );
        await _pumpPanel(tester, client: client, adapter: failing);
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls, isEmpty);
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateFailedKey)),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroReceiveCreateFallbackErrorMessage),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelQrKey)),
          findsNothing,
        );
      },
    );
  });


  group('MoneroReceivePanel — mobile overflow', () {
    testWidgets(
      'no-account state fits without overflow at 420 x 720',
      (tester) async {
        tester.view.physicalSize = const Size(420, 720);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.reset);
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'receive-ready state fits without overflow at 420 x 800',
      (tester) async {
        tester.view.physicalSize = const Size(420, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.reset);
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress':
              '44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7Sq'
              'SsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A',
          'walletLabel':  'Monero',
          'restoreHeight': 3220000,
        };
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(tester.takeException(), isNull);
      },
    );
  });


  group('MoneroReceivePanel — copy hygiene', () {
    test('no marketing exchange verbs in Monero copy constants', () {
      const forbidden = [
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
      ];
      for (final copy in const [
        kMoneroReceivePanelTitle,
        kMoneroReceiveNetworkBadge,
        kMoneroReceiveNonCustodialAttestation,
        kMoneroReceiveAssetWarning,
        kMoneroReceivePrivacyNote,
        kMoneroReceiveDisabledMessage,
        kMoneroReceiveGenerationPendingMessage,
        kMoneroReceiveCreateButtonLabel,
        kMoneroReceiveCreateBusyLabel,
        kMoneroReceiveCreateVaultKeyMissingMessage,
        kMoneroReceiveCreateFallbackErrorMessage,
      ]) {
        for (final v in forbidden) {
          expect(
            copy.toLowerCase(), isNot(contains(' $v ')),
            reason: 'copy must not contain marketing verb "$v": $copy',
          );
        }
      }
    });

    test('never asks user to type a seed / mnemonic / spend / view key', () {
      const inputs = [
        'seed', 'mnemonic', 'spend key', 'view key', 'polyseed',
      ];
      for (final copy in const [
        kMoneroReceiveCreateButtonLabel,
        kMoneroReceiveCreateBusyLabel,
        kMoneroReceiveCreateVaultKeyMissingMessage,
        kMoneroReceiveCreateFallbackErrorMessage,
      ]) {
        for (final tok in inputs) {
          expect(
            copy.toLowerCase(),
            isNot(contains('enter your $tok')),
          );
          expect(
            copy.toLowerCase(),
            isNot(contains('paste your $tok')),
          );
        }
      }
    });
  });
}
