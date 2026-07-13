// 2026-07-13 (Round 5 hardening): regression fixtures for the
// second-canary + production-UX fixes.
//
// Round-4 landed the visibility gate + integer-exact fee gate
// under Sepolia unit tests. Round 5 wires the production path
// (asset-detail Send opener) to actually pass the wei-balance hooks
// so the exact fee gate runs, adds a Max action, an "Available:"
// line, and an optimistic-debit callback on successful broadcast.
// This file locks that in and adds the SUCCESSFUL production
// canary as a positive regression alongside the failed one.
//
// Production canary that SUCCEEDED (do NOT rebroadcast — fixtures
// are declarative):
//   sender      = 0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855
//   recipient   = 0x7C49215A2cB86aaC3e6308EA4D6206912578e870
//   amount      = 0.0056 ETH
//   local hash  = 0x103efd24c2d6692f2f282f1cf1985ead4bbee00ee654a69dfdc92b224d84de4b
//   backend outcome: submitted → later confirmed on-chain
//   Activity showed the outgoing tx immediately.
//
// The failed canary regression (Round 4) still lives in
// `eth_send_canary_correctness_2026_07_13_test.dart`.

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/services/local_outgoing_tx_store.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';


const List<LocalizationsDelegate<Object?>> _l10n = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


const String _kFrom = '0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855';
const String _kDest = '0x7C49215A2cB86aaC3e6308EA4D6206912578e870';
const String _kAmount = '0.0056';

const String kSuccessfulCanaryHash =
    '0x103efd24c2d6692f2f282f1cf1985ead4bbee00ee654a69dfdc92b224d84de4b';


Map<String, Object?> _draftReadyEth({
  String gasLimit = '21000',
  String gasPrice = '20000000000',
}) => {
      'status': 'draft_ready',
      'draftId': 'round5-eth-draft-aabb',
      'fromAddress': _kFrom,
      'destinationAddress': _kDest,
      'amountEth': _kAmount,
      'amountWei': '5600000000000000',
      'unit': 'ETH',
      'nonce': '4',
      'gasLimit': gasLimit,
      'gasPrice': gasPrice,
      'chainId': 1,
      'feeUnit': 'wei',
    };


class _FakeRound5Client extends VaultAIClient {
  final Map<String, dynamic> draftResponse;
  final Map<String, dynamic> encryptedSecretResponse;
  final Map<String, dynamic> broadcastResponse;

  int draftCallCount = 0;
  int encryptedSecretCallCount = 0;
  int broadcastCallCount = 0;

  _FakeRound5Client({
    required this.draftResponse,
    required this.encryptedSecretResponse,
    required this.broadcastResponse,
  }) : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraftNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    String? amountEth,
    String? amountSol,
    String? amountUsdt,
  }) async {
    draftCallCount++;
    return draftResponse;
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
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
    return encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network, required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return encryptedSecretResponse;
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
      broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcastCallCount++;
    return broadcastResponse;
  }
}


Future<void> _pumpPanel(
  WidgetTester tester, {
  required VaultAIClient client,
  required String asset,
  Future<double?> Function()? fetchAvailableBalance,
  Future<double?> Function()? fetchEthBalance,
  Future<BigInt?> Function()? fetchAvailableBalanceWei,
  Future<BigInt?> Function()? fetchEthBalanceWei,
  LocalOutgoingTxStore? outgoingStore,
  void Function({required String txHash, required BigInt debitBaseUnits})?
      onSuccessfulBroadcast,
}) async {
  await tester.binding.setSurfaceSize(const Size(390, 2600));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _l10n,
    home: Scaffold(
      body: CryptoWalletEngineSendPanel(
        authToken: 'tok',
        fromAddress: _kFrom,
        client: client,
        decryptForVault: (_) async => '0x${'11' * 32}',
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        asset: asset,
        network: kEvmNetworkEthereumSepolia,
        fetchAvailableBalance: fetchAvailableBalance,
        fetchEthBalance: fetchEthBalance,
        fetchAvailableBalanceWei: fetchAvailableBalanceWei,
        fetchEthBalanceWei: fetchEthBalanceWei,
        outgoingTxStore: outgoingStore,
        onSuccessfulBroadcast: onSuccessfulBroadcast,
      ),
    ),
  ));
  await tester.pump();
}


void main() {
  group('Successful production canary — positive regression', () {
    testWidgets(
        'canary shape (submitted + local hash on the second run) '
        'produces the honest "Transaction submitted" heading + copy',
        (tester) async {
      final client = _FakeRound5Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': kSuccessfulCanaryHash,
        },
      );
      final exact = BigInt.from(5600000000000000)
          + BigInt.from(21000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => exact,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        _kAmount,
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(client.broadcastCallCount, 1);
      expect(
        find.text(kEthSendResultHeadingSubmitted),
        findsOneWidget,
      );
      // Honest hash rendered so the user can verify on Etherscan.
      expect(
        find.textContaining(kSuccessfulCanaryHash),
        findsOneWidget,
      );
      // NO rejected / uncertain headings.
      expect(
        find.text(kEthSendResultHeadingRejected), findsNothing,
      );
      expect(
        find.text(kEthSendResultHeadingUncertain), findsNothing,
      );
    });

    testWidgets(
        'onSuccessfulBroadcast fires with the correct base-units '
        'debit = value + max fee', (tester) async {
      final client = _FakeRound5Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': kSuccessfulCanaryHash,
        },
      );
      final exact = BigInt.from(5600000000000000)
          + BigInt.from(21000) * BigInt.from(20000000000);
      BigInt? debit;
      String? hash;
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => exact,
        onSuccessfulBroadcast:
            ({required String txHash, required BigInt debitBaseUnits}) {
          hash = txHash;
          debit = debitBaseUnits;
        },
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        _kAmount,
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();
      expect(hash, kSuccessfulCanaryHash);
      expect(debit, exact,
        reason: 'The optimistic pending debit surfaced to the asset '
                'detail page MUST equal value_wei + gas_limit * '
                'gas_price so the balance UI shows the correct pending '
                'amount.');
    });
  });


  group('Max action — integer-exact reservation', () {
    // 2026-07-14 (Round 8 hardening): the Round-5 Max button used a
    // hard-coded `21000 * 100 gwei` reserve. That was replaced with
    // an authoritative-fee-only architecture: Max fails closed
    // when no draft exists so the fee is unknown, and uses the
    // persisted draft fee otherwise. This test is rewritten to
    // reflect the new fail-closed behavior.
    testWidgets(
        'ETH Max without destination fails closed asking for '
        'destination (no hard-coded reserve, no draft required)',
        (tester) async {
      // 2026-07-14 (Round 10 — Max UX): the property this test
      // originally proved — no hard-coded 21000×100 gwei fallback —
      // is still enforced by the source-level assertion in the
      // Round-8 test file. Under the Round-10 architecture, Max
      // no longer requires a persisted draft; it requires a valid
      // destination address (so the fee-estimate endpoint can be
      // called for THAT destination). This test now proves the
      // new destination-required fail-closed path.
      final client = _FakeRound5Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
      );
      final wei = BigInt.from(10).pow(18);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => wei,
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(
        find.text(kEthSendMaxRequiresDestinationError),
        findsOneWidget,
        reason: 'ETH Max MUST fail closed when no destination is '
                'entered, so we cannot request an authoritative '
                'fee estimate for the wrong address.',
      );
    });

    testWidgets(
        'ERC-20 Max copies the token balance verbatim, gas paid in '
        'ETH stays separate', (tester) async {
      final client = _FakeRound5Client(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
      );
      // 12.5 USDT = 12,500,000 base units.
      final tokenBase = BigInt.from(12500000);
      final feeWei = BigInt.from(55000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'USDT_ERC20',
        fetchAvailableBalance: () async => 12.5,
        fetchEthBalance: () async => 0.1,
        fetchAvailableBalanceWei: () async => tokenBase,
        fetchEthBalanceWei: () async => feeWei,
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(
        find.widgetWithText(TextField, '12.5'),
        findsOneWidget,
        reason: 'ERC-20 Max value MUST equal the full token '
                'balance (gas is paid in ETH separately).',
      );
    });

    testWidgets(
        'Max when balance-wei hook returns null → hard-gate error, '
        'no draft', (tester) async {
      // 2026-07-14 (Round 10 — Max UX): Max now requires a valid
      // destination before it can consult the balance hook (fee
      // estimate depends on the destination). Enter one so the
      // balance-null branch is what actually blocks.
      final client = _FakeRound5Client(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => null,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        '0x7C49215A2cB86aaC3e6308EA4D6206912578e870',
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_max_btn')));
      await tester.pumpAndSettle();
      expect(
        find.text(kMainnetSendBalanceUnverifiedError),
        findsOneWidget,
      );
      expect(client.draftCallCount, 0);
    });
  });


  group('Available balance is visible near the amount input', () {
    testWidgets(
        'the Available line shows the current balance value with unit',
        (tester) async {
      final client = _FakeRound5Client(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 0.1234,
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('eth_send_panel_available_balance_text')),
        findsOneWidget,
      );
      expect(find.text('Available: 0.1234 ETH'), findsOneWidget);
    });

    testWidgets(
        'omits the Available line when no balance hook is wired',
        (tester) async {
      final client = _FakeRound5Client(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('eth_send_panel_available_balance_text')),
        findsNothing,
      );
    });
  });


  group('Amount validation edge-case table', () {
    Future<void> submitAmount(WidgetTester tester, String amt) async {
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')), amt,
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      await tester.pumpAndSettle();
    }

    final cases = <Map<String, String?>>[
      {'label': 'empty',
       'input': '', 'expectError': kEthSendFormValidationMissingFields},
      {'label': 'zero',
       'input': '0', 'expectError': kEthSendFormValidationBadAmount},
      {'label': 'negative',
       'input': '-0.01', 'expectError': kEthSendFormValidationBadAmount},
      {'label': 'letters',
       'input': 'abc', 'expectError': kEthSendFormValidationBadAmount},
      {'label': 'malformed decimal',
       'input': '0..01', 'expectError': kEthSendFormValidationBadAmount},
      {'label': 'leading whitespace',
       'input': '   0.01', 'expectError': null},
      {'label': 'trailing whitespace',
       'input': '0.01   ', 'expectError': null},
    ];

    for (final c in cases) {
      testWidgets('amount "${c['label']}"', (tester) async {
        final client = _FakeRound5Client(
          draftResponse: _draftReadyEth().cast<String, dynamic>(),
          encryptedSecretResponse: const {},
          broadcastResponse: const {},
        );
        await _pumpPanel(
          tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalance: () async => 1.0,
        );
        await submitAmount(tester, c['input']!);
        final err = c['expectError'];
        if (err != null) {
          expect(find.text(err), findsOneWidget,
              reason: 'amount "${c['input']}" MUST show "$err"');
          expect(client.draftCallCount, 0);
        } else {
          // The whitespace cases should trim and succeed to draft.
          expect(client.draftCallCount, 1,
              reason: 'amount "${c['input']}" MUST proceed to draft');
        }
      });
    }
  });


  group('Recipient validation edge-case table', () {
    final cases = <Map<String, String?>>[
      {'label': 'empty',
       'input': '', 'expectError': kEthSendFormValidationMissingFields},
      {'label': 'too short',
       'input': '0x123', 'expectError': kEthSendFormValidationBadAddress},
      {'label': 'no 0x prefix',
       'input': 'da3d577784075eb7011e60cb8a5f0ae33f682855',
       'expectError': kEthSendFormValidationBadAddress},
      {'label': 'too long',
       'input':
           '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
       'expectError': kEthSendFormValidationBadAddress},
      {'label': 'non-hex characters',
       'input':
           '0xZZaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
       'expectError': kEthSendFormValidationBadAddress},
      {'label': 'zero address (legal shape)',
       'input': '0x0000000000000000000000000000000000000000',
       'expectError': null},
      // 2026-07-14 (Round 6): the lowercase-legal case was
      // previously the sender's own address in lowercase. Since
      // self-send now blocks, use a DIFFERENT recipient.
      {'label': 'lowercase legal',
       'input': '0x7c49215a2cb86aac3e6308ea4d6206912578e870',
       'expectError': null},
      {'label': 'mixed case legal',
       'input': _kDest, 'expectError': null},
    ];

    for (final c in cases) {
      testWidgets('recipient "${c['label']}"', (tester) async {
        final client = _FakeRound5Client(
          draftResponse: _draftReadyEth().cast<String, dynamic>(),
          encryptedSecretResponse: const {},
          broadcastResponse: const {},
        );
        await _pumpPanel(
          tester,
          client: client,
          asset: 'ETH',
          fetchAvailableBalance: () async => 1.0,
        );
        await tester.enterText(
          find.byKey(const Key('eth_send_panel_destination_input')),
          c['input']!,
        );
        await tester.enterText(
          find.byKey(const Key('eth_send_panel_amount_input')),
          _kAmount,
        );
        await tester.tap(
          find.byKey(const Key('eth_send_panel_review_btn')),
        );
        await tester.pumpAndSettle();
        final err = c['expectError'];
        if (err != null) {
          expect(find.text(err), findsOneWidget,
              reason: 'recipient "${c['input']}" MUST show "$err"');
          expect(client.draftCallCount, 0);
        } else {
          expect(client.draftCallCount, 1,
              reason: 'recipient "${c['input']}" MUST proceed to draft');
        }
      });
    }
  });
}
