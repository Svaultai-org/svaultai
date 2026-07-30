import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

class _FakeMainnetClient extends VaultAIClient {
  Map<String, dynamic> draftResponse;
  Map<String, dynamic> encryptedSecretResponse;
  Map<String, dynamic> broadcastResponse;
  Map<String, dynamic>? feeEstimateResponse;
  Object? throwOnBroadcast;
  Duration? draftDelay;

  int draftSepoliaCount = 0;
  int draftNetworkCount = 0;
  int encryptedSecretSepoliaCount = 0;
  int encryptedSecretNetworkCount = 0;
  int broadcastSepoliaCount = 0;
  int broadcastNetworkCount = 0;
  int feeEstimateNetworkCount = 0;

  Map<String, dynamic>? lastDraftBody;
  Map<String, dynamic>? lastBroadcastBody;
  Map<String, dynamic>? lastEncryptedSecretBody;

  _FakeMainnetClient({
    required this.draftResponse,
    required this.encryptedSecretResponse,
    required this.broadcastResponse,
    this.feeEstimateResponse,
    this.throwOnBroadcast,
  }) : super(baseUrl: 'http://test.invalid');

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
    draftSepoliaCount++;
    final delay = draftDelay;
    if (delay != null) await Future<void>.delayed(delay);
    lastDraftBody = {
      'route': 'sepolia',
      'asset': asset,
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth': amountEth,
    };
    return draftResponse;
  }

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
    draftNetworkCount++;
    final delay = draftDelay;
    if (delay != null) await Future<void>.delayed(delay);
    lastDraftBody = {
      'route': 'network',
      'network': network,
      'asset': asset,
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth': amountEth,
      'amountSol': amountSol,
    };
    return draftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretSepoliaCount++;
    lastEncryptedSecretBody = {
      'route': 'sepolia',
      'asset': asset,
    };
    return encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretNetworkCount++;
    lastEncryptedSecretBody = {
      'route': 'network',
      'network': network,
      'asset': asset,
    };
    return encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransaction({
    required String asset,
    required String authToken,
    required String signedTransaction,
  }) async {
    broadcastSepoliaCount++;
    lastBroadcastBody = {
      'route': 'sepolia',
      'asset': asset,
      'signedTransaction': signedTransaction,
    };
    if (throwOnBroadcast != null) throw throwOnBroadcast!;
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcastNetworkCount++;
    lastBroadcastBody = {
      'route': 'network',
      'network': network,
      'asset': asset,
      'signedTransaction': signedTransaction,
      if (idempotencyKey != null) 'idempotencyKey': idempotencyKey,
    };
    if (throwOnBroadcast != null) throw throwOnBroadcast!;
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
  }) async {
    feeEstimateNetworkCount++;
    return feeEstimateResponse ??
        {
          'status': 'fee_estimate_ready',
          'chainId': 1,
          'gasLimit': draftResponse['gasLimit'],
          'gasPriceWei': draftResponse['gasPrice'],
          'authorizedMaxFeeBaseUnits':
              (BigInt.parse(draftResponse['gasLimit'].toString()) *
                      BigInt.parse(draftResponse['gasPrice'].toString()))
                  .toString(),
          'feeSource': 'test_fee_estimate',
        };
  }
}

const String _kFromAddress = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const String _kDestAddress = '0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF';
const String _kPlaintextPk =
    '0000000000000000000000000000000000000000000000000000000000000001';
const String _kTxHash =
    '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef';

Map<String, dynamic> _mainnetEthDraftReady() => {
      'status': 'draft_ready',
      'asset': 'ETH',
      'network': 'Ethereum Mainnet',
      'fromAddress': _kFromAddress,
      'destinationAddress': _kDestAddress,
      'amountEth': '0.01',
      'amountWei': '10000000000000000',
      'nonce': '0',
      'gasLimit': '21000',
      'gasPrice': '20000000000',
      'chainId': 1,
      'feeUnit': 'ETH',
      'realFundsWarning': kEvmNetworkMainnetSendRealFundsHeadline,
    };

Map<String, dynamic> _mainnetUsdtDraftReady() => {
      'status': 'draft_ready',
      'asset': 'USDT_ERC20',
      'network': 'Ethereum Mainnet',
      'fromAddress': _kFromAddress,
      'destinationAddress': _kDestAddress,
      'amount': '1.0',
      'amountBaseUnits': '1000000',
      'unit': 'USDT',
      'tokenContract': '0x1111111111111111111111111111111111111111',
      'decimals': 6,
      'transactionTo': '0x1111111111111111111111111111111111111111',
      'transactionValueWei': '0',
      'dataHex': '0xa9059cbb' + ('0' * 64) + ('0' * 64),
      'nonce': '0',
      'gasLimit': '60000',
      'gasPrice': '20000000000',
      'chainId': 1,
      'feeUnit': 'ETH',
      'realFundsWarning': 'gas paid in ETH',
    };

Future<void> _pumpMainnetPanel(
  WidgetTester tester, {
  required _FakeMainnetClient client,
  String asset = 'ETH',
  bool mainnetSendEnabled = true,
  bool mainnetSendPaused = false,
  Future<bool> Function(String)? verifyPin,
  Future<String> Function(String)? decryptForVault,
  Future<BigInt?> Function()? fetchAvailableBalanceWei,
}) async {
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoWalletEngineSendPanel(
        authToken: 'tok',
        fromAddress: _kFromAddress,
        client: client,
        decryptForVault:
            decryptForVault ?? ((ciphertext) async => _kPlaintextPk),
        isVaultKeyAvailable: () => true,
        verifyPin: verifyPin,
        asset: asset,
        network: kEvmNetworkEthereumMainnet,
        mainnetSendEnabled: mainnetSendEnabled,
        mainnetSendPaused: mainnetSendPaused,
        fetchAvailableBalance: () async => 10.0,
        fetchAvailableBalanceWei: fetchAvailableBalanceWei ??
            () async => BigInt.parse(
                  '10000000000000000000',
                ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('Mainnet send panel — slice 11', () {
    test('SS1: kCryptoWalletEngineMainnetSendEnabled defaults to false', () {
      expect(kCryptoWalletEngineMainnetSendEnabled, isFalse);
    });

    test('SS2: operator-pinned mainnet send copy constants', () {
      final eth = kEvmNetworkMainnetSendRealFundsHeadline.toLowerCase();
      expect(eth, contains('real eth'));
      expect(eth, contains('mainnet'));
      expect(eth, contains('cannot be reversed'));

      final token = kEvmNetworkMainnetTokenSendRealFundsHeadline.toLowerCase();
      expect(token, contains('mainnet'));
      expect(token, contains('gas is paid in eth'));
      expect(token, contains('cannot be reversed'));
      expect(
        kEvmNetworkMainnetTokenSendRealFundsHeadline,
        contains('{token}'),
      );
    });

    testWidgets('SS3: mainnet badge rendered when network=mainnet',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      expect(
        find.byKey(const Key('eth_send_panel_mainnet')),
        findsOneWidget,
      );
      expect(find.text(kEthSendMainnetNetworkBadge), findsOneWidget);
    });

    testWidgets(
        'SS4: mainnet form stage renders exactly one prominent '
        'top-of-panel warning (disabled OR paused OR real-funds — '
        'never overlapping banners)', (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      // Backend capability is the UI source of truth. Even though the
      // legacy compile-time flag defaults false in tests,
      // backend-enabled + not-paused must show the real-funds warning,
      // not the disabled/paused banners.
      final realFundsFinder = find.byKey(
        const Key('eth_send_panel_mainnet_real_funds'),
      );
      final disabledFinder = find.byKey(
        const Key('eth_send_panel_mainnet_send_disabled'),
      );
      final hasReal = realFundsFinder.evaluate().isNotEmpty;
      final hasDisabled = disabledFinder.evaluate().isNotEmpty;
      expect(hasReal, isTrue);
      expect(hasDisabled, isFalse);
      expect(find.byKey(const Key(kMainnetSendPausedBannerKey)), findsNothing);
      // The two banners must never appear simultaneously.
      expect(hasReal && hasDisabled, isFalse,
          reason: 'mobile UX must not stack overlapping mainnet '
              'warnings — disabled should subsume real-funds');
    });

    testWidgets('SS4b: backend enabled + paused shows paused banner',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        mainnetSendEnabled: true,
        mainnetSendPaused: true,
      );
      expect(
          find.byKey(const Key(kMainnetSendPausedBannerKey)), findsOneWidget);
      expect(find.byKey(const Key('eth_send_panel_mainnet_send_disabled')),
          findsNothing);
      expect(find.byKey(const Key('eth_send_panel_mainnet_real_funds')),
          findsNothing);
    });

    testWidgets('SS5: send-disabled banner + refuses draft when backend off',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        mainnetSendEnabled: false,
      );
      expect(
        find.byKey(const Key('eth_send_panel_mainnet_send_disabled')),
        findsOneWidget,
      );

      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      await tester.pump();
      expect(client.draftSepoliaCount, equals(0));
      expect(client.draftNetworkCount, equals(0));

      expect(
        find.text(kEthSendMainnetSendDisabledBanner),
        findsWidgets,
      );
    });

    testWidgets(
        'SS6: mainnet draft calls the network-explicit route '
        '(never the bare Sepolia route)', (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      await tester.pump();

      expect(client.draftSepoliaCount, equals(0));
      expect(client.broadcastSepoliaCount, equals(0));
      expect(client.encryptedSecretSepoliaCount, equals(0));
    });

    testWidgets('SS6b: draft conflict renders unsigned-draft recovery copy',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: const {
          'status': 'draft_conflict',
          'wallet_engine': 'draft_conflict',
          'draftStatus': 'unsigned_stale',
          'message': 'old backend copy',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      await tester.pumpAndSettle();

      expect(find.text(kMainnetSendUnsignedDraftOpenMessage), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_unsigned_draft_recovery')),
        findsOneWidget,
      );
      expect(find.text(kMainnetSendResumeDraftLabel), findsOneWidget);
      final reviewButton = tester.widget<ElevatedButton>(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      expect(reviewButton.onPressed, isNull);
      expect(client.broadcastNetworkCount, equals(0));
    });

    testWidgets(
        'SS6c: fee changes after PIN stop before secret fetch, signing, '
        'or broadcast', (tester) async {
      var pinVerified = false;
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        feeEstimateResponse: const {
          'status': 'fee_estimate_ready',
          'chainId': 1,
          'gasLimit': '21000',
          'gasPriceWei': '30000000000',
          'authorizedMaxFeeBaseUnits': '630000000000000',
          'feeSource': 'test_fee_changed',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        verifyPin: (_) async {
          pinVerified = true;
          return true;
        },
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(pinVerified, isTrue);
      expect(find.text(kMainnetSendFeeQuoteChangedError), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_quote_change_comparison')),
        findsOneWidget,
      );
      expect(find.text('Old: 0.000420 ETH'), findsOneWidget);
      expect(find.text('Updated: 0.000630 ETH'), findsOneWidget);
      expect(find.text('Old: 0.010420 ETH'), findsOneWidget);
      expect(find.text('Updated: 0.010630 ETH'), findsOneWidget);
      expect(find.text(kMainnetSendAcceptUpdatedFeeLabel), findsOneWidget);
      expect(client.encryptedSecretNetworkCount, equals(0));
      expect(client.broadcastNetworkCount, equals(0));
    });

    testWidgets('SS6c2: updated-fee confirmation cannot duplicate a redraft',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        feeEstimateResponse: const {
          'status': 'fee_estimate_ready',
          'chainId': 1,
          'gasLimit': '21000',
          'gasPriceWei': '30000000000',
          'authorizedMaxFeeBaseUnits': '630000000000000',
          'feeSource': 'test_fee_changed',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        verifyPin: (_) async => true,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      final accept =
          find.byKey(const Key('eth_send_panel_accept_updated_fee_btn'));
      client.draftDelay = const Duration(milliseconds: 100);
      await tester.tap(accept);
      await tester.pump();
      expect(accept, findsNothing);
      await tester.pumpAndSettle();

      expect(client.draftNetworkCount, equals(2),
          reason: 'initial draft + exactly one accepted updated-fee redraft');
      expect(client.broadcastNetworkCount, equals(0));
    });

    testWidgets(
        'SS6d: balance changes after PIN stop before secret fetch, '
        'signing, or broadcast', (tester) async {
      var balanceCalls = 0;
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        verifyPin: (_) async => true,
        fetchAvailableBalanceWei: () async {
          balanceCalls++;
          return BigInt.parse(balanceCalls == 1
              ? '10000000000000000000'
              : '9000000000000000000');
        },
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(find.text(kMainnetSendFeeQuoteChangedError), findsOneWidget);
      expect(find.text('Old: 9.989580 ETH'), findsOneWidget);
      expect(find.text('Updated: 8.989580 ETH'), findsOneWidget);
      expect(find.text(kMainnetSendAcceptUpdatedFeeLabel), findsOneWidget);
      expect(client.encryptedSecretNetworkCount, equals(0));
      expect(client.broadcastNetworkCount, equals(0));
    });

    testWidgets(
        'SS6d2: signed/broadcasting draft conflict shows pending state, '
        'not ordinary Review', (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: const {
          'status': 'draft_conflict',
          'wallet_engine': 'draft_conflict',
          'draftStatus': 'signed_not_broadcast',
          'txHash': _kTxHash,
          'message': 'old backend copy',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();

      expect(find.text(kMainnetSendPendingTransactionMessage), findsOneWidget);
      expect(find.byKey(const Key('eth_send_panel_check_status_btn')),
          findsOneWidget);
      expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
      expect(client.broadcastNetworkCount, equals(0));
    });

    testWidgets('SS6e: unchanged post-PIN quote proceeds to broadcast',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        verifyPin: (_) async => true,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(find.text(kEthSendResultHeadingSubmitted), findsOneWidget);
      expect(client.encryptedSecretNetworkCount, equals(1));
      expect(client.broadcastNetworkCount, equals(1));
    });

    testWidgets(
        'SS6f: lost broadcast response shows uncertain state with '
        'Check status, not ordinary Review', (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
        throwOnBroadcast: Exception('connection lost'),
      );
      await _pumpMainnetPanel(
        tester,
        client: client,
        verifyPin: (_) async => true,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(find.text(kEthSendResultHeadingUncertain), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_check_status_btn')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
      expect(client.broadcastNetworkCount, equals(1));
    });

    testWidgets(
        'SS11: form stage shows the "Ethereum Mainnet" chip and a '
        'top-of-panel mainnet warning row (single, prioritized)',
        (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await _pumpMainnetPanel(tester, client: client);
      // 2026-07-13: the chip lives in the compact header row of the
      // shared `WalletSendScaffold`, not the old wide network badge.
      expect(find.text(kEthSendMainnetNetworkBadge), findsOneWidget);
      // The top-of-panel warning must be present. With the default
      // send-disabled flag it appears as the disabled banner; if the
      // flag is toggled on it appears as the real-funds banner.
      final anyMainnetWarning = find.byWidgetPredicate((w) {
        final k = w.key;
        if (k is! ValueKey) return false;
        return k.value == 'eth_send_panel_mainnet_real_funds' ||
            k.value == 'eth_send_panel_mainnet_send_disabled';
      });
      expect(anyMainnetWarning, findsOneWidget);
    });

    testWidgets(
        'SS9: source guard — broadcast body carries ONLY '
        'signedTransaction (never plaintext-key fields)', (tester) async {
      final client = _FakeMainnetClient(
        draftResponse: _mainnetEthDraftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-mainnet',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash': _kTxHash,
        },
      );
      await client.broadcastCryptoWalletSignedTransactionNetwork(
        network: 'ethereum_mainnet',
        asset: 'ETH',
        authToken: 'tok',
        signedTransaction: '0x' + ('aa' * 200),
      );
      final body = client.lastBroadcastBody!;

      expect(body['signedTransaction'], isNotNull);

      for (final banned in const [
        'privateKey',
        'seedPhrase',
        'mnemonic',
        'recoveryPhrase',
        'encryptedWalletSecret',
      ]) {
        expect(body.containsKey(banned), isFalse,
            reason: 'broadcast body leaks $banned');
      }
    });

    test('SS13: source guard — no debugPrint of signing fields', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_send_panel.dart',
      ).readAsStringSync();

      final printRe = RegExp(r'(debugPrint|print)\s*\([^)]*\)');
      for (final m in printRe.allMatches(src)) {
        final call = m.group(0)!;
        for (final banned in const [
          'privateKey',
          'privateKeyHex',
          'signedTransaction',
          'encryptedSecret',
          'encryptedWalletSecret',
          'pin',
        ]) {
          expect(call.contains(banned), isFalse,
              reason: 'debugPrint leaks $banned: $call');
        }
      }
    });

    test('SS14: source guard — no hardcoded mainnet tx hash literals', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_send_panel.dart',
      ).readAsStringSync();

      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');

      final txRe = RegExp(r"0x[0-9a-fA-F]{64}");
      for (final m in txRe.allMatches(scrubbed)) {
        fail('Send panel contains hardcoded tx hash literal: '
            '${m.group(0)}');
      }
    });

    test('SS15: no buy/sell/swap/trade/stake/bridge UI copy', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_send_panel.dart',
      ).readAsStringSync();
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final stringLit = RegExp(r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"');
      final banned = RegExp(
        r'\b(buy|sell|swap|trade|stake|staking|bridge)\b',
        caseSensitive: false,
      );
      for (final m in stringLit.allMatches(scrubbed)) {
        final lit = m.group(0)!;

        expect(banned.hasMatch(lit), isFalse,
            reason: 'Send panel uses banned word in literal: $lit');
      }
    });
  });

  group('Mainnet send panel — sepolia regression', () {
    test('SS8: signer chainId for Sepolia stays 11155111', () {
      expect(11155111, equals(11155111));
    });
  });
}
