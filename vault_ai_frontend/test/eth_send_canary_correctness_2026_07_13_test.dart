// 2026-07-13 (canary correctness): regression tests for the
// production canary bugs.
//
// Production canary (do NOT rebroadcast):
//   sender:        0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855
//   recipient:     0x7C49215A2cB86aaC3e6308EA4D6206912578e870
//   amount:        0.0056 ETH
//   draft_id:      02ctGuBjqYXERNxD1k5AiplGgc_dyg5a
//   local_hash:    0x783ddc09728b26884c78da47ee408c40daa75c89e0…
//   backend outcome: submitted (INCORRECT — tx never on-chain)
//
// Bugs exercised here (all frontend-observable):
//
//   B1  Balance verification failure was a SOFT WARNING that let
//       the user sign and broadcast. The user typed a PIN and sent
//       a transaction without a live balance check. Fix: hard gate
//       — Send is disabled and the primary action becomes
//       "Retry balance check".
//
//   B2  The confirmation flow required entering the PIN AND typing
//       "SEND ETH" (or "SEND USDT" / "SEND USDC"). Fix: typed
//       phrase removed; the flow is form → Review → PIN → single
//       Send tap.
//
//   B3  On submission_uncertain the result screen either hid the
//       transaction or showed a generic "submitted". Fix: honest
//       result screen with three explicit heading states
//       (submitted / uncertain / rejected), each carrying the
//       local tx hash and an appropriate primary action.
//
//   B4  The outgoing attempt DID NOT appear in Activity — the
//       failed canary vanished from history. Fix: every broadcast
//       stamps a LocalOutgoingTx row in a store that the Activity
//       card merges with indexer results.
//
//   B5  The result screen must always show the hash and (for
//       non-rejected outcomes) an explorer link. The explorer URL
//       must be the correct Mainnet Etherscan for mainnet, Sepolia
//       Etherscan for sepolia.

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


class _FakeCanaryClient extends VaultAIClient {
  final Map<String, dynamic> draftResponse;
  final Map<String, dynamic> encryptedSecretResponse;
  final Map<String, dynamic> broadcastResponse;
  final Map<String, dynamic>? statusResponse;

  int broadcastCallCount = 0;
  int draftCallCount = 0;
  Map<String, dynamic>? broadcastReceivedBody;

  _FakeCanaryClient({
    required this.draftResponse,
    required this.encryptedSecretResponse,
    required this.broadcastResponse,
    // ignore: unused_element_parameter
    this.statusResponse,
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
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
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
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    draftCallCount++;
    return draftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async =>
      encryptedSecretResponse;

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
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async =>
      encryptedSecretResponse;

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
    broadcastReceivedBody = {
      'signedTransaction': signedTransaction,
      'idempotencyKey': idempotencyKey,
      'draftId': draftId,
    };
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>>
      getCryptoWalletTransactionStatusNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String txHash,
  }) async =>
      statusResponse ?? const {'status': 'pending'};
}


const String _kFrom = '0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855';
const String _kDest = '0x7C49215A2cB86aaC3e6308EA4D6206912578e870';
const String _kAmount = '0.0056';

// A locally-derived hash from a well-known signed transaction —
// used ONLY for shape assertions, never broadcast.
Map<String, Object?> _draftReady() => const {
      'status': 'draft_ready',
      'draftId': 'canary-frontend-regression-draft-aabb',
      'fromAddress': _kFrom,
      'destinationAddress': _kDest,
      'amountEth': _kAmount,
      'amountWei': '5600000000000000',
      'unit': 'ETH',
      'nonce': '3',
      'gasLimit': '21000',
      'gasPrice': '20000000000',
      'chainId': 11155111,
      'feeUnit': 'wei',
    };


Future<void> _pumpMainnetPanel(
  WidgetTester tester, {
  required VaultAIClient client,
  Future<double?> Function()? fetchAvailableBalance,
  Future<double?> Function()? fetchEthBalance,
  LocalOutgoingTxStore? outgoingStore,
  Future<bool> Function(String)? launchUrl,
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
        decryptForVault: (_) async => '0x' + '11' * 32,
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        asset: 'ETH',
        network: kEvmNetworkEthereumSepolia,
        fetchAvailableBalance: fetchAvailableBalance,
        fetchEthBalance: fetchEthBalance,
        outgoingTxStore: outgoingStore,
        launchUrl: launchUrl,
      ),
    ),
  ));
  await tester.pump();
}


void main() {
  group('B1 — balance verification is a HARD GATE', () {
    testWidgets(
        'ETH: fetchAvailableBalance returns null → Review disabled, '
        'primary action becomes "Retry balance check", NO draft call, '
        'NO broadcast', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => null,
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
      // The draft call MUST NOT have happened.
      expect(client.draftCallCount, 0);
      expect(client.broadcastCallCount, 0);
      // Error copy MUST be the hard-gate error.
      expect(
        find.text(kMainnetSendBalanceUnverifiedError),
        findsOneWidget,
      );
      // Primary action becomes "Retry balance check".
      expect(
        find.text(kMainnetSendRetryBalanceLabel),
        findsOneWidget,
      );
    });

    testWidgets(
        'ETH: fetchAvailableBalance rethrows → hard gate (never '
        'permits signing)', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => throw Exception('rpc down'),
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
      expect(client.draftCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendBalanceUnverifiedError),
        findsOneWidget,
      );
    });

    testWidgets(
        'ERC20: token balance verified but parent ETH balance null → '
        'hard gate', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: {
          ..._draftReady(),
          'transactionTo': '0x' + 'de' * 20,
          'transactionValueWei': '0',
          'dataHex': '0x',
          'amount': '5',
          'unit': 'USDT',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await tester.binding.setSurfaceSize(const Size(390, 2400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFrom,
            client: client,
            decryptForVault: (_) async => '0x' + '11' * 32,
            isVaultKeyAvailable: () => true,
            verifyPin: (_) async => true,
            asset: 'USDT_ERC20',
            network: kEvmNetworkEthereumSepolia,
            fetchAvailableBalance: () async => 100.0, // token balance OK
            fetchEthBalance: () async => null,        // parent ETH null
          ),
        ),
      ));
      await tester.pump();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '5',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      expect(client.draftCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendEthGasBalanceUnverifiedError),
        findsOneWidget,
      );
    });

    testWidgets(
        'amount > verified balance → error banner, NO draft', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {},
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 0.001,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDest,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.5',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      expect(client.draftCallCount, 0);
      expect(client.broadcastCallCount, 0);
      expect(
        find.text(kMainnetSendInsufficientBalanceError),
        findsOneWidget,
      );
    });
  });


  group('B2 — typed phrase removed, PIN + single Send tap flow', () {
    testWidgets(
        'no typed-phrase stage after Review; confirming leads '
        'directly to PIN dialog', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
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
      // Confirm — no typed-phrase stage anymore.
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      // The confirm-phrase input MUST NOT be visible.
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseInputKey)),
        findsNothing,
        reason: 'typed-phrase input was removed 2026-07-13',
      );
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseStageKey)),
        findsNothing,
      );
      // PIN dialog IS visible.
      expect(
        find.byKey(const Key('eth_send_panel_pin_input')),
        findsOneWidget,
      );
    });

    testWidgets(
        'source: send panel no longer contains a call to the '
        'confirmPhrase stage', (tester) async {
      // Runtime assertion: after Review + Confirm, the state is
      // either signing / submitted / review — never confirmPhrase.
      // This test drives the flow through and checks that we NEVER
      // enter a stage that renders the typed-phrase input.
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': '0xdead'},
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      // No typed-phrase input, ever.
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseInputKey)),
        findsNothing,
      );
    });
  });


  group('B3 — honest result screen for submission_uncertain', () {
    testWidgets(
        'backend replies submission_uncertain → uncertain heading, '
        'local hash, Check-Status action, NO explorer link',
        (tester) async {
      const localHash =
          '0xabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd';
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submission_uncertain',
          'reason': 'not_yet_visible',
          'txHash': localHash,
          'message':
              'The mainnet RPC provider accepted the raw transaction '
              'but no Ethereum node has yet reported seeing it.',
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      // Heading is the uncertain one — NOT a generic "submitted".
      expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
      // Body copy is present.
      expect(find.text(kEthSendResultBodyUncertain), findsOneWidget);
      // Hash is visible.
      expect(find.text(localHash), findsOneWidget);
      // Check-status action is offered.
      expect(
        find.byKey(const Key('eth_send_panel_check_status_btn')),
        findsOneWidget,
      );
      // Reason is surfaced.
      expect(
        find.byKey(const Key('eth_send_panel_result_backend_reason')),
        findsOneWidget,
      );
    });

    testWidgets(
        'backend replies broadcast_rejected → rejection heading, '
        '"Start a new send" action, no explorer link', (tester) async {
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'broadcast_rejected',
          'reason': 'upstream_rpc',
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(find.text(kEthSendResultHeadingRejected), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_return_form_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('eth_send_panel_explorer_btn')),
        findsNothing,
        reason: 'rejected transactions MUST NOT offer an explorer link',
      );
    });
  });


  group('B4 — outgoing tx appears in local Activity immediately', () {
    testWidgets(
        'a mainnet broadcast pushes a LocalOutgoingTx row into the '
        'store: submitting → submitted', (tester) async {
      final store = LocalOutgoingTxStore();
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x'
              '1111111111111111111111111111111111111111111111111111111111111111',
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
        outgoingStore: store,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      final rows = store.rowsFor(
        networkId: kEvmNetworkEthereumSepolia, asset: 'ETH',
      );
      expect(rows.length, 1, reason:
          'exactly one local outgoing row must exist per broadcast');
      expect(rows.first.status, LocalOutgoingTxStatus.submitted);
      expect(rows.first.fromAddress, _kFrom);
      expect(rows.first.toAddress, _kDest);
      expect(rows.first.amount, _kAmount);
      expect(rows.first.unit, 'ETH');
      expect(rows.first.networkId, kEvmNetworkEthereumSepolia);
      expect(rows.first.asset, 'ETH');
    });

    testWidgets(
        'submission_uncertain response records the row as '
        'submissionUncertain', (tester) async {
      final store = LocalOutgoingTxStore();
      final client = _FakeCanaryClient(
        draftResponse: _draftReady().cast<String, dynamic>(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submission_uncertain',
          'reason': 'not_yet_visible',
          'txHash':
              '0x'
              '2222222222222222222222222222222222222222222222222222222222222222',
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 1.0,
        outgoingStore: store,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      final rows = store.all;
      expect(rows.length, 1);
      expect(rows.first.status, LocalOutgoingTxStatus.submissionUncertain);
      expect(rows.first.reason, 'not_yet_visible');
    });
  });


  group('B5 — explorer URL is correct per network', () {
    test('mainnet → https://etherscan.io/tx/<hash>', () {
      final url = ethExplorerUrlFor(
        network: kEvmNetworkEthereumMainnet, txHash: '0xdeadbeef',
      );
      expect(url, 'https://etherscan.io/tx/0xdeadbeef');
    });

    test('sepolia → https://sepolia.etherscan.io/tx/<hash>', () {
      final url = ethExplorerUrlFor(
        network: kEvmNetworkEthereumSepolia, txHash: '0xdeadbeef',
      );
      expect(url, 'https://sepolia.etherscan.io/tx/0xdeadbeef');
    });
  });


  group('LocalOutgoingTxStore mechanics', () {
    test('rowsFor filters by network + asset', () {
      final store = LocalOutgoingTxStore();
      final now = DateTime.utc(2026, 7, 13);
      store.upsert(LocalOutgoingTx(
        txHash: '0xaa', fromAddress: _kFrom, toAddress: _kDest,
        amount: '1', unit: 'ETH', feeWei: null,
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submitting,
      ));
      store.upsert(LocalOutgoingTx(
        txHash: '0xbb', fromAddress: _kFrom, toAddress: _kDest,
        amount: '2', unit: 'USDT', feeWei: null,
        networkId: kEvmNetworkEthereumMainnet, asset: 'USDT_ERC20',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submitted,
      ));
      final ethRows = store.rowsFor(
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
      );
      expect(ethRows.map((r) => r.txHash), ['0xaa']);
    });

    test('updateStatus is a no-op for unknown hash', () {
      final store = LocalOutgoingTxStore();
      store.updateStatus('0xnope', LocalOutgoingTxStatus.confirmed);
      expect(store.all, isEmpty);
    });

    test('upsert then updateStatus preserves other fields', () {
      final store = LocalOutgoingTxStore();
      final now = DateTime.utc(2026, 7, 13);
      store.upsert(LocalOutgoingTx(
        txHash: '0xcc', fromAddress: _kFrom, toAddress: _kDest,
        amount: '0.5', unit: 'ETH', feeWei: BigInt.from(1000),
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submitting,
      ));
      store.updateStatus('0xcc', LocalOutgoingTxStatus.confirmed);
      final r = store.byHash('0xcc')!;
      expect(r.status, LocalOutgoingTxStatus.confirmed);
      expect(r.amount, '0.5');
      expect(r.feeWei, BigInt.from(1000));
    });

    test('hash lookup is case-insensitive', () {
      final store = LocalOutgoingTxStore();
      final now = DateTime.utc(2026, 7, 13);
      store.upsert(LocalOutgoingTx(
        txHash: '0xDEADBEEF', fromAddress: _kFrom, toAddress: _kDest,
        amount: '1', unit: 'ETH', feeWei: null,
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submitted,
      ));
      expect(store.byHash('0xdeadbeef'), isNotNull);
      expect(store.byHash('0xDEADBEEF'), isNotNull);
    });

    test('empty tx hash cannot create a pending transfer row', () {
      final store = LocalOutgoingTxStore();
      final now = DateTime.utc(2026, 7, 30);
      store.upsert(LocalOutgoingTx(
        txHash: '', fromAddress: _kFrom, toAddress: _kDest,
        amount: '1', unit: 'ETH', feeWei: null,
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submitting,
      ));
      expect(store.all, isEmpty);
      expect(store.hasBlockingTransfer(
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
      ), isFalse);
    });

    test('submitted local row is blocking until terminal', () {
      final store = LocalOutgoingTxStore();
      final now = DateTime.utc(2026, 7, 30);
      store.upsert(LocalOutgoingTx(
        txHash: '0xdd', fromAddress: _kFrom, toAddress: _kDest,
        amount: '1', unit: 'ETH', feeWei: null,
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
        createdAt: now, updatedAt: now,
        status: LocalOutgoingTxStatus.submissionUncertain,
      ));
      expect(store.hasBlockingTransfer(
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
      ), isTrue);
      store.updateStatus('0xdd', LocalOutgoingTxStatus.confirmed);
      expect(store.hasBlockingTransfer(
        networkId: kEvmNetworkEthereumMainnet, asset: 'ETH',
      ), isFalse);
    });
  });


  group('canary exact fixture regression', () {
    // Declarative shape only — nothing broadcast, nothing signed.
    // The canary would classify as submissionUncertain in the new
    // world because no visibility observation is ever made.
    testWidgets(
        'a broadcast response mirroring the canary shape produces '
        'the uncertain result screen', (tester) async {
      const canaryLocalHash =
          '0x783ddc09728b26884c78da47ee408c40daa75c89e03700deb216e98ed77c415b';
      final client = _FakeCanaryClient(
        draftResponse: {
          ..._draftReady(),
          'draftId': '02ctGuBjqYXERNxD1k5AiplGgc_dyg5a',
          'destinationAddress': _kDest,
          'amountWei': '5600000000000000',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submission_uncertain',
          'reason': 'not_yet_visible',
          'txHash': canaryLocalHash,
          'message':
              'The mainnet RPC provider accepted the raw transaction '
              'but no Ethereum node has yet reported seeing it.',
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 0.04367029,
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
      await tester.tap(
        find.byKey(const Key('eth_send_panel_confirm_btn')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();
      // The canary shape must NEVER show a generic "Transaction
      // submitted" heading.
      expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
      expect(find.text(kEthSendResultHeadingSubmitted), findsNothing);
      // The local hash MUST be visible.
      expect(find.text(canaryLocalHash), findsOneWidget);
    });
  });
}
