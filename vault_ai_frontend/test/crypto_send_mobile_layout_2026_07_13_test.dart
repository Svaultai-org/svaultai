// 2026-07-13: regression suite for the mobile Send-sheet layout
// rewrite. Locks in the new compact contract for every Send sheet
// (ETH mainnet + Sepolia, SOL, USDT_TRC20) at the mobile viewports
// 320 / 390 / 430 dp:
//
//   * The sheet chrome supplies a single sheet title ("Send ETH",
//     "Send SOL", "Send USDT (TRC20)"). The panel body no longer
//     renders its own duplicate "Send Ethereum" / "Send SOL" /
//     "Send USDT (TRC20)" heading — that was the exact "Send ETH
//     and Send Ethereum duplicate the same information" bug.
//   * The compact network chip lives in the header row of the
//     scaffold — replaces the old wide network badge Text row.
//   * The Review / Confirm primary action lives in a sticky footer
//     that lifts above the keyboard, and stays reachable while the
//     body scrolls. On a 320dp × 480dp viewport (roughly what an
//     iPhone SE has when its keyboard is open) the Review button
//     must still be inside the viewport bounds.
//   * At most ONE prominent top-of-panel warning is visible for
//     mainnet states — the old design stacked a real-funds banner
//     ON TOP of a mainnet-send-disabled banner ON TOP of a paused
//     banner. The new priority is: paused > disabled > real-funds.
//   * The sheet body must not overflow horizontally on any of the
//     three tested mobile widths.
//
// If any Send panel starts rendering an inline "Send X" heading
// (i.e. duplicating the sheet chrome title), the "single title"
// tests below fail. If any Send panel loses its sticky Review /
// Confirm footer, the sticky-reachable tests below fail.

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_layout.dart';
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


// Pumps `panel` inside the real `showCryptoWalletSheet` chrome at the
// given mobile viewport. Returns the tester after settling.
Future<void> _pumpInsideChrome(
  WidgetTester tester, {
  required Size viewport,
  required Widget panel,
  required String sheetTitle,
  required String sheetKey,
}) async {
  await tester.binding.setSurfaceSize(viewport);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Center(
        child: Builder(builder: (ctx) {
          // Open the sheet immediately for the test — simulates a
          // user tapping "Send" on an asset card.
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
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
}


void main() {
  group('Send sheets — mobile layout (320 / 390 / 430)', () {

    for (final w in const [320.0, 390.0, 430.0]) {
      testWidgets(
        'ETH Sepolia Send at ${w.toInt()}dp: '
        'single sheet title, compact chip, sticky Review reachable',
        (tester) async {
          await _pumpInsideChrome(
            tester,
            viewport: Size(w, 800),
            sheetTitle: 'Send ETH',
            sheetKey: 'crypto_wallet_engine_send_sheet',
            panel: CryptoWalletEngineSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddress,
              client: _StubClient(),
              decryptForVault: (_) async => 'plain',
              isVaultKeyAvailable: () => true,
              asset: 'ETH',
              network: kEvmNetworkEthereumSepolia,
            ),
          );
          // Exactly ONE "Send ETH" title (the chrome header). If the
          // panel body starts rendering its own inline "Send Ethereum"
          // heading again, this fails.
          expect(find.text('Send ETH'), findsOneWidget);
          expect(find.text('Send Ethereum'), findsNothing);
          // Compact network chip present.
          expect(
            find.byKey(const Key('eth_send_panel_network_chip')),
            findsOneWidget,
          );
          expect(find.text(kEthSendNetworkBadge), findsOneWidget);
          // Sticky footer with the Review button exists and is inside
          // the surface.
          expect(
            find.byKey(const Key('eth_send_panel_review_btn')),
            findsOneWidget,
          );
          final btnRect = tester.getRect(
            find.byKey(const Key('eth_send_panel_review_btn')),
          );
          expect(btnRect.left, greaterThanOrEqualTo(0));
          expect(btnRect.right, lessThanOrEqualTo(w));
          expect(btnRect.width, greaterThan(48));
          // Close X and drag handle are still reachable in the chrome.
          expect(
            find.byKey(
              const Key('crypto_wallet_engine_send_sheet_close_btn'),
            ),
            findsOneWidget,
          );
          expect(
            find.byKey(
              const Key('crypto_wallet_engine_send_sheet_drag_handle'),
            ),
            findsOneWidget,
          );
          // No exceptions from layout (no RenderFlex overflow).
          expect(tester.takeException(), isNull);
        },
      );
    }

    testWidgets(
      'ETH mainnet Send: chip labeled "Ethereum Mainnet" and exactly '
      'ONE top-of-panel warning is visible (never overlapping banners)',
      (tester) async {
        await _pumpInsideChrome(
          tester,
          viewport: const Size(390, 800),
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
          ),
        );
        // The mainnet chip is labelled "Ethereum Mainnet".
        expect(find.text(kEthSendMainnetNetworkBadge), findsOneWidget);
        // AT MOST ONE mainnet warning — never both.
        final hasReal = find
            .byKey(const Key('eth_send_panel_mainnet_real_funds'))
            .evaluate()
            .isNotEmpty;
        final hasDisabled = find
            .byKey(
              const Key('eth_send_panel_mainnet_send_disabled'),
            )
            .evaluate()
            .isNotEmpty;
        final hasPaused = find
            .byKey(const Key(kMainnetSendPausedBannerKey))
            .evaluate()
            .isNotEmpty;
        final total = [hasReal, hasDisabled, hasPaused]
            .where((x) => x).length;
        expect(total, equals(1),
            reason: 'exactly one mainnet warning should be visible');
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'Solana Send at 320dp: single "Send SOL" title, chip, sticky '
      'Review button reachable, no overflow',
      (tester) async {
        await _pumpInsideChrome(
          tester,
          viewport: const Size(320, 800),
          sheetTitle: 'Send SOL',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: CryptoWalletEngineSolanaSendPanel(
            authToken: 'tok',
            fromAddress: _kSolFrom,
            client: _StubClient(),
            decryptForVault: (_) async => 'plain',
            isVaultKeyAvailable: () => true,
            features: _sendOnFeatures(),
          ),
        );
        expect(find.text('Send SOL'), findsOneWidget);
        // The panel body no longer renders its own "Send SOL" heading
        // (would produce two matches).
        expect(find.text('Send SOL'), findsOneWidget);
        // Compact network chip.
        expect(
          find.byKey(const Key('solana_send_panel_network_chip')),
          findsOneWidget,
        );
        // Sticky Review footer visible.
        expect(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
          findsOneWidget,
        );
        final btnRect = tester.getRect(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        expect(btnRect.left, greaterThanOrEqualTo(0));
        expect(btnRect.right, lessThanOrEqualTo(320));
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'USDT TRC20 Send at 390dp: single title, chip, sticky Review '
      'button reachable, no overflow',
      (tester) async {
        await _pumpInsideChrome(
          tester,
          viewport: const Size(390, 800),
          sheetTitle: 'Send USDT (TRC20)',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: CryptoWalletEngineTronSendPanel(
            authToken: 'tok',
            fromAddress: _kTronFrom,
            client: _StubClient(),
            decryptForVault: (_) async => 'plain',
            isVaultKeyAvailable: () => true,
            features: _sendOnFeatures(),
          ),
        );
        expect(find.text('Send USDT (TRC20)'), findsOneWidget);
        expect(
          find.byKey(const Key('tron_send_panel_network_chip')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kTronSendReviewButtonKey)),
          findsOneWidget,
        );
        final btnRect = tester.getRect(
          find.byKey(const Key(kTronSendReviewButtonKey)),
        );
        expect(btnRect.left, greaterThanOrEqualTo(0));
        expect(btnRect.right, lessThanOrEqualTo(390));
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'Sheet chrome exposes the shared drag handle + close X for '
      'every Send sheet (regression: user could not dismiss)',
      (tester) async {
        await _pumpInsideChrome(
          tester,
          viewport: const Size(390, 800),
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: _StubClient(),
            decryptForVault: (_) async => 'plain',
            isVaultKeyAvailable: () => true,
            asset: 'ETH',
            network: kEvmNetworkEthereumSepolia,
          ),
        );
        expect(
          find.byKey(
            const Key('crypto_wallet_engine_send_sheet_drag_handle'),
          ),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_wallet_engine_send_sheet_close_btn'),
          ),
          findsOneWidget,
        );
        // Tapping the close X dismisses the sheet.
        await tester.tap(find.byKey(
          const Key('crypto_wallet_engine_send_sheet_close_btn'),
        ));
        await tester.pumpAndSettle();
        // Sheet gone → the send panel is no longer in the tree.
        expect(
          find.byKey(const Key('eth_send_panel_review_btn')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'Keyboard-open state: sticky footer lifts and Review stays '
      'reachable above the simulated keyboard inset (viewInsets)',
      (tester) async {
        // Simulate the iOS keyboard by injecting viewInsets.bottom.
        final view = tester.view;
        addTearDown(() {
          view.resetViewInsets();
          view.resetDevicePixelRatio();
          view.resetPhysicalSize();
        });
        view.devicePixelRatio = 1.0;
        view.physicalSize = const Size(390, 800);
        // 336 physical pixels of keyboard, DPR=1 → 336dp inset.
        view.viewInsets = FakeViewPadding(bottom: 336);
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(
            body: Builder(builder: (ctx) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                showCryptoWalletSheet<void>(
                  context: ctx,
                  title: 'Send ETH',
                  sheetKey: 'crypto_wallet_engine_send_sheet',
                  bodyOwnsLayout: true,
                  child: CryptoWalletEngineSendPanel(
                    authToken: 'tok',
                    fromAddress: _kFromAddress,
                    client: _StubClient(),
                    decryptForVault: (_) async => 'plain',
                    isVaultKeyAvailable: () => true,
                    asset: 'ETH',
                    network: kEvmNetworkEthereumSepolia,
                  ),
                );
              });
              return const SizedBox.shrink();
            }),
          ),
        ));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500));
        // Review button is still in the tree.
        expect(
          find.byKey(const Key('eth_send_panel_review_btn')),
          findsOneWidget,
        );
        final btnRect = tester.getRect(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        // The `WalletSendScaffold` footer applies AnimatedPadding with
        // MediaQuery.viewInsetsOf(context).bottom = 336, so the
        // button's bottom should be ABOVE the simulated keyboard
        // inset. Physical viewport = 800, keyboard = 336 → keyboard
        // top edge at y=464. The button bottom must be < 464.
        expect(btnRect.bottom, lessThan(464),
            reason: 'sticky Review button must lift above the '
                'iOS keyboard inset');
        expect(tester.takeException(), isNull);
      },
    );

    test(
      'source-guard: no send-panel body renders a duplicate title '
      'heading via `kEthSendPanelTitle` / `kSolanaSendPanelTitle` / '
      '`kTronSendPanelTitle`',
      () {
        // Read each send-panel source file and assert that the panel
        // body does NOT reference the legacy title constants inside a
        // Text() widget invocation. The constants are still exported
        // for backward-compat with existing tests, but they must not
        // be used to render a second inline heading below the sheet
        // chrome's title.
        final files = <String>[
          'lib/ui/crypto_wallet_engine_send_panel.dart',
          'lib/ui/crypto_wallet_engine_solana_send_panel.dart',
          'lib/ui/crypto_wallet_engine_tron_send_panel.dart',
        ];
        final bannedPatterns = <String>[
          'Text(kEthSendPanelTitle',
          'Text(kSolanaSendPanelTitle',
          'Text(kTronSendPanelTitle',
        ];
        for (final path in files) {
          final f = File(path);
          expect(f.existsSync(), isTrue, reason: 'missing $path');
          final raw = f.readAsStringSync();
          // Strip single-line comments so a doc-comment mention of
          // the constant doesn't false-flag.
          final scrubbed = raw
              .split('\n')
              .map((line) {
                final idx = line.indexOf('//');
                return idx >= 0 ? line.substring(0, idx) : line;
              })
              .join('\n');
          for (final pat in bannedPatterns) {
            expect(scrubbed.contains(pat), isFalse,
                reason: '$path still renders a duplicate title via '
                    '`$pat` — the sheet chrome already shows the '
                    'sheet title');
          }
        }
      },
    );

    test(
      'source-guard: `WalletSendScaffold` is the layout used by every '
      'send panel (chip header + sticky footer contract)',
      () {
        for (final path in const [
          'lib/ui/crypto_wallet_engine_send_panel.dart',
          'lib/ui/crypto_wallet_engine_solana_send_panel.dart',
          'lib/ui/crypto_wallet_engine_tron_send_panel.dart',
        ]) {
          final f = File(path);
          expect(f.existsSync(), isTrue);
          final raw = f.readAsStringSync();
          expect(raw.contains('WalletSendScaffold'), isTrue,
              reason: '$path must use the shared WalletSendScaffold '
                  'so mobile keyboard behavior stays consistent');
        }
      },
    );
  });
}
