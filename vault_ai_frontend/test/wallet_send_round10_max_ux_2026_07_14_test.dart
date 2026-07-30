// 2026-07-14 (Round 10 — Max UX fix): regression suite for the
// destination-first, fee-estimate-driven Max button.
//
// Previous behavior (Round 8): Max required a persisted draft to
// know the fee. Users had to enter an amount and tap Review first —
// unacceptable UX for a wallet.
//
// New behavior (Round 10):
//   * ETH Max requires a valid destination address (fee estimate
//     depends on it), then fetches verified balance + calls the
//     fee-estimate endpoint. BigInt only. No hard-coded fallback.
//   * ERC-20 Max = full verified token base-unit balance. Never
//     subtracts ETH. Gas is checked separately by the pre-sign
//     exact-fee gate.
//   * SOL Max requires a valid destination + verified lamports +
//     fee-estimate call. BigInt only.
//   * USDT-TRC20 Max = full verified token base-unit balance.
//     Never subtracts TRX. Draft-time TRX check is the pre-sign
//     gate's responsibility.
//   * No encrypted secret / signing / broadcast during Max.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';


const List<LocalizationsDelegate<Object?>> _l10n = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

CryptoWalletFeatures _solFeatures() =>
    CryptoWalletFeatures.fromBackend(const <String, dynamic>{
      'walletEngineEnabled': true,
      'solanaEnabled': true,
      'solanaSendEnabled': true,
    });

CryptoWalletFeatures _tronFeatures() =>
    CryptoWalletFeatures.fromBackend(const <String, dynamic>{
      'walletEngineEnabled': true,
      'tronEnabled': true,
      'tronSendEnabled': true,
      'tronUsdtContractConfigured': true,
    });

const String _kEthFrom = '0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855';
const String _kEthDest = '0x7C49215A2cB86aaC3e6308EA4D6206912578e870';
const String _kSolFrom = 'So11111111111111111111111111111111111111112';
const String _kSolDest = '11111111111111111111111111111111';
const String _kTrnFrom = 'TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq';


/// Fake API client that records fee-estimate calls and returns a
/// scriptable response.
class _MaxUxClient extends VaultAIClient {
  final Map<String, dynamic>? feeEstimateResponse;
  final Object? feeEstimateThrow;
  int feeEstimateCallCount = 0;
  int draftCallCount = 0;
  int encryptedSecretCallCount = 0;
  int broadcastCallCount = 0;
  Map<String, String>? lastFeeEstimateRequest;

  _MaxUxClient({
    this.feeEstimateResponse,
    this.feeEstimateThrow,
  }) : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>>
      postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
  }) async {
    feeEstimateCallCount++;
    lastFeeEstimateRequest = {
      'network':        network,
      'fromAddress':    fromAddress,
      'destinationAddress': destinationAddress,
      'asset':          asset,
    };
    if (feeEstimateThrow != null) {
      throw feeEstimateThrow!;
    }
    return feeEstimateResponse ?? const <String, dynamic>{};
  }

  @override
  Future<Map<String, dynamic>>
      createCryptoWalletSendDraftNetwork({
    required String network, required String asset,
    required String authToken, required String fromAddress,
    required String destinationAddress,
    String? amountEth, String? amountSol, String? amountUsdt,
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    draftCallCount++;
    return const {'status': 'draft_ready'};
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset, required String authToken,
    required String fromAddress, required String destinationAddress,
    required String amountEth,
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    draftCallCount++;
    return const {'status': 'draft_ready'};
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset, required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return const {
      'wallet_engine': 'encrypted_secret_ready',
      'encryptedWalletSecret': 'CT',
    };
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletEncryptedSecretNetwork({
    required String network, required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return const {
      'wallet_engine': 'encrypted_secret_ready',
      'encryptedWalletSecret': 'CT',
    };
  }

  @override
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransactionNetwork({
    required String network, required String asset,
    required String authToken, required Object signedTransaction,
    String? idempotencyKey, String? draftId,
  }) async {
    broadcastCallCount++;
    return const {};
  }

  @override
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransaction({
    required String asset, required String authToken,
    required Object signedTransaction,
  }) async {
    broadcastCallCount++;
    return const {};
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletDraftExpiryNetwork({
    required String network, required String draftId,
    required String authToken,
  }) async {
    return const {'expired': false};
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletOutgoingHistoryNetwork({
    required String network, required String authToken,
  }) async =>
      const {'status': 'ok', 'outgoing': []};

  @override
  Future<Map<String, dynamic>> getCryptoWalletTransactionStatusNetwork({
    required String network, required String asset,
    required String txHash, required String authToken,
  }) async =>
      const {'transactionStatus': 'pending'};
}


Future<void> _pumpEth(
  WidgetTester tester, {
  required _MaxUxClient client,
  required String asset,
  Future<double?> Function()? fetchAvailableBalance,
  Future<BigInt?> Function()? fetchAvailableBalanceWei,
  Future<BigInt?> Function()? fetchEthBalanceWei,
}) async {
  await tester.binding.setSurfaceSize(const Size(390, 2400));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _l10n,
    home: Scaffold(
      body: CryptoWalletEngineSendPanel(
        authToken: 'tok',
        fromAddress: _kEthFrom,
        client: client,
        decryptForVault: (_) async => '0x${'11' * 32}',
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        asset: asset,
        network: kEvmNetworkEthereumSepolia,
        fetchAvailableBalance:
            fetchAvailableBalance ?? (() async => 1.0),
        fetchAvailableBalanceWei: fetchAvailableBalanceWei,
        fetchEthBalanceWei: fetchEthBalanceWei,
      ),
    ),
  ));
  await tester.pump();
}

Future<void> _pumpSol(
  WidgetTester tester, {
  required _MaxUxClient client,
  Future<BigInt?> Function()? fetchAvailableLamports,
}) async {
  await tester.binding.setSurfaceSize(const Size(390, 2400));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _l10n,
    home: Scaffold(
      body: CryptoWalletEngineSolanaSendPanel(
        authToken: 'tok',
        fromAddress: _kSolFrom,
        client: client,
        decryptForVault: (_) async => '{"secretKeyBase58":"aa"}',
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        features: _solFeatures(),
        fetchAvailableLamports: fetchAvailableLamports,
      ),
    ),
  ));
  await tester.pump();
}

Future<void> _pumpTron(
  WidgetTester tester, {
  required _MaxUxClient client,
  Future<BigInt?> Function()? fetchAvailableTokenBaseUnits,
  Future<BigInt?> Function()? fetchTrxBalanceSun,
}) async {
  await tester.binding.setSurfaceSize(const Size(390, 2400));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _l10n,
    home: Scaffold(
      body: CryptoWalletEngineTronSendPanel(
        authToken: 'tok',
        fromAddress: _kTrnFrom,
        client: client,
        decryptForVault: (_) async => '{"privateKeyHex":"deadbeef"}',
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        features: _tronFeatures(),
        fetchAvailableTokenBaseUnits: fetchAvailableTokenBaseUnits,
        fetchTrxBalanceSun: fetchTrxBalanceSun,
      ),
    ),
  ));
  await tester.pump();
}


Future<void> _enterEthDest(WidgetTester tester, String dest) async {
  await tester.enterText(
    find.byKey(const Key('eth_send_panel_destination_input')),
    dest,
  );
  await tester.pumpAndSettle();
}

Future<void> _enterSolDest(WidgetTester tester, String dest) async {
  await tester.enterText(
    find.byKey(const Key('solana_send_panel_destination_input')),
    dest,
  );
  await tester.pumpAndSettle();
}


Future<String> _readLibFile(String rel) async {
  return File('${Directory.current.path}/lib/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  group('Round 10 — ETH Max UX', () {
    testWidgets('Max works BEFORE Review — no draft required',
        (tester) async {
      // 1 ETH balance, fee = 21000 * 20 gwei = 420_000_000_000_000 wei.
      // Expected amount = 1 - 0.00042 = 0.99958 ETH.
      final client = _MaxUxClient(
        feeEstimateResponse: {
          'status': 'fee_estimate_ready',
          'authorizedMaxFeeBaseUnits':
              (BigInt.from(21000) *
                      BigInt.from(20000000000))
                  .toString(),
          'feeSource': 'eth_estimateGas_x_gasPrice',
          'network': 'ethereum_sepolia',
          'asset': 'ETH',
          'chainId': 11155111,
        },
      );
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async =>
              BigInt.from(10).pow(18));
      await _enterEthDest(tester, _kEthDest);
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      // 1 ETH - 21000*20e9 wei = 999580000000000000 wei = 0.99958 ETH
      expect(tf.controller?.text ?? '', '0.99958');
      // Fee-estimate endpoint was hit; no draft or secret retrieval.
      expect(client.feeEstimateCallCount, 1);
      expect(client.draftCallCount, 0);
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      // Destination echoed into the request.
      expect(
          client.lastFeeEstimateRequest?['destinationAddress'],
          _kEthDest);
    });

    testWidgets('Max without destination BLOCKS with clear message',
        (tester) async {
      final client = _MaxUxClient();
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async =>
              BigInt.from(10).pow(18));
      // No destination entered.
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kEthSendMaxRequiresDestinationError),
          findsOneWidget);
      expect(client.feeEstimateCallCount, 0);
      final tf = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '');
    });

    testWidgets('Max with malformed destination BLOCKS',
        (tester) async {
      final client = _MaxUxClient();
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async =>
              BigInt.from(10).pow(18));
      await _enterEthDest(tester, 'not-an-address');
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kEthSendMaxRequiresDestinationError),
          findsOneWidget);
      expect(client.feeEstimateCallCount, 0);
    });

    testWidgets('Balance unavailable → BLOCKS temporarily',
        (tester) async {
      final client = _MaxUxClient(
        feeEstimateResponse: {
          'status': 'fee_estimate_ready',
          'authorizedMaxFeeBaseUnits': '420000000000000',
          'feeSource': 'eth_estimateGas_x_gasPrice',
        },
      );
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async => null);
      await _enterEthDest(tester, _kEthDest);
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kMainnetSendBalanceUnverifiedError),
          findsOneWidget);
      // We MUST NOT have called the fee-estimate endpoint before
      // confirming balance is verifiable.
      expect(client.feeEstimateCallCount, 0);
    });

    testWidgets('Fee estimate unavailable → BLOCKS temporarily',
        (tester) async {
      final client = _MaxUxClient(
        feeEstimateResponse: const {
          'status': 'fee_estimate_unavailable',
          'reason': 'rpc_unreachable',
        },
      );
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async =>
              BigInt.from(10).pow(18));
      await _enterEthDest(tester, _kEthDest);
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kEthSendMaxTemporarilyUnavailableError),
          findsOneWidget);
      // Amount stays empty on temporary failure.
      final tf = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '');
      // No secret retrieval or broadcast during Max.
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
    });

    testWidgets('Fee estimate throws → BLOCKS temporarily',
        (tester) async {
      final client = _MaxUxClient(
        feeEstimateThrow: Exception('network down'),
      );
      await _pumpEth(tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalanceWei: () async =>
              BigInt.from(10).pow(18));
      await _enterEthDest(tester, _kEthDest);
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kEthSendMaxTemporarilyUnavailableError),
          findsOneWidget);
    });

    testWidgets(
        'ERC-20 Max = full token balance; NO ETH is subtracted',
        (tester) async {
      // 12.5 USDT = 12_500_000 base units.
      final tokenBase = BigInt.from(12500000);
      final client = _MaxUxClient();
      await _pumpEth(tester,
          client: client,
          asset: 'USDT_ERC20',
          fetchAvailableBalanceWei: () async => tokenBase);
      // ERC-20 Max does NOT need destination — the fee is paid in
      // ETH which the exact-fee gate checks separately.
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '12.5');
      // NO fee-estimate call for the ERC-20 Max — token balance is
      // authoritative on its own.
      expect(client.feeEstimateCallCount, 0);
      expect(client.encryptedSecretCallCount, 0);
    });

    testWidgets(
        'source: ETH _onMaxTap has NO hard-coded 21000×100 gwei '
        'fallback', (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_send_panel.dart',
      );
      final idx = src.indexOf('Future<void> _onMaxTap()');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 4000);
      final hardcoded = RegExp(
        r'BigInt\.from\(21000\)\s*\*\s*BigInt\.from\(100000000000\)',
      );
      expect(hardcoded.hasMatch(scope), isFalse);
      expect(scope.contains('100 gwei'), isFalse);
    });
  });

  group('Round 10 — SOL Max UX', () {
    testWidgets('Max works BEFORE Review — no draft required',
        (tester) async {
      // 1 SOL = 1_000_000_000 lamports. Fee = 5000 lamports.
      final client = _MaxUxClient(
        feeEstimateResponse: const {
          'status': 'fee_estimate_ready',
          'authorizedMaxFeeBaseUnits': '5000',
          'feeSource': 'sol_getFeeForMessage',
          'network': 'solana_mainnet',
          'asset': 'SOL',
        },
      );
      await _pumpSol(tester,
          client: client,
          fetchAvailableLamports: () async => BigInt.from(1000000000));
      await _enterSolDest(tester, _kSolDest);
      await tester.tap(
        find.byKey(const Key('solana_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('solana_send_panel_amount_input')),
      );
      // 1_000_000_000 - 5000 = 999_995_000 lamports = 0.999995 SOL
      expect(tf.controller?.text ?? '', '0.999995');
      expect(client.feeEstimateCallCount, 1);
      expect(client.draftCallCount, 0);
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
    });

    testWidgets('Max without destination BLOCKS with clear message',
        (tester) async {
      final client = _MaxUxClient();
      await _pumpSol(tester,
          client: client,
          fetchAvailableLamports: () async => BigInt.from(1000000000));
      await tester.tap(
        find.byKey(const Key('solana_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kSolanaSendMaxRequiresDestinationError),
          findsOneWidget);
      expect(client.feeEstimateCallCount, 0);
    });

    testWidgets('Balance unavailable → BLOCKS temporarily',
        (tester) async {
      final client = _MaxUxClient(
        feeEstimateResponse: const {
          'status': 'fee_estimate_ready',
          'authorizedMaxFeeBaseUnits': '5000',
        },
      );
      await _pumpSol(tester,
          client: client,
          fetchAvailableLamports: () async => null);
      await _enterSolDest(tester, _kSolDest);
      await tester.tap(
        find.byKey(const Key('solana_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kSolanaSendMaxBalanceUnverifiedError),
          findsOneWidget);
      // MUST NOT have called fee-estimate before balance is verified.
      expect(client.feeEstimateCallCount, 0);
    });

    testWidgets('Fee estimate unavailable → BLOCKS temporarily',
        (tester) async {
      final client = _MaxUxClient(
        feeEstimateResponse: const {
          'status': 'fee_estimate_unavailable',
          'reason': 'rpc_unreachable',
        },
      );
      await _pumpSol(tester,
          client: client,
          fetchAvailableLamports: () async => BigInt.from(1000000000));
      await _enterSolDest(tester, _kSolDest);
      await tester.tap(
        find.byKey(const Key('solana_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kSolanaSendMaxTemporarilyUnavailableError),
          findsOneWidget);
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
    });

    testWidgets(
        'source: SOL _onMaxTap has NO hard-coded numeric fee',
        (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      final idx = src.indexOf('Future<void> _onMaxTap()');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 3000);
      // No numeric literal > 10^9 (allow 10^9 divisor for
      // lamports-to-SOL formatting).
      final literals = RegExp(r'\b\d{5,}\b')
          .allMatches(scope)
          .map((m) => m.group(0))
          .toList();
      for (final n in literals) {
        final v = int.tryParse(n!);
        if (v != null) {
          expect(v <= 1000000000, isTrue,
              reason:
                  'SOL Max contains hard-coded literal "$n" that '
                  'could be an unauthorized fee reservation.');
        }
      }
    });
  });

  group('Round 10 — TRC-20 Max UX', () {
    testWidgets(
        'USDT-TRC20 Max = full verified token balance, no TRX '
        'subtraction, no fee-estimate call', (tester) async {
      // 12.5 USDT = 12_500_000 base units. TRX balance is small
      // (say 100 sun = 0.0001 TRX) — Max must NOT subtract this.
      final client = _MaxUxClient();
      await _pumpTron(tester,
          client: client,
          fetchAvailableTokenBaseUnits: () async =>
              BigInt.from(12500000),
          fetchTrxBalanceSun: () async => BigInt.from(100));
      await tester.tap(
        find.byKey(const Key('tron_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('tron_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '12.5');
      expect(client.feeEstimateCallCount, 0);
      expect(client.encryptedSecretCallCount, 0);
    });

    testWidgets(
        'USDT-TRC20 Max with null token balance → BLOCKS',
        (tester) async {
      final client = _MaxUxClient();
      await _pumpTron(tester,
          client: client,
          fetchAvailableTokenBaseUnits: () async => null,
          fetchTrxBalanceSun: () async => BigInt.from(1000000));
      await tester.tap(
        find.byKey(const Key('tron_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      // The exact error text is TRON-panel-specific; assert amount
      // stays empty as the observable safety property.
      final tf = tester.widget<TextField>(
        find.byKey(const Key('tron_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '');
      expect(client.feeEstimateCallCount, 0);
    });
  });

  group('Round 10 — source-level safety invariants', () {
    testWidgets(
        'ETH Max path fetches balance BEFORE calling the fee-'
        'estimate endpoint (so an unverifiable balance never '
        'leaks a destination lookup)', (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_send_panel.dart',
      );
      final idx = src.indexOf('Future<void> _onMaxTap()');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 4000);
      final feeIdx = scope.indexOf('_fetchAuthorizedMaxFeeWei');
      final balIdx = scope.indexOf('fetchAvailableBalanceWei');
      expect(balIdx, greaterThan(-1));
      expect(feeIdx, greaterThan(-1));
      expect(balIdx < feeIdx, isTrue,
          reason:
              'balance check MUST precede fee-estimate call so we '
              'never issue an unauthenticated destination lookup '
              'for a wallet we cannot see.');
    });

    testWidgets(
        'SOL Max path fetches balance BEFORE the fee-estimate '
        'call', (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      final idx = src.indexOf('Future<void> _onMaxTap()');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 3000);
      final balIdx = scope.indexOf('fetchAvailableLamports');
      final feeIdx = scope.indexOf('_fetchAuthorizedMaxFeeLamports');
      expect(balIdx, greaterThan(-1));
      expect(feeIdx, greaterThan(-1));
      expect(balIdx < feeIdx, isTrue);
    });

    testWidgets(
        'API client fee-estimate call sends the intended endpoint',
        (tester) async {
      final src = await _readLibFile('api_client.dart');
      final idx = src.indexOf(
          'postCryptoWalletSendFeeEstimateNetwork');
      expect(idx, greaterThan(-1));
      final scope = src.substring(idx, idx + 2000);
      expect(scope.contains('/send/fee_estimate'), isTrue);
      expect(scope.contains("'fromAddress'"), isTrue);
      expect(scope.contains("'destinationAddress'"), isTrue);
      expect(scope.contains("'asset'"), isTrue);
    });
  });
}
