// 2026-07-13 (durability slice): regression tests for the two Round-4
// production correctness gaps.
//
//   1. Outgoing Activity MUST survive Flutter web reload / browser
//      restart / re-authentication on a second device. The in-memory
//      LocalOutgoingTxStore from Round-3 is insufficient by itself;
//      it must be composed with a durable vault-scoped backend
//      history endpoint whose rows outlive the browser session.
//
//   2. Balance verification must be a HARD authorization gate using
//      the EXACT gas fields returned by the draft — integer BigInt
//      arithmetic against `gasLimit * gasPrice + valueWei` (for ETH)
//      or the token base-units + `gasLimit * gasPrice` (for ERC-20).
//      Never a double-arithmetic 0.0005 ETH advisory. If either
//      hook is missing / unavailable / short by even 1 wei, the
//      flow refuses to fetch the encrypted secret, decrypt, sign,
//      or broadcast.
//
// Neither concern is exercised by the Round-3 canary tests — they
// live in a separate file so the intent is unambiguous.

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/durable_outgoing_history_store.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/services/local_outgoing_tx_store.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';
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


Map<String, Object?> _draftReadyEth({
  String amountEth = _kAmount,
  String amountWei = '5600000000000000',   // 0.0056 * 1e18
  String gasLimit  = '21000',
  String gasPrice  = '20000000000',        // 20 gwei → fee = 4.2e14 wei
}) {
  return {
    'status': 'draft_ready',
    'draftId': 'durability-frontend-regression-draft-aabb',
    'fromAddress': _kFrom,
    'destinationAddress': _kDest,
    'amountEth': amountEth,
    'amountWei': amountWei,
    'unit': 'ETH',
    'nonce': '3',
    'gasLimit': gasLimit,
    'gasPrice': gasPrice,
    'chainId': 1,
    'feeUnit': 'wei',
  };
}

Map<String, Object?> _draftReadyUsdt({
  String amount = '5',
  String gasLimit = '55000',
  String gasPrice = '20000000000',
}) {
  return {
    'status': 'draft_ready',
    'draftId': 'durability-frontend-regression-token-aabb',
    'fromAddress': _kFrom,
    'destinationAddress': _kDest,
    'amount': amount,
    'amountBaseUnits': '5000000',  // 5.0 USDT with 6 decimals
    'unit': 'USDT',
    'transactionTo': '0xdadadadadadadadadadadadadadadadadadadada',
    'transactionValueWei': '0',
    'dataHex': '0xa9059cbb'
        '0000000000000000000000007c49215a2cb86aac3e6308ea4d62'
        '06912578e870'
        '00000000000000000000000000000000000000000000000000000000'
        '004c4b40',
    'nonce': '3',
    'gasLimit': gasLimit,
    'gasPrice': gasPrice,
    'chainId': 1,
    'feeUnit': 'wei',
    'tokenContract': '0xdadadadadadadadadadadadadadadadadadadada',
    'decimals': 6,
  };
}


class _FakeDurabilityClient extends VaultAIClient {
  final Map<String, dynamic> draftResponse;
  final Map<String, dynamic> encryptedSecretResponse;
  final Map<String, dynamic> broadcastResponse;
  final Map<String, dynamic>? outgoingHistoryResponse;

  int draftCallCount = 0;
  int encryptedSecretCallCount = 0;
  int broadcastCallCount = 0;
  int outgoingHistoryCallCount = 0;

  _FakeDurabilityClient({
    required this.draftResponse,
    required this.encryptedSecretResponse,
    required this.broadcastResponse,
    this.outgoingHistoryResponse,
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
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransaction({
    required String asset,
    required String authToken,
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

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletOutgoingHistoryNetwork({
    required String network,
    required String authToken,
  }) async {
    outgoingHistoryCallCount++;
    return outgoingHistoryResponse ??
        const {'status': 'ok', 'outgoing': []};
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactions({
    required String asset,
    required String authToken,
    int limit = 20,
  }) async =>
      const {'transactionsStatus': 'unavailable', 'transactions': []};

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async =>
      const {'transactionsStatus': 'unavailable', 'transactions': []};
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
}) async {
  await tester.binding.setSurfaceSize(const Size(390, 2400));
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
      ),
    ),
  ));
  await tester.pump();
}


Future<void> _driveThroughToPin(
  WidgetTester tester, {
  String amount = _kAmount,
}) async {
  await tester.enterText(
    find.byKey(const Key('eth_send_panel_destination_input')),
    _kDest,
  );
  await tester.enterText(
    find.byKey(const Key('eth_send_panel_amount_input')),
    amount,
  );
  await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.pumpAndSettle();
}


void main() {
  group('Integer-exact fee authorization — ETH', () {
    testWidgets(
        'ETH balance == value + exact max fee → allowed all the way '
        'to broadcast', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      // valueWei = 5.6e15, fee = 21000 * 20e9 = 4.2e14, sum = 6.02e15.
      final exactAvail = BigInt.from(5600000000000000)
          + BigInt.from(21000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => exactAvail,
      );
      await _driveThroughToPin(tester);
      // PIN dialog. Submit the PIN.
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      // Everything MUST have happened: draft, secret, broadcast.
      expect(client.draftCallCount, 1);
      expect(client.encryptedSecretCallCount, 1);
      expect(client.broadcastCallCount, 1,
        reason: 'Exactly-at-the-limit balance MUST be authorized.');
    });

    testWidgets(
        'ETH balance one wei BELOW value + exact max fee → BLOCKED, '
        'no secret fetch, no broadcast', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      final shortByOneWei = BigInt.from(5600000000000000)
          + BigInt.from(21000) * BigInt.from(20000000000)
          - BigInt.one;
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => shortByOneWei,
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      // Draft ran (backend gate is separate), but NO signing, NO
      // secret fetch, NO broadcast.
      expect(client.draftCallCount, 1);
      expect(client.encryptedSecretCallCount, 0,
        reason: '1-wei short MUST block secret fetch.');
      expect(client.broadcastCallCount, 0,
        reason: '1-wei short MUST block broadcast.');
      expect(
        find.text(kMainnetSendExactFeeInsufficientEthError),
        findsOneWidget,
      );
    });

    testWidgets(
        'fetchAvailableBalanceWei returns null → BLOCKED, no secret '
        'fetch, no broadcast, error "exact fee unverified"',
        (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => null,
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendExactFeeUnverifiedError),
        findsOneWidget,
      );
    });

    testWidgets(
        'fetchAvailableBalanceWei throws → BLOCKED, no signing, '
        'no broadcast', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async =>
            throw Exception('rpc down mid-flow'),
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendExactFeeUnverifiedError),
        findsOneWidget,
      );
    });

    testWidgets(
        'huge draft value (near uint256 boundary) preserves integer '
        'precision', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth(
          amountEth: '1',
          // 12,345,678,987,654,321,098,765 wei
          amountWei: '12345678987654321098765',
          gasLimit: '1000000',
          gasPrice: '999999999999',
        ).cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      // valueWei + gasLimit * gasPrice. Must never round through
      // double. Below-by-one is blocked; equal is allowed.
      final valueWei = BigInt.parse('12345678987654321098765');
      final feeWei = BigInt.from(1000000) * BigInt.from(999999999999);
      final exact = valueWei + feeWei;
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 999999.0,
        fetchAvailableBalanceWei: () async => exact - BigInt.one,
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 0,
        reason: 'BigInt subtraction of 1 wei from a 78-bit balance '
                'MUST block signing. A double conversion would round '
                'past this boundary and mis-allow the transaction.');
      expect(client.broadcastCallCount, 0);
    });

    testWidgets(
        'gas price bumped between two drafts causes the second exact '
        'fee re-check to fail even though balance was fine for first '
        'draft', (tester) async {
      // Balance = 5.6e15 + 21000 * 20e9 = 6.02e15 wei. Fine for the
      // FIRST draft (gasPrice=20 gwei). Backend re-draft with a
      // higher gasPrice must be BLOCKED by the exact fee re-check.
      final oldBalance = BigInt.from(5600000000000000)
          + BigInt.from(21000) * BigInt.from(20000000000);
      final client = _FakeDurabilityClient(
        // The re-drafted response uses 100 gwei — 5x the original.
        draftResponse: _draftReadyEth(
          gasPrice: '100000000000',
        ).cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        // Wallet balance did NOT grow — client still holds the old
        // number of wei.
        fetchAvailableBalanceWei: () async => oldBalance,
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.broadcastCallCount, 0);
      expect(client.encryptedSecretCallCount, 0,
        reason: 'Draft-bumped gas price must trigger integer-exact '
                're-check failure BEFORE any secret fetch.');
      expect(
        find.text(kMainnetSendExactFeeInsufficientEthError),
        findsOneWidget,
      );
    });
  });


  group('Integer-exact fee authorization — ERC-20', () {
    testWidgets(
        'ERC20 token balance sufficient but ETH one wei below exact '
        'fee → BLOCKED', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyUsdt().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      final feeWei = BigInt.from(55000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'USDT_ERC20',
        fetchAvailableBalance: () async => 100.0,
        fetchEthBalance: () async => 0.1,
        // Plenty of USDT (10 tokens = 10_000_000 base units).
        fetchAvailableBalanceWei: () async => BigInt.from(10000000),
        // ETH exactly one wei short of the fee.
        fetchEthBalanceWei: () async => feeWei - BigInt.one,
      );
      await _driveThroughToPin(tester, amount: '5');
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendExactFeeInsufficientGasEthError),
        findsOneWidget,
      );
    });

    testWidgets(
        'ERC20 ETH fee sufficient but token balance one base unit '
        'short → BLOCKED', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyUsdt().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      final feeWei = BigInt.from(55000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'USDT_ERC20',
        fetchAvailableBalance: () async => 100.0,
        fetchEthBalance: () async => 0.1,
        // 5 USDT amount = 5_000_000 base units. Balance is
        // 4_999_999 — one base unit short.
        fetchAvailableBalanceWei: () async => BigInt.from(4999999),
        fetchEthBalanceWei: () async => feeWei,
      );
      await _driveThroughToPin(tester, amount: '5');
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendExactFeeInsufficientTokenError),
        findsOneWidget,
      );
    });

    testWidgets(
        'ERC20 both exact — authorized, secret + broadcast happen',
        (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyUsdt().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      final feeWei = BigInt.from(55000) * BigInt.from(20000000000);
      await _pumpPanel(
        tester,
        client: client,
        asset: 'USDT_ERC20',
        fetchAvailableBalance: () async => 100.0,
        fetchEthBalance: () async => 0.1,
        fetchAvailableBalanceWei: () async => BigInt.from(5000000),
        fetchEthBalanceWei: () async => feeWei,
      );
      await _driveThroughToPin(tester, amount: '5');
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      expect(client.encryptedSecretCallCount, 1);
      expect(client.broadcastCallCount, 1);
    });
  });


  group('Ordering: balance → draft → exact fee re-check → secret '
      'fetch → sign → broadcast', () {
    testWidgets(
        'exact-fee failure aborts BEFORE the encrypted secret is '
        'requested from the backend', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: _draftReadyEth().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': '0xdeadbeef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        asset: 'ETH',
        fetchAvailableBalance: () async => 1.0,
        fetchAvailableBalanceWei: () async => BigInt.one,
      );
      await _driveThroughToPin(tester);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')), '1234',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_pin_confirm')),
      );
      await tester.pumpAndSettle();
      // KEY ORDERING INVARIANT:
      //   PIN dialog succeeded → BUT encrypted secret was NEVER
      //   fetched because the exact-fee gate blocked. The user's
      //   private key ciphertext never left the backend.
      expect(client.encryptedSecretCallCount, 0,
        reason: 'Encrypted secret fetch MUST come AFTER the exact '
                'fee gate.');
      expect(client.broadcastCallCount, 0);
    });
  });


  group('Durable outgoing history — DurableOutgoingHistoryStore', () {
    test('parses backend rows into typed BigInt records', () {
      final store = DurableOutgoingHistoryStore(
        client: _FakeDurabilityClient(
          draftResponse: const {},
          encryptedSecretResponse: const {},
          broadcastResponse: const {},
        ),
        authTokenProvider: () => 'tok',
      );
      store.seedForNetwork('ethereum_mainnet', <DurableOutgoingTx>[
        DurableOutgoingTx.fromJson(<String, Object?>{
          'draftId': 'drft-1',
          'networkId': 'ethereum_mainnet',
          'asset': 'ETH',
          'unit': 'ETH',
          'decimals': 18,
          'fromAddress': _kFrom,
          'destinationAddress': _kDest,
          'transactionTo': _kDest,
          'valueWei': '5600000000000000',
          'amountBaseUnits': '5600000000000000',
          'dataHex': '0x',
          'gasLimit': '21000',
          'gasPrice': '20000000000',
          'feeWei': '420000000000000',
          'chainId': 1,
          'localTxHash': '0x'
              '783ddc09728b26884c78da47ee408c40'
              'daa75c89e03700deb216e98ed77c415b',
          'broadcastOutcome': 'submission_uncertain',
          'createdAt': 1720000000.0,
          'consumedAt': 1720000010.0,
          'outcomeRecordedAt': 1720000011.0,
        }),
      ]);
      final rows = store.rowsFor(
        networkId: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(rows.length, 1);
      final r = rows.single;
      expect(r.valueWei, BigInt.parse('5600000000000000'));
      expect(r.gasLimit * r.gasPrice, BigInt.parse('420000000000000'));
      expect(r.broadcastOutcome, 'submission_uncertain');
      expect(r.localTxHash.length, 66);
    });

    test('refresh calls the backend once and captures errors', () async {
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: const {
          'status': 'ok',
          'outgoing': <Map<String, Object?>>[
            {
              'draftId': 'drft-refresh-1',
              'networkId': 'ethereum_mainnet',
              'asset': 'ETH',
              'unit': 'ETH',
              'decimals': 18,
              'fromAddress': _kFrom,
              'destinationAddress': _kDest,
              'transactionTo': _kDest,
              'valueWei': '1',
              'amountBaseUnits': '1',
              'dataHex': '0x',
              'gasLimit': '21000',
              'gasPrice': '1',
              'feeWei': '21000',
              'chainId': 1,
              'localTxHash':
              '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
              'aaaaaaaaaaaaaaaa',
              'broadcastOutcome': 'submitted',
              'createdAt': 1.0,
              'consumedAt': 2.0,
              'outcomeRecordedAt': 3.0,
            }
          ],
        },
      );
      final store = DurableOutgoingHistoryStore(
        client: client,
        authTokenProvider: () => 'tok',
      );
      await store.refresh('ethereum_mainnet');
      expect(client.outgoingHistoryCallCount, 1);
      final rows = store.rowsFor(
        networkId: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(rows.length, 1);
      expect(rows.single.draftId, 'drft-refresh-1');
      expect(store.lastRefreshError('ethereum_mainnet'), isNull);
    });

    test('sorted newest-first by consumedAt then createdAt', () {
      final store = DurableOutgoingHistoryStore(
        client: _FakeDurabilityClient(
          draftResponse: const {},
          encryptedSecretResponse: const {},
          broadcastResponse: const {},
        ),
        authTokenProvider: () => 'tok',
      );
      DurableOutgoingTx mk(String id, double? c) {
        final chunk = id.hashCode.toRadixString(16).padLeft(4, '0');
        final buf = StringBuffer('0x');
        for (var i = 0; i < 16; i++) {
          buf.write(chunk);
        }
        return DurableOutgoingTx.fromJson(<String, Object?>{
          'draftId': id,
          'networkId': 'ethereum_mainnet',
          'asset': 'ETH',
          'unit': 'ETH',
          'decimals': 18,
          'fromAddress': _kFrom,
          'destinationAddress': _kDest,
          'transactionTo': _kDest,
          'valueWei': '0',
          'amountBaseUnits': '0',
          'dataHex': '0x',
          'gasLimit': '0',
          'gasPrice': '0',
          'feeWei': '0',
          'chainId': 1,
          'localTxHash': buf.toString(),
          'broadcastOutcome': 'submitted',
          'createdAt': (c ?? 0.0) - 1,
          'consumedAt': c,
          'outcomeRecordedAt': c,
        });
      }
      store.seedForNetwork('ethereum_mainnet', [
        mk('old', 100.0),
        mk('new', 300.0),
        mk('mid', 200.0),
      ]);
      final rows = store.rowsFor(
        networkId: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(rows.map((r) => r.draftId).toList(),
          ['new', 'mid', 'old']);
    });
  });


  group('Three-source merge precedence', () {
    testWidgets(
        'chain-observed (indexer) confirmed WINS over durable '
        'submission_uncertain and local submissionUncertain',
        (tester) async {
      const hash = '0x'
          '783ddc09728b26884c78da47ee408c40'
          'daa75c89e03700deb216e98ed77c415b';
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: {
          'status': 'ok',
          'outgoing': <Map<String, Object?>>[{
            'draftId': 'drft-durable',
            'networkId': 'ethereum_mainnet',
            'asset': 'ETH',
            'unit': 'ETH',
            'decimals': 18,
            'fromAddress': _kFrom,
            'destinationAddress': _kDest,
            'transactionTo': _kDest,
            'valueWei': '5600000000000000',
            'amountBaseUnits': '5600000000000000',
            'dataHex': '0x',
            'gasLimit': '21000',
            'gasPrice': '20000000000',
            'feeWei': '420000000000000',
            'chainId': 1,
            'localTxHash': hash,
            'broadcastOutcome': 'submission_uncertain',
            'createdAt': 100.0,
            'consumedAt': 101.0,
            'outcomeRecordedAt': 102.0,
          }],
        },
      );
      // Wire a client that DOES surface an indexer row that names
      // the same hash but reports `confirmed`.
      final withIndexer = _IndexerFakeClient(
        base: client,
        indexerRows: [
          {
            'txHash': hash,
            'direction': 'outgoing',
            'amount': '0.0056',
            'unit': 'ETH',
            'status': 'confirmed',
            'confirmations': 12,
            'fromAddress': _kFrom,
            'toAddress': _kDest,
            'timestamp': 999,
            'source': 'indexer',
          }
        ],
      );
      final local = LocalOutgoingTxStore();
      local.upsert(LocalOutgoingTx(
        txHash: hash,
        fromAddress: _kFrom,
        toAddress: _kDest,
        amount: '0.0056',
        unit: 'ETH',
        feeWei: BigInt.from(420000000000000),
        networkId: 'ethereum_mainnet',
        asset: 'ETH',
        createdAt: DateTime.fromMillisecondsSinceEpoch(1000000),
        updatedAt: DateTime.fromMillisecondsSinceEpoch(1000000),
        status: LocalOutgoingTxStatus.submissionUncertain,
      ));
      final durable = DurableOutgoingHistoryStore(
        client: withIndexer,
        authTokenProvider: () => 'tok',
      );
      await durable.refresh('ethereum_mainnet');

      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: withIndexer,
            network: 'ethereum_mainnet',
            localStore: local,
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();

      // The rendered row for this hash MUST be confirmed — chain
      // wins over durable + local.
      expect(
        find.byKey(Key('crypto_wallet_activity_card_row_status_$hash')),
        findsOneWidget,
      );
      expect(find.text('confirmed'), findsOneWidget);
      // NEITHER "submission_uncertain" nor "submitting" should be
      // rendered for this hash — chain wins.
      expect(find.text('submission_uncertain'), findsNothing);
    });

    testWidgets(
        'durable submitted WINS over stale local submitting when '
        'no chain observation exists', (tester) async {
      const hash =
          '0x11111111111111111111111111111111'
          '11111111111111111111111111111111';
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: {
          'status': 'ok',
          'outgoing': <Map<String, Object?>>[{
            'draftId': 'drft-durable-only',
            'networkId': 'ethereum_mainnet',
            'asset': 'ETH',
            'unit': 'ETH',
            'decimals': 18,
            'fromAddress': _kFrom,
            'destinationAddress': _kDest,
            'transactionTo': _kDest,
            'valueWei': '5600000000000000',
            'amountBaseUnits': '5600000000000000',
            'dataHex': '0x',
            'gasLimit': '21000',
            'gasPrice': '20000000000',
            'feeWei': '420000000000000',
            'chainId': 1,
            'localTxHash': hash,
            'broadcastOutcome': 'submitted',
            'createdAt': 2000.0,   // durable is fresh
            'consumedAt': 2000.0,
            'outcomeRecordedAt': 2000.0,
          }],
        },
      );
      final local = LocalOutgoingTxStore();
      // Local row is in a NON local-only state (submissionUncertain)
      // that has been superseded by the fresher durable submitted.
      local.upsert(LocalOutgoingTx(
        txHash: hash,
        fromAddress: _kFrom,
        toAddress: _kDest,
        amount: '0.0056',
        unit: 'ETH',
        feeWei: BigInt.from(420000000000000),
        networkId: 'ethereum_mainnet',
        asset: 'ETH',
        createdAt: DateTime.fromMillisecondsSinceEpoch(500),
        updatedAt: DateTime.fromMillisecondsSinceEpoch(500),
        status: LocalOutgoingTxStatus.submissionUncertain,
      ));
      final durable = DurableOutgoingHistoryStore(
        client: client,
        authTokenProvider: () => 'tok',
      );
      await durable.refresh('ethereum_mainnet');

      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: client,
            network: 'ethereum_mainnet',
            localStore: local,
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text(kActivityStatusSubmitted), findsOneWidget);
      expect(
        find.text(kActivityStatusSubmissionUncertain), findsNothing,
      );
    });

    testWidgets(
        'local submitting state (transient only) WINS over stale '
        'durable that has not yet caught up', (tester) async {
      // Broadcast just happened this session — the local row says
      // `submitting`, the durable snapshot from mount does not yet
      // include this hash. Local should surface it.
      const hash =
          '0x22222222222222222222222222222222'
          '22222222222222222222222222222222';
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: const {
          'status': 'ok', 'outgoing': <Map<String, Object?>>[],
        },
      );
      final local = LocalOutgoingTxStore();
      local.upsert(LocalOutgoingTx(
        txHash: hash,
        fromAddress: _kFrom,
        toAddress: _kDest,
        amount: '0.0056',
        unit: 'ETH',
        feeWei: BigInt.from(420000000000000),
        networkId: 'ethereum_mainnet',
        asset: 'ETH',
        createdAt: DateTime.fromMillisecondsSinceEpoch(1000),
        updatedAt: DateTime.fromMillisecondsSinceEpoch(1000),
        status: LocalOutgoingTxStatus.submitting,
      ));
      final durable = DurableOutgoingHistoryStore(
        client: client,
        authTokenProvider: () => 'tok',
      );
      await durable.refresh('ethereum_mainnet');
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: client,
            network: 'ethereum_mainnet',
            localStore: local,
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text(kActivityStatusSubmitting), findsOneWidget);
    });

    testWidgets(
        'a durable-only row (no local, no indexer) still renders — '
        'simulating a fresh Flutter web reload where the in-memory '
        'store is empty but the backend still has the row',
        (tester) async {
      const hash =
          '0x33333333333333333333333333333333'
          '33333333333333333333333333333333';
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: {
          'status': 'ok',
          'outgoing': <Map<String, Object?>>[{
            'draftId': 'drft-durable-solo',
            'networkId': 'ethereum_mainnet',
            'asset': 'ETH',
            'unit': 'ETH',
            'decimals': 18,
            'fromAddress': _kFrom,
            'destinationAddress': _kDest,
            'transactionTo': _kDest,
            'valueWei': '5600000000000000',
            'amountBaseUnits': '5600000000000000',
            'dataHex': '0x',
            'gasLimit': '21000',
            'gasPrice': '20000000000',
            'feeWei': '420000000000000',
            'chainId': 1,
            'localTxHash': hash,
            'broadcastOutcome': 'submission_uncertain',
            'createdAt': 100.0,
            'consumedAt': 101.0,
            'outcomeRecordedAt': 102.0,
          }],
        },
      );
      // Local store is EMPTY — this is exactly the browser-reload
      // scenario.
      final local = LocalOutgoingTxStore();
      final durable = DurableOutgoingHistoryStore(
        client: client,
        authTokenProvider: () => 'tok',
      );
      await durable.refresh('ethereum_mainnet');

      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: client,
            network: 'ethereum_mainnet',
            localStore: local,
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      // The uncertain row MUST appear — it did not evaporate with
      // the browser reload.
      expect(
        find.byKey(Key('crypto_wallet_activity_card_row_$hash')),
        findsOneWidget,
      );
      expect(
        find.text(kActivityStatusSubmissionUncertain),
        findsOneWidget,
      );
    });

    testWidgets(
        'indexer + durable + local reporting the same hash render '
        'exactly ONCE (no duplicate rows)', (tester) async {
      const hash =
          '0x44444444444444444444444444444444'
          '44444444444444444444444444444444';
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: {
          'status': 'ok',
          'outgoing': <Map<String, Object?>>[{
            'draftId': 'drft-multi-source',
            'networkId': 'ethereum_mainnet',
            'asset': 'ETH',
            'unit': 'ETH',
            'decimals': 18,
            'fromAddress': _kFrom,
            'destinationAddress': _kDest,
            'transactionTo': _kDest,
            'valueWei': '5600000000000000',
            'amountBaseUnits': '5600000000000000',
            'dataHex': '0x',
            'gasLimit': '21000',
            'gasPrice': '20000000000',
            'feeWei': '420000000000000',
            'chainId': 1,
            'localTxHash': hash,
            'broadcastOutcome': 'submitted',
            'createdAt': 100.0,
            'consumedAt': 101.0,
            'outcomeRecordedAt': 102.0,
          }],
        },
      );
      final withIndexer = _IndexerFakeClient(
        base: client,
        indexerRows: [
          {
            'txHash': hash,
            'direction': 'outgoing',
            'amount': '0.0056',
            'unit': 'ETH',
            'status': 'pending',
            'confirmations': 0,
            'fromAddress': _kFrom,
            'toAddress': _kDest,
            'timestamp': 200,
            'source': 'indexer',
          }
        ],
      );
      final local = LocalOutgoingTxStore();
      local.upsert(LocalOutgoingTx(
        txHash: hash,
        fromAddress: _kFrom,
        toAddress: _kDest,
        amount: '0.0056',
        unit: 'ETH',
        feeWei: BigInt.from(420000000000000),
        networkId: 'ethereum_mainnet',
        asset: 'ETH',
        createdAt: DateTime.fromMillisecondsSinceEpoch(1000000),
        updatedAt: DateTime.fromMillisecondsSinceEpoch(1000000),
        status: LocalOutgoingTxStatus.submitted,
      ));
      final durable = DurableOutgoingHistoryStore(
        client: withIndexer,
        authTokenProvider: () => 'tok',
      );
      await durable.refresh('ethereum_mainnet');

      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: withIndexer,
            network: 'ethereum_mainnet',
            localStore: local,
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      // Exactly one row keyed by this hash — no dedup miss.
      expect(
        find.byKey(Key('crypto_wallet_activity_card_row_$hash')),
        findsOneWidget,
      );
    });
  });


  group('DurableOutgoingHistoryStore + activity card wiring', () {
    testWidgets(
        'activity card refreshes durable store on mount', (tester) async {
      final client = _FakeDurabilityClient(
        draftResponse: const {},
        encryptedSecretResponse: const {},
        broadcastResponse: const {},
        outgoingHistoryResponse: const {
          'status': 'ok', 'outgoing': <Map<String, Object?>>[],
        },
      );
      final durable = DurableOutgoingHistoryStore(
        client: client,
        authTokenProvider: () => 'tok',
      );
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _l10n,
        home: Scaffold(
          body: CryptoWalletActivityCard(
            asset: 'ETH',
            authToken: 'tok',
            apiClient: client,
            network: 'ethereum_mainnet',
            durableStore: durable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(client.outgoingHistoryCallCount, greaterThanOrEqualTo(1),
        reason: 'Mounting the activity card MUST kick a durable '
                'history refresh so a browser reload immediately '
                'populates from Postgres.');
    });
  });
}


/// Test helper that composes a base client with a canned indexer
/// response, so `listCryptoWalletTransactionsNetwork` returns rows
/// as if they came from the indexer.
class _IndexerFakeClient extends VaultAIClient {
  final _FakeDurabilityClient base;
  final List<Map<String, Object?>> indexerRows;

  _IndexerFakeClient({
    required this.base,
    required this.indexerRows,
  }) : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    return {
      'transactionsStatus': 'available',
      'transactions': indexerRows,
    };
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletOutgoingHistoryNetwork({
    required String network,
    required String authToken,
  }) async {
    return base.getCryptoWalletOutgoingHistoryNetwork(
      network: network, authToken: authToken,
    );
  }
}
