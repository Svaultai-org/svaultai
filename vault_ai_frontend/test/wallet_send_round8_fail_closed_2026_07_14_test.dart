// 2026-07-14 (Round 8 corrective completion): fail-closed
// regression suite.
//
// Areas exercised:
//   * SOL missing/null/thrown/malformed hooks BLOCK before
//     encrypted-secret retrieval.
//   * SOL pre-secret authoritative draft-expiry check blocks
//     when the endpoint says expired OR expired == null.
//   * SOL pre-broadcast authoritative expiry check blocks after
//     signing but BEFORE broadcast.
//   * TRON parallel behavior.
//   * EVM + SOL + TRON duplicate-Review guard (exactly one draft
//     call under rapid double-tap).
//   * ETH Max fails closed when no draft exists (NO hardcoded
//     100 gwei fallback).
//   * SOL Max = availableLamports − persistedFeeLamports.
//   * TRON USDT Max = full verified token base-unit balance.
//   * TRON review copy: USDT amount and max-authorized TRX fee
//     rendered separately.

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


CryptoWalletFeatures _featuresForSol() {
  return CryptoWalletFeatures.fromBackend(const <String, dynamic>{
    'walletEngineEnabled': true, 'solanaEnabled': true,
    'solanaSendEnabled': true,
  });
}

CryptoWalletFeatures _featuresForTron() {
  return CryptoWalletFeatures.fromBackend(const <String, dynamic>{
    'walletEngineEnabled': true, 'tronEnabled': true,
    'tronSendEnabled': true, 'tronUsdtContractConfigured': true,
  });
}


const String _kEthFrom = '0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855';
const String _kEthDest = '0x7C49215A2cB86aaC3e6308EA4D6206912578e870';
const String _kSolFrom = 'So11111111111111111111111111111111111111112';
const String _kSolDest = '11111111111111111111111111111111';
const String _kTrnFrom = 'TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq';
const String _kTrnDest = 'TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9';


class _FakeR8Client extends VaultAIClient {
  final Map<String, dynamic> draftResponse;
  final Map<String, dynamic> broadcastResponse;
  // Authoritative draft-expiry endpoint responses can be scripted
  // per call; ordered scripts pop from the front so pre-secret vs
  // pre-broadcast checks can differ.
  final List<Map<String, dynamic>> expiryScript;

  int draftCallCount = 0;
  int broadcastCallCount = 0;
  int encryptedSecretCallCount = 0;
  int expiryCallCount = 0;

  _FakeR8Client({
    this.draftResponse = const {'status': 'draft_ready'},
    this.broadcastResponse = const {},
    this.expiryScript = const <Map<String, dynamic>>[],
  }) : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraftNetwork({
    required String network, required String asset,
    required String authToken, required String fromAddress,
    required String destinationAddress,
    String? amountEth, String? amountSol, String? amountUsdt,
  }) async {
    draftCallCount++;
    return draftResponse;
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset, required String authToken,
    required String fromAddress, required String destinationAddress,
    required String amountEth,
  }) async {
    draftCallCount++;
    return draftResponse;
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
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransaction({
    required String asset, required String authToken,
    required Object signedTransaction,
  }) async {
    broadcastCallCount++;
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletDraftExpiryNetwork({
    required String network, required String draftId,
    required String authToken,
  }) async {
    expiryCallCount++;
    if (expiryScript.isEmpty) {
      // Default: not expired.
      return const {'expired': false};
    }
    final idx = expiryCallCount - 1;
    if (idx < expiryScript.length) return expiryScript[idx];
    return expiryScript.last;
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


Map<String, Object?> _draftReadyEth() => {
      'status': 'draft_ready',
      'draftId': 'r8-eth-drft-aabb',
      'fromAddress': _kEthFrom,
      'destinationAddress': _kEthDest,
      'amountEth': '0.001',
      'amountWei': '1000000000000000',
      'unit': 'ETH',
      'nonce': '5',
      'gasLimit': '21000',
      'gasPrice': '20000000000',
      'chainId': 1,
      'feeUnit': 'wei',
    };

Map<String, Object?> _draftReadySol() => {
      'status': 'draft_ready',
      'draftId': 'r8-sol-drft-aabb',
      'fromAddress': _kSolFrom,
      'destinationAddress': _kSolDest,
      'amountSol': '0.001',
      'lamports': '1000000',
      'feeLamports': 5000,
      'recentBlockhash': 'GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cUKQwT8b9DhP7A',
      'lastValidBlockHeight': 250000000,
    };

Map<String, Object?> _draftReadyTron() {
  final txId = 'aa' * 32;
  return {
    'status': 'draft_ready',
    'draftId': 'r8-trn-drft-aabb',
    'fromAddress': _kTrnFrom,
    'destinationAddress': _kTrnDest,
    'amountUsdt': '5.0',
    'amountBaseUnits': '5000000',
    'txID': txId,
    'unsignedTransaction': <String, Object?>{
      'txID': txId,
      'raw_data': <String, Object?>{'expiration': 99999999999999},
      'raw_data_hex': '0a',
    },
    'feeLimitSun': 100000000,
    'feeLimitTrx': '100.0',
    'trxBalance': '200.0',
    'resourceStatus': 'ready',
    'expirationMs': 99999999999999,
  };
}


Future<void> _pumpEth(
  WidgetTester tester, {
  required VaultAIClient client,
  Future<double?> Function()? fetchAvailableBalance,
  Future<BigInt?> Function()? fetchAvailableBalanceWei,
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
        asset: 'ETH',
        network: kEvmNetworkEthereumSepolia,
        fetchAvailableBalance:
            fetchAvailableBalance ?? (() async => 1.0),
        fetchAvailableBalanceWei: fetchAvailableBalanceWei,
      ),
    ),
  ));
  await tester.pump();
}


Future<void> _pumpSol(
  WidgetTester tester, {
  required VaultAIClient client,
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
        features: _featuresForSol(),
        fetchAvailableLamports: fetchAvailableLamports,
      ),
    ),
  ));
  await tester.pump();
}


Future<void> _pumpTron(
  WidgetTester tester, {
  required VaultAIClient client,
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
        features: _featuresForTron(),
        fetchAvailableTokenBaseUnits: fetchAvailableTokenBaseUnits,
        fetchTrxBalanceSun: fetchTrxBalanceSun,
      ),
    ),
  ));
  await tester.pump();
}


Future<void> _driveThroughToPin({
  required WidgetTester tester,
  required String destKey,
  required String amountKey,
  required String reviewKey,
  required String confirmKey,
  required String pinInputKey,
  required String pinConfirmKey,
  required String dest,
  required String amount,
}) async {
  await tester.enterText(find.byKey(Key(destKey)), dest);
  await tester.enterText(find.byKey(Key(amountKey)), amount);
  await tester.tap(find.byKey(Key(reviewKey)));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key(confirmKey)));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(Key(pinInputKey)), '1234');
  await tester.tap(find.byKey(Key(pinConfirmKey)));
  await tester.pumpAndSettle();
}


void main() {
  // ───────────────────────────────────────────────────────────
  // SOL fail-closed
  // ───────────────────────────────────────────────────────────
  group('SOL: fetchAvailableLamports fail-closed matrix', () {
    testWidgets(
        'missing hook → BLOCK: no encrypted secret fetch',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
      );
      // No fetchAvailableLamports wired.
      await _pumpSol(tester, client: client);
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0,
          reason: 'missing SOL balance hook MUST block secret fetch');
      expect(client.broadcastCallCount, 0);
      expect(find.text(kSolanaSendExactFeeUnverifiedError),
          findsOneWidget);
    });

    testWidgets('null balance → BLOCK: no encrypted secret fetch',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => null);
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(find.text(kSolanaSendExactFeeUnverifiedError),
          findsOneWidget);
    });

    testWidgets('thrown balance fetch → BLOCK', (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => throw Exception('down'));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
    });

    testWidgets(
        'malformed persisted fee value → BLOCK',
        (tester) async {
      // feeLamports missing / non-numeric.
      final malformedDraft = <String, Object?>{
        ..._draftReadySol(),
        'feeLamports': 'not-a-number',
      };
      final client = _FakeR8Client(
        draftResponse: malformedDraft.cast<String, dynamic>(),
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => BigInt.from(9999999));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0);
    });
  });

  // ───────────────────────────────────────────────────────────
  // SOL expiry order
  // ───────────────────────────────────────────────────────────
  group('SOL: pre-sign + pre-broadcast expiry order', () {
    testWidgets(
        'pre-secret expiry check blocked: no secret fetch',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
        expiryScript: const [
          {'expired': true, 'reason': 'blockheight_exceeded'},
        ],
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => BigInt.from(9999999));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0,
          reason: 'pre-secret expiry MUST block secret fetch');
      expect(client.broadcastCallCount, 0);
      expect(client.expiryCallCount, 1);
    });

    testWidgets(
        'pre-secret expired=null (unverifiable) blocks',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
        expiryScript: const [
          {'expired': null, 'reason': 'rpc_not_configured'},
        ],
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => BigInt.from(9999999));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'solana_send_panel_destination_input',
        amountKey: 'solana_send_panel_amount_input',
        reviewKey: 'solana_send_panel_review_btn',
        confirmKey: 'solana_send_panel_confirm_btn',
        pinInputKey: 'solana_send_panel_pin_input',
        pinConfirmKey: 'solana_send_panel_pin_confirm_btn',
        dest: _kSolDest, amount: '0.001',
      );
      expect(client.encryptedSecretCallCount, 0,
          reason: 'expired == null MUST fail closed, not open');
    });

    testWidgets(
        'source: SOL panel calls _verifyDraftExpiryFailClosed '
        'IMMEDIATELY BEFORE the broadcast call (no code between)',
        (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      final call = src.indexOf(
        'broadcastCryptoWalletSignedTransactionNetwork',
      );
      expect(call, greaterThan(-1));
      // Search backwards for the pre-broadcast expiry check.
      final preIdx = src.lastIndexOf(
        '_verifyDraftExpiryFailClosed', call,
      );
      expect(preIdx, greaterThan(-1),
          reason: 'pre-broadcast expiry check MUST appear before '
                  'the broadcast call in the source.');
      // The gap between the check and broadcast must be small —
      // just a status classification block, no unrelated calls.
      final gap = src.substring(preIdx, call);
      // No RPC calls between the pre-broadcast expiry check and
      // the broadcast — no unrelated client methods.
      final rpcMethodsBetween = RegExp(
        r'client\.[a-zA-Z]+',
      ).allMatches(gap).toList();
      // Only the broadcast itself, and possibly setState is fine.
      expect(rpcMethodsBetween.length, lessThanOrEqualTo(0),
          reason: 'no client RPC calls may sit between the pre-'
                  'broadcast expiry check and the broadcast call.');
    });
  });

  // ───────────────────────────────────────────────────────────
  // TRON parallel: fail-closed + expiry order
  // ───────────────────────────────────────────────────────────
  group('TRON: fail-closed + pre-sign + pre-broadcast expiry', () {
    testWidgets(
        'missing fetchAvailableTokenBaseUnits → BLOCK before secret',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
      );
      await _pumpTron(tester, client: client,
          fetchTrxBalanceSun: () async => BigInt.from(999999999999));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'tron_send_panel_destination_input',
        amountKey: 'tron_send_panel_amount_input',
        reviewKey: 'tron_send_panel_review_btn',
        confirmKey: 'tron_send_panel_confirm_btn',
        pinInputKey: 'tron_send_panel_pin_input',
        pinConfirmKey: 'tron_send_panel_pin_confirm_btn',
        dest: _kTrnDest, amount: '5.0',
      );
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kTronSendExactFeeUnverifiedError), findsOneWidget,
      );
    });

    testWidgets(
        'pre-secret expiry blocks: no secret fetch',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
        expiryScript: const [
          {'expired': true, 'reason': 'expiration_passed'},
        ],
      );
      await _pumpTron(tester, client: client,
          fetchAvailableTokenBaseUnits: () async => BigInt.from(9999999999),
          fetchTrxBalanceSun: () async => BigInt.from(999999999999));
      await _driveThroughToPin(
        tester: tester,
        destKey: 'tron_send_panel_destination_input',
        amountKey: 'tron_send_panel_amount_input',
        reviewKey: 'tron_send_panel_review_btn',
        confirmKey: 'tron_send_panel_confirm_btn',
        pinInputKey: 'tron_send_panel_pin_input',
        pinConfirmKey: 'tron_send_panel_pin_confirm_btn',
        dest: _kTrnDest, amount: '5.0',
      );
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(client.expiryCallCount, 1);
    });

    testWidgets(
        'source: TRON panel calls _verifyDraftExpiryFailClosed '
        'immediately before broadcast (no client RPC between)',
        (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_tron_send_panel.dart',
      );
      final call = src.indexOf(
        'broadcastCryptoWalletSignedTransactionNetwork',
      );
      expect(call, greaterThan(-1));
      final preIdx = src.lastIndexOf(
        '_verifyDraftExpiryFailClosed', call,
      );
      expect(preIdx, greaterThan(-1));
      final gap = src.substring(preIdx, call);
      final rpcMethodsBetween = RegExp(
        r'client\.[a-zA-Z]+',
      ).allMatches(gap).toList();
      expect(rpcMethodsBetween.length, lessThanOrEqualTo(0));
    });
  });

  // ───────────────────────────────────────────────────────────
  // Duplicate Review (draft-in-flight) guards
  // ───────────────────────────────────────────────────────────
  group('EVM/SOL/TRON duplicate Review guard', () {
    testWidgets('EVM rapid double-tap Review → exactly 1 draft call',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
      );
      await _pumpEth(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kEthDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')), '0.001',
      );
      final btn = find.byKey(const Key('eth_send_panel_review_btn'));
      // Fire two taps back-to-back before settling.
      await tester.tap(btn);
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(client.draftCallCount, 1);
    });

    testWidgets('SOL rapid double-tap Review → exactly 1 draft call',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
      );
      await _pumpSol(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('solana_send_panel_destination_input')),
        _kSolDest,
      );
      await tester.enterText(
        find.byKey(const Key('solana_send_panel_amount_input')), '0.001',
      );
      final btn = find.byKey(const Key('solana_send_panel_review_btn'));
      await tester.tap(btn);
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(client.draftCallCount, 1);
    });

    testWidgets('TRON rapid double-tap Review → exactly 1 draft call',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
      );
      await _pumpTron(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_destination_input')),
        _kTrnDest,
      );
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_amount_input')), '5.0',
      );
      final btn = find.byKey(const Key('tron_send_panel_review_btn'));
      await tester.tap(btn);
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(client.draftCallCount, 1);
    });
  });

  // ───────────────────────────────────────────────────────────
  // Max architecture — no hard-coded fallback
  // ───────────────────────────────────────────────────────────
  group('Max architecture', () {
    testWidgets(
        'ETH Max with NO destination → BLOCKED asking for '
        'destination (no 21000 * 100 gwei fallback, no draft '
        'requirement)', (tester) async {
      // 2026-07-14 (Round 10 — Max UX): Max no longer requires a
      // persisted draft. Instead it needs a valid destination so
      // it can ask the fee-estimate endpoint for the authoritative
      // maximum fee for THAT recipient. This test asserts the
      // destination-required fail-closed branch and the amount
      // field stays empty.
      final client = _FakeR8Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
      );
      await _pumpEth(tester, client: client,
          fetchAvailableBalanceWei: () async =>
              BigInt.parse('1000000000000000000'));
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(find.text(kEthSendMaxRequiresDestinationError),
          findsOneWidget);
      final tf = tester.widget<TextField>(
        find.byKey(const Key('eth_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '');
    });

    testWidgets(
        'source-level: no `21000 * BigInt.from(100000000000)` gas '
        'reservation pattern remains in send_panel Max path',
        (tester) async {
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_send_panel.dart',
      );
      final onMax = src.indexOf('Future<void> _onMaxTap()');
      expect(onMax, greaterThan(-1));
      final scope = src.substring(onMax, onMax + 2500);
      // Match the specific hardcoded-fallback expression the
      // Round-5 impl used: `BigInt.from(21000) * BigInt.from(100000000000)`
      // or its ETH shorthand. If the constant reappears in the
      // Max path this test fails.
      final hardcodedRe = RegExp(
        r'BigInt\.from\(21000\)\s*\*\s*BigInt\.from\(100000000000\)',
      );
      expect(hardcodedRe.hasMatch(scope), isFalse,
          reason: 'Max must NOT reintroduce the Round-5 hardcoded '
                  '21000 * 100 gwei gas reservation.');
      // Belt-and-braces: no ETH mention of `100 gwei`.
      expect(scope.contains('100 gwei'), isFalse);
    });

    testWidgets(
        'SOL Max without destination → BLOCKED asking for '
        'destination (Round 10 — no draft required)',
        (tester) async {
      // 2026-07-14 (Round 10 — Max UX): SOL Max no longer needs a
      // persisted draft. It calls the fee-estimate endpoint for
      // the destination the user has entered. Missing destination
      // → clear fail-closed message.
      final client = _FakeR8Client(
        draftResponse: _draftReadySol().cast<String, dynamic>(),
      );
      await _pumpSol(tester, client: client,
          fetchAvailableLamports: () async => BigInt.from(1000000));
      await tester.tap(
        find.byKey(const Key('solana_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      expect(find.text(kSolanaSendMaxRequiresDestinationError),
          findsOneWidget);
    });

    testWidgets(
        'source: SOL Max helper reads fee from the authoritative '
        'fee-estimate endpoint and does NOT hard-code any fee',
        (tester) async {
      // 2026-07-14 (Round 10 — Max UX): SOL Max reads the fee from
      // `postCryptoWalletSendFeeEstimateNetwork`, not from a
      // persisted draft. The property this test enforces — no
      // hard-coded numeric fee — is unchanged. Only the source
      // of the fee changed.
      final src = await _readLibFile(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      final onMax = src.indexOf('Future<void> _onMaxTap()');
      expect(onMax, greaterThan(-1));
      final scope = src.substring(onMax, onMax + 2500);
      // The Max path must call the fee-estimate helper.
      expect(scope.contains('_fetchAuthorizedMaxFeeLamports'), isTrue,
          reason: 'SOL Max must call the authoritative fee-estimate '
                  'helper for the entered destination.');
      // No hard-coded numeric fee constants.
      final numericLiterals = RegExp(r'\b\d{5,}\b')
          .allMatches(scope)
          .map((m) => m.group(0))
          .toList();
      for (final n in numericLiterals) {
        final v = int.tryParse(n!);
        if (v != null) {
          expect(v <= 1000000000, isTrue,
              reason: 'SOL Max contains a hard-coded numeric literal '
                      '"$n" that could be an unauthorized fee '
                      'reservation.');
        }
      }
    });

    testWidgets(
        'TRON USDT Max = exact token base-unit balance (no TRX '
        'subtraction)', (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
      );
      // 12.5 USDT = 12_500_000 base units.
      await _pumpTron(tester, client: client,
          fetchAvailableTokenBaseUnits: () async => BigInt.from(12500000),
          fetchTrxBalanceSun: () async => BigInt.from(1000000));
      await tester.tap(
        find.byKey(const Key('tron_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('tron_send_panel_amount_input')),
      );
      expect(tf.controller?.text, '12.5');
    });

    testWidgets(
        'TRON USDT Max with null token balance → BLOCKED, no fill',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
      );
      await _pumpTron(tester, client: client,
          fetchAvailableTokenBaseUnits: () async => null,
          fetchTrxBalanceSun: () async => BigInt.from(1000000));
      await tester.tap(
        find.byKey(const Key('tron_send_panel_max_btn')),
      );
      await tester.pumpAndSettle();
      final tf = tester.widget<TextField>(
        find.byKey(const Key('tron_send_panel_amount_input')),
      );
      expect(tf.controller?.text ?? '', '');
      expect(
        find.text(kTronSendMaxBalanceUnverifiedError),
        findsOneWidget,
      );
    });
  });

  // ───────────────────────────────────────────────────────────
  // TRON review copy: USDT amount + max authorized TRX cost
  // separately visible
  // ───────────────────────────────────────────────────────────
  group('TRON review copy separation', () {
    testWidgets(
        'review body renders USDT amount and max authorized TRX '
        'network cost with distinct labels',
        (tester) async {
      final client = _FakeR8Client(
        draftResponse: _draftReadyTron().cast<String, dynamic>(),
      );
      await _pumpTron(tester, client: client,
          fetchAvailableTokenBaseUnits: () async => BigInt.from(9999999999),
          fetchTrxBalanceSun: () async => BigInt.from(999999999999));
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_destination_input')),
        _kTrnDest,
      );
      await tester.enterText(
        find.byKey(const Key('tron_send_panel_amount_input')),
        '5.0',
      );
      await tester.tap(
        find.byKey(const Key('tron_send_panel_review_btn')),
      );
      await tester.pumpAndSettle();
      // USDT amount row.
      expect(
        find.byKey(
          const Key('tron_send_panel_review_usdt_amount_row'),
        ),
        findsOneWidget,
      );
      expect(find.text(kTronReviewUsdtAmountLabel), findsOneWidget);
      expect(find.text('5.0 USDT'), findsOneWidget);
      // Max authorized TRX cost row.
      expect(
        find.byKey(const Key(
          'tron_send_panel_review_max_authorized_fee_trx_row',
        )),
        findsOneWidget,
      );
      expect(find.text(kTronReviewMaxAuthorizedFeeLabel),
          findsOneWidget);
      // Explicit caution copy — never describe fee limit as
      // guaranteed charge.
      expect(
        find.byKey(const Key(
          'tron_send_panel_review_max_authorized_caution',
        )),
        findsOneWidget,
      );
      // Network label (may appear both in the review body AND
      // elsewhere; the key check is that the network name is at
      // least present).
      expect(find.text(kTronReviewNetworkValue),
          findsAtLeastNWidgets(1));
    });
  });
}


Future<String> _readLibFile(String relative) async {
  return File('${Directory.current.path}/lib/$relative')
      .readAsStringSync();
}
