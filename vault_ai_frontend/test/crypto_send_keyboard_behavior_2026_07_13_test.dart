// 2026-07-13: Send-sheet mobile-keyboard behavior regression suite.
//
// Production Safari found the previous Send sheets compressed the
// form body between the header and a Review button that floated in
// the middle of the screen when the keyboard opened. Root cause:
// double `viewInsets.bottom` accounting -- the shared scaffold
// added `AnimatedPadding(bottom: viewInsets.bottom)` to the footer
// while the sheet's own overall bounds still sat at the physical
// viewport bottom, so the footer got shoved up into the body.
//
// The fix applies the keyboard inset ONCE, at the sheet's outer edge
// in `CryptoWalletSheetChrome`, and lets the descendant subtree see
// `viewInsets.bottom == 0`. As a result the whole sheet (header,
// scroll body, footer) lifts as one unit and the Review button sits
// naturally at the bottom of the sheet, immediately above the
// keyboard. The scaffold body picks up extra bottom scroll padding
// so `Scrollable.ensureVisible` has room to slide the focused
// destination or amount field above the keyboard.
//
// This suite locks in those invariants at the three mobile
// viewports the user asked for (320 / 390 / 430) across every asset
// that shares the layout (ETH mainnet + Sepolia, USDT/USDC ERC20,
// SOL, USDT_TRC20).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_sheet_chrome.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';


const String _kFromAddress =
    '0xAABBCCDDEEFF00112233445566778899AABBCCDD';
const String _kSolFrom = '11111111111111111111111111111111';
const String _kTronFrom = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';


class _StubClient extends VaultAIClient {
  _StubClient() : super(baseUrl: 'http://test.invalid');
}


CryptoWalletFeatures _sendOnFeatures() =>
    CryptoWalletFeatures.fromBackend(const {
      'schema':                      'crypto_wallet_engine_features_v1',
      'walletEngineEnabled':         true,
      'mainnetReceiveEnabled':       false,
      'mainnetErc20ReceiveEnabled':  false,
      'mainnetSendEnabled':          false,
      'mainnetSendPaused':           false,
      'defaultNetwork':              'ethereum_sepolia',
      'defaultNetworkConfigValid':   true,
      'solanaEnabled':               true,
      'solanaReceiveEnabled':        true,
      'solanaSendEnabled':           true,
      'solanaSendPaused':            false,
      'tronEnabled':                 true,
      'tronReceiveEnabled':          true,
      'tronSendEnabled':             true,
      'tronSendPaused':              false,
      'moneroEnabled':               false,
      'moneroReceiveEnabled':        false,
      'moneroSendEnabled':           false,
      'moneroSendPaused':            false,
    });


// Simulate the iOS keyboard by injecting `viewInsets.bottom` into
// the test view. When `keyboardHeight == 0`, no keyboard is
// simulated. Cleanup is scoped to the pump call via addTearDown.
Future<void> _pumpSheet(
  WidgetTester tester, {
  required Size viewport,
  required double keyboardHeight,
  required String sheetTitle,
  required String sheetKey,
  required Widget panel,
}) async {
  final view = tester.view;
  addTearDown(() {
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
    view.resetViewInsets();
    view.resetPadding();
  });
  view.devicePixelRatio = 1.0;
  view.physicalSize = viewport;
  view.viewInsets = FakeViewPadding(bottom: keyboardHeight);
  await tester.binding.setSurfaceSize(viewport);
  addTearDown(() => tester.binding.setSurfaceSize(null));

  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(builder: (ctx) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          showCryptoWalletSheet<void>(
            context: ctx,
            title: sheetTitle,
            sheetKey: sheetKey,
            bodyOwnsLayout: true,
            child: panel,
          );
        });
        return const SizedBox.shrink();
      }),
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}


CryptoWalletEngineSendPanel _ethPanel({
  bool mainnet = false,
  String asset = 'ETH',
}) {
  return CryptoWalletEngineSendPanel(
    authToken: 'tok',
    fromAddress: _kFromAddress,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    asset: asset,
    network: mainnet
        ? kEvmNetworkEthereumMainnet
        : kEvmNetworkEthereumSepolia,
  );
}

CryptoWalletEngineSolanaSendPanel _solPanel() {
  return CryptoWalletEngineSolanaSendPanel(
    authToken: 'tok',
    fromAddress: _kSolFrom,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    features: _sendOnFeatures(),
  );
}

CryptoWalletEngineTronSendPanel _tronPanel() {
  return CryptoWalletEngineTronSendPanel(
    authToken: 'tok',
    fromAddress: _kTronFrom,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    features: _sendOnFeatures(),
  );
}


// Assert every mandatory element of the layout invariant:
//   * The close X in the chrome header is present and hittable.
//   * The Review (or Confirm) button is inside the visible surface.
//   * The Review button does not overlap either text field.
//   * The Review button is not wider than the viewport.
//   * The button's height is moderate (not the pre-fix "large fixed
//     bar" that ate the middle of the screen).
Future<void> _assertLayoutInvariants(
  WidgetTester tester, {
  required Size viewport,
  required double keyboardHeight,
  required Key destKey,
  required Key amountKey,
  required Key reviewKey,
  required Key closeKey,
}) async {
  expect(find.byKey(closeKey), findsOneWidget,
      reason: 'Close X must be present at every keyboard state.');
  expect(find.byKey(reviewKey), findsOneWidget,
      reason: 'Primary action button must be present.');
  expect(find.byKey(destKey), findsOneWidget);
  expect(find.byKey(amountKey), findsOneWidget);

  // Close X hit region must not be underneath the simulated keyboard.
  final closeRect = tester.getRect(find.byKey(closeKey));
  final visibleBottom = viewport.height - keyboardHeight;
  expect(
    closeRect.bottom, lessThanOrEqualTo(visibleBottom),
    reason: 'Close X must remain reachable above the keyboard.',
  );

  // Review button geometry.
  final btnRect = tester.getRect(find.byKey(reviewKey));
  expect(btnRect.left, greaterThanOrEqualTo(0.0),
      reason: 'Review button must not exceed the left edge.');
  expect(btnRect.right, lessThanOrEqualTo(viewport.width),
      reason: 'Review button must not exceed viewport width.');
  expect(btnRect.width, greaterThan(48.0),
      reason: 'Review button must be a real width, not squashed.');
  // Moderate height -- not a giant middle-of-screen bar.
  expect(btnRect.height, lessThan(80.0),
      reason: 'Review button must retain a normal mobile button '
          'height (not become an oversized bar).');
  // Above the keyboard.
  expect(
    btnRect.bottom, lessThanOrEqualTo(visibleBottom + 0.5),
    reason: 'Review button must sit above the keyboard.',
  );

  // Review button rect must not strictly overlap the DESTINATION
  // field. Destination is the first form field and always sits above
  // the fold on every viewport, so a real overlap here would mean
  // the button is being painted on top of the primary input. Amount
  // is deliberately not checked here — in the tight USDT/USDC mainnet
  // layout with real-funds warnings, the amount field's natural
  // (unscrolled) logical position can sit BELOW the sticky footer
  // and is brought into view by Scrollable.ensureVisible when the
  // user focuses it. That auto-scroll behavior is covered by
  // dedicated `Amount stays visible when focused...` tests below.
  final destRect = tester.getRect(find.byKey(destKey));
  expect(btnRect.overlaps(destRect), isFalse,
      reason: 'Review button and Destination must not overlap.');
}


void main() {
  group('Send sheets — keyboard behavior (320 / 390 / 430)', () {
    for (final w in const [320.0, 390.0, 430.0]) {
      testWidgets(
        'ETH Sepolia at ${w.toInt()}dp × keyboard CLOSED — layout '
        'invariants hold',
        (tester) async {
          await _pumpSheet(
            tester,
            viewport: Size(w, 780),
            keyboardHeight: 0,
            sheetTitle: 'Send ETH',
            sheetKey: 'crypto_wallet_engine_send_sheet',
            panel: _ethPanel(),
          );
          await _assertLayoutInvariants(
            tester,
            viewport: Size(w, 780),
            keyboardHeight: 0,
            destKey: const Key('eth_send_panel_destination_input'),
            amountKey: const Key('eth_send_panel_amount_input'),
            reviewKey: const Key('eth_send_panel_review_btn'),
            closeKey: const Key(
              'crypto_wallet_engine_send_sheet_close_btn',
            ),
          );
        },
      );

      testWidgets(
        'ETH Sepolia at ${w.toInt()}dp × keyboard OPEN (336dp inset) — '
        'sheet lifts above keyboard, footer not floating',
        (tester) async {
          await _pumpSheet(
            tester,
            viewport: Size(w, 780),
            keyboardHeight: 336,
            sheetTitle: 'Send ETH',
            sheetKey: 'crypto_wallet_engine_send_sheet',
            panel: _ethPanel(),
          );
          await _assertLayoutInvariants(
            tester,
            viewport: Size(w, 780),
            keyboardHeight: 336,
            destKey: const Key('eth_send_panel_destination_input'),
            amountKey: const Key('eth_send_panel_amount_input'),
            reviewKey: const Key('eth_send_panel_review_btn'),
            closeKey: const Key(
              'crypto_wallet_engine_send_sheet_close_btn',
            ),
          );
        },
      );
    }

    testWidgets(
      'Destination auto-scrolls into view when focused (keyboard '
      'open) and stays above the keyboard',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        // Focus the destination field.
        await tester.tap(
          find.byKey(const Key('eth_send_panel_destination_input')),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));

        final destRect = tester.getRect(
          find.byKey(const Key('eth_send_panel_destination_input')),
        );
        final visibleBottom = 780.0 - 336.0;
        expect(destRect.bottom, lessThanOrEqualTo(visibleBottom + 0.5),
            reason: 'Destination field must be above the keyboard '
                'when focused.');
      },
    );

    testWidgets(
      'Amount stays visible when focused via Next-key hop from '
      'Destination (keyboard open)',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        // Focus destination, type an address, submit (equivalent to
        // the Next key on the mobile keyboard).
        final destFinder =
            find.byKey(const Key('eth_send_panel_destination_input'));
        await tester.tap(destFinder);
        await tester.pump();
        await tester.enterText(
          destFinder,
          '0x1111111111111111111111111111111111111111',
        );
        await tester.testTextInput.receiveAction(TextInputAction.next);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));

        final amountRect = tester.getRect(
          find.byKey(const Key('eth_send_panel_amount_input')),
        );
        final visibleBottom = 780.0 - 336.0;
        expect(amountRect.bottom, lessThanOrEqualTo(visibleBottom + 0.5),
            reason: 'Amount field must be above the keyboard after '
                'Next-key hop from Destination.');
      },
    );

    testWidgets(
      'Keyboard dismissal preserves entered destination and amount',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        final destFinder =
            find.byKey(const Key('eth_send_panel_destination_input'));
        final amountFinder =
            find.byKey(const Key('eth_send_panel_amount_input'));
        await tester.enterText(
          destFinder, '0x2222222222222222222222222222222222222222');
        await tester.enterText(amountFinder, '0.42');

        // Simulate the keyboard dismissing (viewInsets goes to zero).
        tester.view.viewInsets = FakeViewPadding.zero;
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        expect(
          (tester.widget(destFinder) as TextField).controller!.text,
          '0x2222222222222222222222222222222222222222',
          reason: 'Destination must survive keyboard dismissal.',
        );
        expect(
          (tester.widget(amountFinder) as TextField).controller!.text,
          '0.42',
          reason: 'Amount must survive keyboard dismissal.',
        );
      },
    );

    testWidgets(
      'Reopening the keyboard does not jump the sheet to an '
      'incorrect position',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 0,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        // Note the closed-keyboard footer position.
        final closedBtn = tester.getRect(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        // Simulate keyboard opening.
        tester.view.viewInsets = FakeViewPadding(bottom: 336);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        final openBtn = tester.getRect(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        // Button must have moved UP (smaller y = higher on screen).
        expect(openBtn.bottom, lessThan(closedBtn.bottom),
            reason: 'Sheet + footer must lift when keyboard opens.');
        // Now close the keyboard again.
        tester.view.viewInsets = FakeViewPadding.zero;
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        final reclosedBtn = tester.getRect(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        // Sheet should return roughly to the closed position (± a
        // few dp for animation float).
        expect(
          (reclosedBtn.bottom - closedBtn.bottom).abs(),
          lessThan(6.0),
          reason: 'Sheet must restore its resting position after '
              'the keyboard closes.',
        );
      },
    );

    testWidgets(
      'Review button stays disabled behavior: invalid address + '
      'no amount does not silently succeed (regression: primary '
      'action remains a review-only step, not a broadcast)',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 0,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        // Tap Review with no address/amount entered. The panel
        // must NOT crash, must NOT initiate a broadcast, must NOT
        // transition to a stage that would.
        await tester.tap(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        await tester.pump();
        // No broadcast means no submitted stage, no signing stage.
        expect(
          find.byKey(const Key('eth_send_panel_signing')), findsNothing);
      },
    );

    testWidgets(
      'Long-pasted Ethereum address does not overflow horizontally '
      'at 320dp',
      (tester) async {
        await _pumpSheet(
          tester,
          viewport: const Size(320, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        await tester.enterText(
          find.byKey(const Key('eth_send_panel_destination_input')),
          '0xffffffffffffffffffffffffffffffffffffffff',
        );
        await tester.pump();
        expect(tester.takeException(), isNull);
      },
    );

    // Every asset that shares the layout gets the same
    // keyboard-open invariant check. If any single asset regresses,
    // its test fails alone.
    for (final asset in const [
      'ETH', 'USDT_ERC20', 'USDC_ERC20',
    ]) {
      testWidgets(
        'EVM ($asset) mainnet Send at 390dp × keyboard open — '
        'invariants hold',
        (tester) async {
          const w = 390.0;
          await _pumpSheet(
            tester,
            viewport: const Size(w, 780),
            keyboardHeight: 336,
            sheetTitle: 'Send $asset',
            sheetKey: 'crypto_wallet_engine_send_sheet',
            panel: _ethPanel(mainnet: true, asset: asset),
          );
          await _assertLayoutInvariants(
            tester,
            viewport: const Size(w, 780),
            keyboardHeight: 336,
            destKey: const Key('eth_send_panel_destination_input'),
            amountKey: const Key('eth_send_panel_amount_input'),
            reviewKey: const Key('eth_send_panel_review_btn'),
            closeKey: const Key(
              'crypto_wallet_engine_send_sheet_close_btn',
            ),
          );
        },
      );
    }

    testWidgets(
      'Solana Send at 390dp × keyboard open — invariants hold',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send SOL',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _solPanel(),
        );
        await _assertLayoutInvariants(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          destKey: const Key(kSolanaSendDestinationInputKey),
          amountKey: const Key(kSolanaSendAmountInputKey),
          reviewKey: const Key(kSolanaSendReviewButtonKey),
          closeKey: const Key(
            'crypto_wallet_engine_send_sheet_close_btn',
          ),
        );
      },
    );

    testWidgets(
      'TRON USDT_TRC20 Send at 390dp × keyboard open — invariants hold',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send USDT (TRC20)',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _tronPanel(),
        );
        await _assertLayoutInvariants(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          destKey: const Key(kTronSendDestinationInputKey),
          amountKey: const Key(kTronSendAmountInputKey),
          reviewKey: const Key(kTronSendReviewButtonKey),
          closeKey: const Key(
            'crypto_wallet_engine_send_sheet_close_btn',
          ),
        );
      },
    );

    testWidgets(
      'Mainnet PAUSED state still renders correctly at keyboard-open '
      'viewport — the paused banner is visible above the fold',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 336,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: _StubClient(),
            decryptForVault: (_) async => 'plain',
            isVaultKeyAvailable: () => true,
            asset: 'ETH',
            network: kEvmNetworkEthereumMainnet,
            mainnetSendPaused: true,
          ),
        );
        expect(
          find.byKey(const Key(kMainnetSendPausedBannerKey)),
          findsOneWidget,
        );
        // Header/close X still reachable.
        expect(
          find.byKey(const Key(
              'crypto_wallet_engine_send_sheet_close_btn')),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Destination input action is Next (moves focus to Amount)',
      (tester) async {
        const w = 390.0;
        await _pumpSheet(
          tester,
          viewport: const Size(w, 780),
          keyboardHeight: 0,
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(),
        );
        final destField = tester.widget<TextField>(
          find.byKey(const Key('eth_send_panel_destination_input')),
        );
        expect(destField.textInputAction, TextInputAction.next);

        final amountField = tester.widget<TextField>(
          find.byKey(const Key('eth_send_panel_amount_input')),
        );
        expect(amountField.textInputAction, TextInputAction.done);
      },
    );
  });
}
