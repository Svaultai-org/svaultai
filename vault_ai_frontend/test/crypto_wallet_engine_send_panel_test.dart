import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

class _FakeSendClient extends VaultAIClient {
  Map<String, dynamic> _draftResponse;
  Map<String, dynamic> _encryptedSecretResponse;
  Map<String, dynamic> _broadcastResponse;
  Map<String, dynamic>? _feeEstimateResponse;
  Completer<Map<String, dynamic>>? broadcastCompleter;
  Object? throwOnBroadcast;

  int draftCallCount = 0;
  int feeEstimateCallCount = 0;
  int encryptedSecretCallCount = 0;
  int broadcastCallCount = 0;

  Map<String, dynamic>? lastDraftBody;
  Map<String, dynamic>? lastBroadcastBody;

  _FakeSendClient({
    required Map<String, dynamic> draftResponse,
    required Map<String, dynamic> encryptedSecretResponse,
    required Map<String, dynamic> broadcastResponse,
    Map<String, dynamic>? feeEstimateResponse,
    this.broadcastCompleter,
    // ignore: unused_element_parameter
    this.throwOnBroadcast,
  })  : _draftResponse = draftResponse,
        _encryptedSecretResponse = encryptedSecretResponse,
        _feeEstimateResponse = feeEstimateResponse,
        _broadcastResponse = broadcastResponse,
        super(baseUrl: 'http://test.invalid');

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
    lastDraftBody = {
      'asset': asset,
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth': amountEth,
    };
    return _draftResponse;
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
    draftCallCount++;
    lastDraftBody = {
      'network': network,
      'asset': asset,
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth': amountEth,
      'amountSol': amountSol,
      'amountUsdt': amountUsdt,
    };
    return _draftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return _encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    return _encryptedSecretResponse;
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransaction({
    required String asset,
    required String authToken,
    required String signedTransaction,
  }) async {
    broadcastCallCount++;
    lastBroadcastBody = {
      'asset': asset,
      'signedTransaction': signedTransaction,
    };
    if (throwOnBroadcast != null) {
      throw throwOnBroadcast!;
    }
    if (broadcastCompleter != null) {
      return broadcastCompleter!.future;
    }
    return _broadcastResponse;
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
    broadcastCallCount++;
    lastBroadcastBody = {
      'network': network,
      'asset': asset,
      'signedTransaction': signedTransaction,
      'idempotencyKey': idempotencyKey,
      'draftId': draftId,
    };
    if (throwOnBroadcast != null) {
      throw throwOnBroadcast!;
    }
    if (broadcastCompleter != null) {
      return broadcastCompleter!.future;
    }
    return _broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
  }) async {
    feeEstimateCallCount++;
    return _feeEstimateResponse ??
        {
          'status': 'fee_estimate_ready',
          'network': network,
          'asset': asset,
          'authorizedMaxFeeBaseUnits': '420000000000000',
          'gasLimit': '21000',
          'gasPriceWei': '20000000000',
          'chainId': network == kEvmNetworkEthereumMainnet ? 1 : 11155111,
          'feeSource': 'test_fee_estimate',
        };
  }
}

const String _kFromAddress = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const String _kDestAddress = '0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF';

const String _kPlaintextPk =
    '0000000000000000000000000000000000000000000000000000000000000001';

Map<String, dynamic> _draftReady({
  int chainId = 11155111,
  String gasLimit = '21000',
  String gasPrice = '20000000000',
}) =>
    {
      'status': 'draft_ready',
      'asset': 'ETH',
      'network': 'Ethereum Sepolia',
      'fromAddress': _kFromAddress,
      'destinationAddress': _kDestAddress,
      'amountEth': '0.01',
      'amountWei': '10000000000000000',
      'nonce': '0',
      'gasLimit': gasLimit,
      'gasPrice': gasPrice,
      'chainId': chainId,
    };

Future<void> _pumpPanel(
  WidgetTester tester, {
  required _FakeSendClient client,
  Future<String> Function(String)? decryptForVault,
  bool keyAvailable = true,
  Future<bool> Function(String)? verifyPin,
  String network = kEvmNetworkEthereumSepolia,
  bool mainnetSendEnabled = false,
  bool mainnetSendPaused = false,
  Future<double?> Function()? fetchAvailableBalance,
  Future<BigInt?> Function()? fetchAvailableBalanceWei,
  DateTime Function()? clock,
}) async {
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoWalletEngineSendPanel(
        authToken: 'tok',
        fromAddress: _kFromAddress,
        client: client,
        decryptForVault:
            decryptForVault ?? ((ciphertext) async => _kPlaintextPk),
        isVaultKeyAvailable: () => keyAvailable,
        verifyPin: verifyPin,
        network: network,
        mainnetSendEnabled: mainnetSendEnabled,
        mainnetSendPaused: mainnetSendPaused,
        fetchAvailableBalance: fetchAvailableBalance,
        fetchAvailableBalanceWei: fetchAvailableBalanceWei,
        clock: clock,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

void main() {
  group('crypto_wallet_engine_send_panel slice 3', () {
    testWidgets('SP1: Review with empty inputs → missing-fields error',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(tester, client: client);
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pump();
      expect(find.text(kEthSendFormValidationMissingFields), findsOneWidget);
      expect(client.draftCallCount, equals(0));
    });

    testWidgets('SP2: bad destination → bad-address error', (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': 'xxx'},
      );
      await _pumpPanel(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        'not-an-address',
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0.01',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pump();
      expect(find.text(kEthSendFormValidationBadAddress), findsOneWidget);
      expect(client.draftCallCount, equals(0));
    });

    testWidgets('SP3: non-positive amount → bad-amount error', (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': 'xxx'},
      );
      await _pumpPanel(tester, client: client);
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '0',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pump();
      expect(find.text(kEthSendFormValidationBadAmount), findsOneWidget);
      expect(client.draftCallCount, equals(0));
    });

    testWidgets('SP4: valid inputs → draft request with closed-set body',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': 'xxx'},
      );
      await _pumpPanel(tester, client: client);
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
      expect(client.draftCallCount, equals(1));
      expect(
          client.lastDraftBody,
          equals({
            'asset': 'ETH',
            'fromAddress': _kFromAddress,
            'destinationAddress': _kDestAddress,
            'amountEth': '0.01',
          }));
    });

    testWidgets('SP5: Review stage renders from/dest/amount/fee/total/network',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {'status': 'submitted', 'txHash': 'xxx'},
      );
      await _pumpPanel(tester, client: client);
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
      expect(
        find.byKey(const Key('eth_send_panel_review_stage')),
        findsOneWidget,
      );
      expect(find.textContaining('From'), findsOneWidget);
      expect(find.textContaining('Destination'), findsOneWidget);
      expect(find.textContaining('0.01 ETH'), findsAtLeastNWidgets(1));
      expect(find.textContaining('Ethereum Sepolia'), findsAtLeastNWidgets(1));
      expect(find.text(kEthSendReviewWarning), findsOneWidget);
    });

    testWidgets('SP8: end-to-end — sign + broadcast with closed-set body',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      String? capturedCiphertext;
      var decryptCallCount = 0;
      await _pumpPanel(
        tester,
        client: client,
        decryptForVault: (ciphertext) async {
          decryptCallCount++;
          capturedCiphertext = ciphertext;
          return _kPlaintextPk;
        },
        verifyPin: (pin) async => pin == '123456',
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
      expect(
        find.byKey(const Key('eth_send_panel_pin_dialog')),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(decryptCallCount, equals(1));
      expect(capturedCiphertext, equals('CT-xyz'));

      expect(client.broadcastCallCount, equals(1));

      expect(client.lastBroadcastBody!.keys.toSet(),
          equals({'asset', 'signedTransaction'}));

      final signed = client.lastBroadcastBody!['signedTransaction'] as String;
      expect(signed.startsWith('0x'), isTrue);
      expect(signed.length, greaterThan(200));
      expect(signed.contains(_kPlaintextPk), isFalse,
          reason: 'plaintext private key MUST NOT leak into the '
              'signed transaction');

      expect(
        find.byKey(const Key('eth_send_panel_submitted_stage')),
        findsOneWidget,
      );
      expect(find.text(kEthSendSuccessHeading), findsOneWidget);
      expect(find.textContaining('0x1234567890abcdef'), findsOneWidget);
    });

    testWidgets('SP7: wrong PIN → no broadcast, no signing', (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      var decryptCallCount = 0;
      await _pumpPanel(
        tester,
        client: client,
        decryptForVault: (ciphertext) async {
          decryptCallCount++;
          return _kPlaintextPk;
        },
        verifyPin: (pin) async => false,
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
        'wrong',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();
      expect(decryptCallCount, equals(0));
      expect(client.broadcastCallCount, equals(0));
      expect(find.text(kEthSendErrorPinWrong), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_review_stage')),
        findsOneWidget,
      );
    });

    testWidgets(
        'SP10: broadcast_unavailable → honest rejection result screen '
        '(2026-07-13 canary correctness)', (tester) async {
      // Pre-canary this test asserted the submitted stage was NOT
      // shown. Post-canary, an explicit backend rejection routes to
      // an HONEST result screen with the rejection heading + reason.
      // The submitted-stage KEY is reused, but the body shows the
      // rejection copy — never a generic success.
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'broadcast_unavailable',
          'reason': 'upstream_timeout',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        verifyPin: (pin) async => true,
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
      // Result screen is shown, but with the REJECTED heading + body
      // (not the submitted body). "Start a new send" is the primary
      // action; there's no fake success and no explorer link.
      expect(
        find.byKey(const Key('eth_send_panel_submitted_stage')),
        findsOneWidget,
      );
      expect(find.text(kEthSendResultHeadingRejected), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_return_form_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('eth_send_panel_explorer_btn')),
        findsNothing,
        reason: 'A rejected transaction MUST NOT offer an explorer link.',
      );
    });

    test('SP11: source guard — no seed / mnemonic / private key input', () {
      final src = File('lib/ui/crypto_wallet_engine_send_panel.dart')
          .readAsStringSync();

      const banned = [
        'seed',
        'mnemonic',
        'recovery',
        'private key',
        'privatekey',
        'wif',
        'xprv'
      ];
      final singleQ = RegExp("labelText:\\s*'([^']+)'");
      final doubleQ = RegExp('labelText:\\s*"([^"]+)"');
      final labels = <String>[
        ...singleQ.allMatches(src).map((m) => m.group(1)!.toLowerCase()),
        ...doubleQ.allMatches(src).map((m) => m.group(1)!.toLowerCase()),
      ];
      expect(labels.isNotEmpty, isTrue,
          reason: 'expected at least one labelText literal in '
              'the send panel');
      for (final label in labels) {
        for (final word in banned) {
          expect(
            label.contains(word),
            isFalse,
            reason: 'send panel field labelled "$label" contains '
                'banned word "$word".',
          );
        }
      }
    });

    testWidgets(
        'SP12: failed PIN verification clears in-flight state so a '
        'retry can sign once', (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      var verifyAttempts = 0;
      var decryptCallCount = 0;
      await _pumpPanel(
        tester,
        client: client,
        decryptForVault: (ciphertext) async {
          decryptCallCount++;
          return _kPlaintextPk;
        },
        verifyPin: (pin) async {
          verifyAttempts++;
          if (verifyAttempts == 1) {
            throw StateError('temporary verifier outage');
          }
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

      expect(find.text(kEthSendErrorPinVerificationFailed), findsOneWidget);
      expect(client.encryptedSecretCallCount, equals(0));
      expect(decryptCallCount, equals(0));
      expect(client.broadcastCallCount, equals(0));

      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(verifyAttempts, equals(2));
      expect(decryptCallCount, equals(1));
      expect(client.broadcastCallCount, equals(1));
      expect(
        find.byKey(const Key('eth_send_panel_submitted_stage')),
        findsOneWidget,
      );
    });

    testWidgets(
        'SP13: mainnet balance unavailable blocks before draft, PIN, '
        'secret, and broadcast', (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        network: kEvmNetworkEthereumMainnet,
        mainnetSendEnabled: true,
        mainnetSendPaused: false,
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

      expect(find.text(kMainnetSendBalanceUnverifiedError), findsOneWidget);
      expect(
        find.byKey(const Key('eth_send_panel_review_stage')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('eth_send_panel_pin_dialog')),
        findsNothing,
      );
      expect(client.draftCallCount, equals(0));
      expect(client.encryptedSecretCallCount, equals(0));
      expect(client.broadcastCallCount, equals(0));
    });

    testWidgets('SP14: available balance is visible and refreshable',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      var balanceCalls = 0;
      await _pumpPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async {
          balanceCalls++;
          return balanceCalls == 1 ? 0.038064000767729 : 0.04;
        },
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Available balance: 0.038064000767729 ETH'),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(const Key('eth_send_panel_available_balance_refresh_btn')),
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Available balance: 0.04 ETH'),
        findsOneWidget,
      );
    });

    testWidgets('SP15: review renders explicit balance and fee quote rows',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 0.02,
        fetchAvailableBalanceWei: () async => BigInt.parse('20000000000000000'),
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

      expect(find.textContaining('Available'), findsAtLeastNWidgets(1));
      expect(find.text('Unavailable'), findsOneWidget,
          reason: 'Unsupported pending balance must be labeled unavailable.');
      expect(find.textContaining('Spendable'), findsOneWidget);
      expect(find.textContaining('Estimated fee'), findsOneWidget);
      expect(find.textContaining('Maximum debit'), findsOneWidget);
      expect(find.textContaining('Remaining'), findsOneWidget);
    });

    testWidgets(
        'SP15b: mainnet review trusts verified raw balance in draft response',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: {
          ..._draftReady(chainId: 1),
          'network': 'Ethereum Mainnet',
          'blockNumber': 19000000,
          'confirmedBalanceWei': '20000000000000000',
          'spendableBalanceWei': '20000000000000000',
          'pendingBalanceWei': null,
          'estimatedFeeWei': '420000000000000',
          'maximumFeeWei': '420000000000000',
          'totalMaximumDebitWei': '10420000000000000',
          'remainingBalanceWei': '9580000000000000',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        network: kEvmNetworkEthereumMainnet,
        mainnetSendEnabled: true,
        mainnetSendPaused: false,
        fetchAvailableBalance: () async => 0.02,
        fetchAvailableBalanceWei: null,
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

      expect(find.textContaining('Review send'), findsOneWidget);
      expect(find.textContaining('Available'), findsAtLeastNWidgets(1));
      expect(find.textContaining('Spendable'), findsOneWidget);
      expect(find.textContaining('Estimated fee'), findsOneWidget);
      expect(find.textContaining('Maximum debit'), findsOneWidget);
      expect(find.textContaining('Remaining'), findsOneWidget);
    });

    testWidgets('SP16: expired quote blocks after PIN and before secret fetch',
        (tester) async {
      var now = DateTime.utc(2026, 7, 30, 12);
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 0.02,
        fetchAvailableBalanceWei: () async => BigInt.parse('20000000000000000'),
        verifyPin: (_) async => true,
        clock: () => now,
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
      now = now.add(kWalletSendQuoteTtl).add(const Duration(seconds: 1));
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        '123456',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();

      expect(find.text(kMainnetSendFeeQuoteExpiredError), findsOneWidget);
      expect(client.encryptedSecretCallCount, equals(0));
      expect(client.broadcastCallCount, equals(0));
    });

    testWidgets(
        'SP17: mainnet gas-price spike requires a fresh review before signing',
        (tester) async {
      final client = _FakeSendClient(
        draftResponse: _draftReady(chainId: 1),
        feeEstimateResponse: const {
          'status': 'fee_estimate_ready',
          'network': kEvmNetworkEthereumMainnet,
          'asset': 'ETH',
          'authorizedMaxFeeBaseUnits': '630000000000000',
          'gasLimit': '21000',
          'gasPriceWei': '30000000000',
          'chainId': 1,
          'feeSource': 'eth_estimateGas_x_gasPrice',
        },
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
      );
      await _pumpPanel(
        tester,
        client: client,
        network: kEvmNetworkEthereumMainnet,
        mainnetSendEnabled: true,
        mainnetSendPaused: false,
        fetchAvailableBalance: () async => 0.02,
        fetchAvailableBalanceWei: () async => BigInt.parse('20000000000000000'),
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

      expect(client.feeEstimateCallCount, equals(1));
      expect(find.text(kMainnetSendFeeQuoteChangedError), findsOneWidget);
      expect(client.encryptedSecretCallCount, equals(0));
      expect(client.broadcastCallCount, equals(0));
    });

    testWidgets('SP18: duplicate PIN confirm produces one broadcast attempt',
        (tester) async {
      final completer = Completer<Map<String, dynamic>>();
      final client = _FakeSendClient(
        draftResponse: _draftReady(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
        },
        broadcastCompleter: completer,
      );
      await _pumpPanel(
        tester,
        client: client,
        fetchAvailableBalance: () async => 0.02,
        fetchAvailableBalanceWei: () async => BigInt.parse('20000000000000000'),
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
      final pinConfirm = find.byKey(const Key('eth_send_panel_pin_confirm'));
      await tester.tap(pinConfirm);
      await tester.tap(pinConfirm, warnIfMissed: false);
      await tester.pump();

      expect(client.broadcastCallCount, equals(1));
      completer.complete(const {
        'status': 'submitted',
        'txHash':
            '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
      });
      await tester.pumpAndSettle();
      expect(client.broadcastCallCount, equals(1));
    });

    test('SP19: source guard - review confirm is readiness-gated', () {
      final src = File('lib/ui/crypto_wallet_engine_send_panel.dart')
          .readAsStringSync();
      expect(
        src,
        contains('onPressed: _canConfirmReview ? _onReviewConfirmTap : null'),
      );
      expect(
        src,
        isNot(contains('text: kMainnetSendBalanceUnverifiedWarning')),
        reason: 'Review must not render the deprecated non-blocking '
            'balance warning copy.',
      );
    });
  });
}
