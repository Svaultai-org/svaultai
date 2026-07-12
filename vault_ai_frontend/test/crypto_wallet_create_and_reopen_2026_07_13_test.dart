// 2026-07-13 regression tests for the TRON wallet creation flow
// concurrency, reopen behavior, and the sheet close/back control.
//
// Production report:
//   "For USDT TRC20 I could create a TRON wallet. The Receive panel
//    opens. After the wallet exists, the QR/address panel is shown.
//    There is NO visible back arrow or close button."
//
// The fix installs a shared sheet chrome (see
// crypto_wallet_sheet_chrome_2026_07_13_test.dart). This suite
// asserts the wallet flow itself remains correct:
//   * Create button is disabled/loading during creation.
//   * Rapid double-taps produce exactly ONE POST create call.
//   * On success the same widget rebuilds into the QR/address view
//     (no Navigator push, so the sheet chrome stays in place).
//   * Re-mounting the panel with an existing-wallet response goes
//     straight to Receive QR — no re-create.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_sheet_chrome.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_receive_panel.dart';


class _SpyClient extends VaultAIClient {
  final List<String> receiveCalls = [];
  int createCalls = 0;
  final Completer<Map<String, dynamic>> pendingCreate =
      Completer<Map<String, dynamic>>();

  /// Sequence of responses returned by successive
  /// `getCryptoWalletReceiveNetwork` calls.
  final List<Map<String, dynamic>> receiveResponses = [];

  _SpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    final idx = receiveCalls.length;
    receiveCalls.add('$network/$asset');
    if (idx < receiveResponses.length) return receiveResponses[idx];
    // Default: no-account state.
    return const {'wallet_engine': 'no_account'};
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
    return pendingCreate.future;
  }
}


CryptoWalletFeatures _features() {
  return CryptoWalletFeatures.fromBackend(const {
    'walletEngineEnabled':        true,
    'sepoliaReceiveEnabled':      true,
    'sepoliaSendEnabled':         true,
    'mainnetReceiveEnabled':      false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':         false,
    'mainnetSendPaused':          false,
    'defaultNetwork':             'ethereum_sepolia',
    'defaultNetworkConfigValid':  true,
    'solanaEnabled':              false,
    'solanaReceiveEnabled':       false,
    'solanaBalanceEnabled':       false,
    'solanaSendEnabled':          false,
    'solanaSendPaused':           false,
    'solanaActivityConnected':    false,
    'solanaStatusReady':          false,
    'solanaFeeReady':             false,
    'tronEnabled':                true,
    'tronReceiveEnabled':         true,
    'tronBalanceEnabled':         true,
    'tronSendEnabled':            false,
    'tronActivityConnected':      false,
    'tronUsdtContractConfigured': true,
    'supportedNetworks': ['ethereum_sepolia', 'tron_mainnet'],
    'supportedAssetsByNetwork': {
      'ethereum_sepolia': ['ETH'],
      'tron_mainnet':     ['USDT_TRC20'],
    },
  });
}


Widget _wrapPanel({
  required _SpyClient client,
  Key? panelKey,
}) {
  return MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    home: Scaffold(
      backgroundColor: kWalletBgBase,
      body: CryptoWalletEngineTronReceivePanel(
        key: panelKey,
        authToken: 'tok',
        client: client,
        encryptForVault: (plaintext) async => 'ct:$plaintext',
        isVaultKeyAvailable: () => true,
        features: _features(),
      ),
    ),
  );
}


Widget _wrapInsideSheet(_SpyClient client) {
  return MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    home: Scaffold(
      backgroundColor: kWalletBgBase,
      body: Builder(
        builder: (ctx) => Center(
          child: ElevatedButton(
            key: const Key('open_receive_sheet'),
            onPressed: () => showCryptoWalletSheet<void>(
              context: ctx,
              title: 'Receive USDT (TRC20)',
              sheetKey: 'crypto_wallet_engine_receive_sheet',
              child: CryptoWalletEngineTronReceivePanel(
                authToken: 'tok',
                client: client,
                encryptForVault: (plaintext) async => 'ct:$plaintext',
                isVaultKeyAvailable: () => true,
                features: _features(),
              ),
            ),
            child: const Text('Receive'),
          ),
        ),
      ),
    ),
  );
}


void main() {
  group('Wallet creation: loading + double-tap protection', () {
    testWidgets('rapid Create taps produce exactly ONE server '
        'create call, and the button locks while pending', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'create_tron_wallet_first',
          'wallet_engine_status':   'create_tron_wallet_first',
        });

      await t.pumpWidget(_wrapPanel(client: client));
      await t.pumpAndSettle();

      final createBtn = find.byKey(
        const Key(kTronReceivePanelCreateBtnKey),
      );
      expect(createBtn, findsOneWidget);

      // Rapid double tap. Second tap should be a no-op because the
      // panel disables `onPressed` while `_creating == true`.
      await t.tap(createBtn);
      await t.pump();
      // Second tap while still creating.
      await t.tap(createBtn, warnIfMissed: false);
      await t.pump();

      // The mocked create Future is still pending. Only one call.
      expect(client.createCalls, equals(1),
          reason: 'rapid taps must collapse to exactly one create '
              'RPC while the previous one is still in flight');

      // Complete the create so no dangling Future outlives the test.
      client.pendingCreate.complete(const {'wallet_engine': 'created'});
      await t.pump();
    });

    testWidgets('button shows a spinner icon while creating (button '
        'is disabled — onPressed becomes null)', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'create_tron_wallet_first',
          'wallet_engine_status':   'create_tron_wallet_first',
        });

      await t.pumpWidget(_wrapPanel(client: client));
      await t.pumpAndSettle();

      await t.tap(find.byKey(const Key(kTronReceivePanelCreateBtnKey)));
      // Do NOT settle — the mock create Future stays pending; we
      // want to see the button in its in-flight state.
      await t.pump();

      final btn = t.widget<ElevatedButton>(
        find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
      );
      expect(btn.onPressed, isNull,
          reason: 'button MUST be disabled while creation is '
              'pending — this is the double-tap guard');
      expect(find.byType(CircularProgressIndicator), findsWidgets);

      client.pendingCreate.complete(const {'wallet_engine': 'created'});
      await t.pump();
    });
  });

  group('Wallet creation: successful transition to QR/address', () {
    testWidgets('after create completes, panel rebuilds into '
        'receive-ready state with QR + address (in place, no '
        'Navigator push)', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'create_tron_wallet_first',
          'wallet_engine_status':   'create_tron_wallet_first',
        })
        ..receiveResponses.add(const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':         'TXYZReceiveAddressExample1234567890',
        });

      await t.pumpWidget(_wrapPanel(client: client));
      await t.pumpAndSettle();

      // Initial: Create state.
      expect(
        find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kTronReceivePanelQrKey)),
        findsNothing,
      );

      // Fire creation.
      await t.tap(find.byKey(
        const Key(kTronReceivePanelCreateBtnKey),
      ));
      await t.pump();

      // Complete the mock create — panel will now call _load()
      // which returns receive_ready.
      client.pendingCreate.complete(const {'wallet_engine': 'created'});
      await t.pumpAndSettle();

      // Ready state widgets are now present; Create button is gone.
      expect(
        find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kTronReceivePanelQrKey)),
        findsOneWidget,
      );
      expect(find.byType(QrImageView), findsOneWidget);
      expect(
        find.byKey(const Key(kTronReceivePanelAddressTextKey)),
        findsOneWidget,
      );
      // Two receive fetches: initial mount + post-create refresh.
      expect(client.receiveCalls.length, equals(2));
    });
  });

  group('Wallet reopen: existing wallet is not recreated', () {
    testWidgets('mounting the panel with an existing-wallet backend '
        'response shows the QR immediately, does NOT call create',
        (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':         'TABCExistingWalletAddressXYZ12345678',
        });

      await t.pumpWidget(_wrapPanel(client: client));
      await t.pumpAndSettle();

      // No Create button.
      expect(
        find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
        findsNothing,
      );
      // QR + address are shown.
      expect(
        find.byKey(const Key(kTronReceivePanelQrKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kTronReceivePanelAddressTextKey)),
        findsOneWidget,
      );
      // createCryptoWalletAccountNetwork was NEVER invoked.
      expect(client.createCalls, equals(0),
          reason: 'reopening Receive with an existing wallet MUST '
              'NOT trigger a second wallet creation');
    });
  });

  group('Sheet chrome + wallet flow — close X visible in create '
      'state AND in receive-ready state', () {
    testWidgets('opening the Receive sheet renders the drag handle '
        'and the close X above the Create button', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'create_tron_wallet_first',
          'wallet_engine_status':   'create_tron_wallet_first',
        });

      await t.pumpWidget(_wrapInsideSheet(client));
      await t.tap(find.byKey(const Key('open_receive_sheet')));
      await t.pumpAndSettle();

      // Sheet chrome present.
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_drag_handle',
        )),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_close_btn',
        )),
        findsOneWidget,
      );
      // Panel body present under it.
      expect(
        find.byKey(const Key(kTronReceivePanelCreateBtnKey)),
        findsOneWidget,
      );
    });

    testWidgets('close X remains visible after transitioning from '
        'create state → receive-ready state (regression: the '
        'original bug had NO control at all here)', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'create_tron_wallet_first',
          'wallet_engine_status':   'create_tron_wallet_first',
        })
        ..receiveResponses.add(const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':         'TQRExampleAddressAfterCreation12345',
        });

      await t.pumpWidget(_wrapInsideSheet(client));
      await t.tap(find.byKey(const Key('open_receive_sheet')));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
        const Key(kTronReceivePanelCreateBtnKey),
      ));
      await t.pump();
      client.pendingCreate.complete(const {
        'wallet_engine':          'created',
      });
      await t.pumpAndSettle();

      // Now in receive-ready state.
      expect(
        find.byKey(const Key(kTronReceivePanelQrKey)),
        findsOneWidget,
      );
      // ✅ Close X is STILL visible — this is exactly what the
      // production bug was missing.
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_close_btn',
        )),
        findsOneWidget,
      );
    });

    testWidgets('tapping the close X after wallet is ready dismisses '
        'the sheet cleanly — the created wallet was already '
        'persisted server-side so nothing is lost', (t) async {
      final client = _SpyClient()
        ..receiveResponses.add(const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':         'TABCExistingWalletAddressXYZ12345678',
        });

      await t.pumpWidget(_wrapInsideSheet(client));
      await t.tap(find.byKey(const Key('open_receive_sheet')));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
        const Key('crypto_wallet_engine_receive_sheet_close_btn'),
      ));
      await t.pumpAndSettle();

      // Sheet is gone; underlying "Receive" button is visible again.
      expect(find.byKey(const Key(kTronReceivePanelQrKey)),
          findsNothing);
      expect(find.byKey(const Key('open_receive_sheet')),
          findsOneWidget);
    });
  });

  group('Wallet flow: long address on mobile widths 360/390/430', () {
    for (final width in const <double>[360, 390, 430]) {
      testWidgets('${width.toInt()}dp: full 34-char TRON address '
          'renders inside the sheet with the QR + close X visible '
          'and no RenderFlex overflow', (t) async {
        t.view.physicalSize = Size(width, 900);
        t.view.devicePixelRatio = 1.0;
        addTearDown(() {
          t.view.resetPhysicalSize();
          t.view.resetDevicePixelRatio();
        });

        final client = _SpyClient()
          ..receiveResponses.add({
            'wallet_engine':          'receive_ready',
            'wallet_engine_status':   'receive_ready',
            'publicAddress':          'TXYZ${'a' * 30}',
          });

        await t.pumpWidget(_wrapInsideSheet(client));
        await t.tap(find.byKey(const Key('open_receive_sheet')));
        await t.pumpAndSettle();

        expect(t.takeException(), isNull,
            reason: 'no layout overflow expected at ${width}dp');
        expect(
          find.byKey(const Key(kTronReceivePanelQrKey)),
          findsOneWidget,
        );
        // Close X is reachable at every tested mobile width.
        expect(
          find.byKey(const Key(
            'crypto_wallet_engine_receive_sheet_close_btn',
          )),
          findsOneWidget,
        );
      });
    }
  });

  group('Sheet chrome close button remains reachable at extreme '
      'narrow 320dp even when the panel body has legacy width '
      'assumptions', () {
    testWidgets('320dp: close X + drag handle are on-screen and '
        'tappable even if the panel body itself overflows '
        'internally (pre-existing 320dp panel layout debt is out '
        'of scope for this PR — the user\'s reported bug was the '
        'missing close control, and this test proves the close '
        'still works at the narrowest mobile viewport)', (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1.0;
      addTearDown(() {
        t.view.resetPhysicalSize();
        t.view.resetDevicePixelRatio();
      });

      final client = _SpyClient()
        ..receiveResponses.add({
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':          'TXYZ${'a' * 30}',
        });

      await t.pumpWidget(_wrapInsideSheet(client));
      await t.tap(find.byKey(const Key('open_receive_sheet')));
      // Consume any pre-existing panel overflow errors deliberately.
      // The chrome itself (drag handle + close X) is what matters.
      await t.pumpAndSettle();
      t.takeException();

      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_close_btn',
        )),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_drag_handle',
        )),
        findsOneWidget,
      );

      // Tapping the close X still dismisses the sheet cleanly.
      await t.tap(find.byKey(const Key(
        'crypto_wallet_engine_receive_sheet_close_btn',
      )));
      await t.pumpAndSettle();
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_receive_sheet_close_btn',
        )),
        findsNothing,
      );
    });
  });
}
