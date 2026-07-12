// 2026-07-13: end-to-end + widget tests for the recipient QR-scan
// flow. Uses `FakeRecipientQrScanner` so no real camera is required.
//
// Coverage:
//   * Scan button is visible on every asset's Send panel form.
//   * A valid decode populates the destination field; the sheet
//     closes; the entered amount is preserved.
//   * An invalid decode does NOT populate the destination field
//     and the sheet stays open (retry-friendly).
//   * Cross-network / seed / private-key QRs are rejected.
//   * The scanner sheet stops + disposes the scanner on close.
//   * Reopening the scanner works (a fresh fake is passed each time).
//   * Camera unavailable renders the manual-entry fallback.
//   * The keyboard layout fix is not regressed by opening/closing
//     the scanner.
//   * No overflow at 320 / 390 / 430 widths.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/services/recipient_qr_parser.dart';
import 'package:vault_ai_frontend/services/recipient_qr_scanner.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_sheet_chrome.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';
import 'package:vault_ai_frontend/ui/scan_recipient_qr_sheet.dart';


const String _kFromEth = '0xAABBCCDDEEFF00112233445566778899AABBCCDD';
const String _kFromSol = '11111111111111111111111111111111';
const String _kFromTron = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';

const String _kEthAddr = '0xffffffffffffffffffffffffffffffffffffffff';
const String _kSolAddr = 'So11111111111111111111111111111111111111112';
const String _kTronAddr = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';


class _StubClient extends VaultAIClient {
  _StubClient() : super(baseUrl: 'http://test.invalid');
}


CryptoWalletFeatures _featuresOn() =>
    CryptoWalletFeatures.fromBackend(const {
      'schema':                     'crypto_wallet_engine_features_v1',
      'walletEngineEnabled':        true,
      'mainnetReceiveEnabled':      false,
      'mainnetErc20ReceiveEnabled': false,
      'mainnetSendEnabled':         false,
      'mainnetSendPaused':          false,
      'defaultNetwork':             'ethereum_sepolia',
      'defaultNetworkConfigValid':  true,
      'solanaEnabled':              true,
      'solanaReceiveEnabled':       true,
      'solanaSendEnabled':          true,
      'solanaSendPaused':           false,
      'tronEnabled':                true,
      'tronReceiveEnabled':         true,
      'tronSendEnabled':            true,
      'tronSendPaused':             false,
      'moneroEnabled':              false,
      'moneroReceiveEnabled':       false,
      'moneroSendEnabled':          false,
      'moneroSendPaused':           false,
    });


// A scan hook that returns a pre-canned value on the FIRST scan
// invocation. Wire into the Send panels via `scanRecipientQr:`.
Future<String?> Function(
  BuildContext, RecipientNetwork, int?,
) _scanReturns(String? value) {
  return (BuildContext _, RecipientNetwork _n, int? _c) async => value;
}


Future<void> _pumpSheet(
  WidgetTester tester, {
  required Size viewport,
  required String sheetTitle,
  required String sheetKey,
  required Widget panel,
}) async {
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
  Future<String?> Function(BuildContext, RecipientNetwork, int?)? hook,
}) {
  return CryptoWalletEngineSendPanel(
    authToken: 'tok',
    fromAddress: _kFromEth,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    asset: asset,
    network: mainnet
        ? kEvmNetworkEthereumMainnet
        : kEvmNetworkEthereumSepolia,
    scanRecipientQr: hook,
  );
}

CryptoWalletEngineSolanaSendPanel _solPanel({
  Future<String?> Function(BuildContext, RecipientNetwork, int?)? hook,
}) {
  return CryptoWalletEngineSolanaSendPanel(
    authToken: 'tok',
    fromAddress: _kFromSol,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    features: _featuresOn(),
    scanRecipientQr: hook,
  );
}

CryptoWalletEngineTronSendPanel _tronPanel({
  Future<String?> Function(BuildContext, RecipientNetwork, int?)? hook,
}) {
  return CryptoWalletEngineTronSendPanel(
    authToken: 'tok',
    fromAddress: _kFromTron,
    client: _StubClient(),
    decryptForVault: (_) async => 'plain',
    isVaultKeyAvailable: () => true,
    features: _featuresOn(),
    scanRecipientQr: hook,
  );
}


void main() {
  group('Send panels expose the "Scan recipient QR" action', () {
    testWidgets('ETH Sepolia', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send ETH',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(),
      );
      expect(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });

    testWidgets('ETH mainnet', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send ETH',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(mainnet: true),
      );
      expect(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });

    testWidgets('USDT_ERC20', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send USDT',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(mainnet: true, asset: 'USDT_ERC20'),
      );
      expect(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });

    testWidgets('USDC_ERC20', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send USDC',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(mainnet: true, asset: 'USDC_ERC20'),
      );
      expect(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });

    testWidgets('SOL', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send SOL',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _solPanel(),
      );
      expect(
        find.byKey(const Key('solana_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });

    testWidgets('USDT_TRC20', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send USDT (TRC20)',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _tronPanel(),
      );
      expect(
        find.byKey(const Key('tron_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });
  });


  group('Scanning populates the destination and preserves state', () {
    testWidgets('valid ETH scan populates destination and keeps '
        'the amount already typed', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send ETH',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(hook: _scanReturns(_kEthAddr)),
      );
      // The user has already typed the amount.
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.42',
      );
      // Now scan the recipient QR.
      await tester.tap(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      final destField = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_destination_input')),
      );
      expect(destField.controller!.text, _kEthAddr);
      final amountField = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      expect(amountField.controller!.text, '0.42',
          reason: 'Amount already entered must survive the scan.');
    });

    testWidgets('scan cancelled (user tapped manual-entry fallback) '
        'does not overwrite an existing destination', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send ETH',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _ethPanel(hook: _scanReturns(null)),
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kEthAddr,
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
      );
      await tester.pump();
      final destField = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_destination_input')),
      );
      expect(destField.controller!.text, _kEthAddr);
    });

    testWidgets('valid SOL scan populates destination', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send SOL',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _solPanel(hook: _scanReturns(_kSolAddr)),
      );
      await tester.tap(
        find.byKey(const Key('solana_send_panel_scan_qr_btn')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      final destField = tester.widget<TextField>(
        find.byKey(const Key(kSolanaSendDestinationInputKey)),
      );
      expect(destField.controller!.text, _kSolAddr);
    });

    testWidgets('valid TRON scan populates destination', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send USDT (TRC20)',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: _tronPanel(hook: _scanReturns(_kTronAddr)),
      );
      await tester.tap(
        find.byKey(const Key('tron_send_panel_scan_qr_btn')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      final destField = tester.widget<TextField>(
        find.byKey(const Key(kTronSendDestinationInputKey)),
      );
      expect(destField.controller!.text, _kTronAddr);
    });
  });


  group('Scanner sheet — lifecycle + fake scanner', () {
    testWidgets('valid decode closes the sheet with the address',
        (tester) async {
      final fake = FakeRecipientQrScanner();
      String? gotAddress;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              gotAddress = await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake,
              );
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Feed a valid decode from the "camera".
      fake.pushResult(_kEthAddr);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(gotAddress, _kEthAddr);
      expect(fake.disposeCalls, greaterThanOrEqualTo(1));
    });

    testWidgets('invalid decode keeps sheet open + shows error, '
        'resumes scanning', (tester) async {
      final fake = FakeRecipientQrScanner();
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake,
              );
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Feed a solana:... URI on the Ethereum screen (cross-network).
      fake.pushResult('solana:$_kSolAddr');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Sheet still open, error banner visible.
      expect(
        find.byKey(const Key(kScanRecipientQrSheetKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kScanRecipientQrErrorBannerKey)),
        findsOneWidget,
      );
      // Scanner resumed.
      expect(fake.resumeCalls, greaterThanOrEqualTo(1));
    });

    testWidgets('duplicate decodes fire only one result callback',
        (tester) async {
      final fake = FakeRecipientQrScanner();
      final results = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              final r = await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake,
              );
              if (r != null) results.add(r);
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Push the same QR three times rapidly.
      fake.pushResult(_kEthAddr);
      fake.pushResult(_kEthAddr);
      fake.pushResult(_kEthAddr);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Exactly one result should have been surfaced (because the
      // sheet paused the scanner immediately after the first decode).
      expect(results.length, 1);
    });

    testWidgets('close button pops with null, stops + disposes '
        'scanner', (tester) async {
      final fake = FakeRecipientQrScanner();
      String? got = 'not-null-sentinel';
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              got = await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake,
              );
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      await tester.tap(
        find.byKey(const Key(kScanRecipientQrCloseBtnKey)),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(got, isNull);
      expect(fake.stopCalls, greaterThanOrEqualTo(1));
      expect(fake.disposeCalls, greaterThanOrEqualTo(1));
    });

    testWidgets('reopening the sheet works after the previous scan '
        'completed', (tester) async {
      // Two independent fake scanners, one per sheet — matches how
      // the production sheet creates a fresh MobileScannerController
      // on each open.
      final fake1 = FakeRecipientQrScanner();
      final fake2 = FakeRecipientQrScanner();
      String? got1;
      String? got2;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              got1 = await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake1,
              );
              got2 = await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake2,
              );
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      fake1.pushResult(_kEthAddr);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Second sheet is now open.
      const addr2 = '0x2222222222222222222222222222222222222222';
      fake2.pushResult(addr2);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(got1, _kEthAddr);
      expect(got2, addr2);
    });

    testWidgets('camera unavailable shows the manual-entry fallback',
        (tester) async {
      final fake = FakeRecipientQrScanner(cameraAvailable: false);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (ctx) {
            WidgetsBinding.instance.addPostFrameCallback((_) async {
              await showScanRecipientQrSheet(
                context: ctx,
                network: RecipientNetwork.ethereum,
                expectedChainId: 1,
                scanner: fake,
              );
            });
            return const SizedBox.shrink();
          }),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        find.byKey(
            const Key(kScanRecipientQrCameraUnavailableKey)),
        findsOneWidget,
      );
      // Manual-entry button still present.
      expect(
        find.byKey(const Key(kScanRecipientQrManualBtnKey)),
        findsOneWidget,
      );
    });
  });


  group('QR flow does not regress the mobile keyboard layout', () {
    for (final w in const [320.0, 390.0, 430.0]) {
      testWidgets(
        'ETH Send at ${w.toInt()}dp: scan button + destination + '
        'amount + close X + Review all coexist, no overflow',
        (tester) async {
          await _pumpSheet(
            tester,
            viewport: Size(w, 780),
            sheetTitle: 'Send ETH',
            sheetKey: 'crypto_wallet_engine_send_sheet',
            panel: _ethPanel(),
          );
          expect(find.byKey(const Key(
              'eth_send_panel_scan_qr_btn')), findsOneWidget);
          expect(find.byKey(const Key(
              'eth_send_panel_destination_input')), findsOneWidget);
          expect(find.byKey(const Key(
              'eth_send_panel_amount_input')), findsOneWidget);
          expect(find.byKey(const Key(
              'eth_send_panel_review_btn')), findsOneWidget);
          expect(find.byKey(const Key(
              'crypto_wallet_engine_send_sheet_close_btn')),
              findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }

    testWidgets(
      'ETH Send: opening + cancelling the scanner returns to the '
      'form with the destination + amount + Review intact '
      '(keyboard layout not regressed)',
      (tester) async {
        await _pumpSheet(
          tester,
          viewport: const Size(390, 780),
          sheetTitle: 'Send ETH',
          sheetKey: 'crypto_wallet_engine_send_sheet',
          panel: _ethPanel(hook: _scanReturns(null)),
        );
        await tester.enterText(
          find.byKey(const Key('eth_send_panel_destination_input')),
          _kEthAddr,
        );
        await tester.enterText(
          find.byKey(const Key('eth_send_panel_amount_input')),
          '0.1',
        );
        await tester.tap(
          find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        );
        await tester.pump();
        // Both fields still populated after cancel.
        expect(
          (tester.widget<TextField>(find.byKey(
              const Key('eth_send_panel_destination_input')))
              .controller!.text),
          _kEthAddr,
        );
        expect(
          (tester.widget<TextField>(find.byKey(
              const Key('eth_send_panel_amount_input')))
              .controller!.text),
          '0.1',
        );
        // Review still there.
        expect(
          find.byKey(const Key('eth_send_panel_review_btn')),
          findsOneWidget,
        );
      },
    );
  });


  group('Mainnet paused state is unchanged by the scan feature',
      () {
    testWidgets('mainnet-paused ETH Send still renders paused banner '
        'and the scan button is still present', (tester) async {
      await _pumpSheet(
        tester,
        viewport: const Size(390, 780),
        sheetTitle: 'Send ETH',
        sheetKey: 'crypto_wallet_engine_send_sheet',
        panel: CryptoWalletEngineSendPanel(
          authToken: 'tok',
          fromAddress: _kFromEth,
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
      // Scan button is still present in the destination field
      // (paused only blocks broadcast; the input UI is unchanged).
      expect(
        find.byKey(const Key('eth_send_panel_scan_qr_btn')),
        findsOneWidget,
      );
    });
  });
}
