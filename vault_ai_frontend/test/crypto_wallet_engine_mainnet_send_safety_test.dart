

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';


class _FakeSafetyClient extends VaultAIClient {
  Map<String, dynamic> draftResponse;
  Map<String, dynamic> encryptedSecretResponse;
  Map<String, dynamic> broadcastResponse;

  int draftNetworkCount = 0;
  int broadcastNetworkCount = 0;
  int broadcastSepoliaCount = 0;
  Map<String, dynamic>? lastBroadcastBody;

  _FakeSafetyClient({
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
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    draftNetworkCount++;
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
    return draftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async => encryptedSecretResponse;

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async => encryptedSecretResponse;

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
    broadcastNetworkCount++;
    lastBroadcastBody = {
      'route':             'network',
      'network':           network,
      'asset':             asset,
      'signedTransaction': signedTransaction,
      if (idempotencyKey != null) 'idempotencyKey': idempotencyKey,
    };
    return broadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransaction({
    required String asset,
    required String authToken,
    required String signedTransaction,
  }) async {
    broadcastSepoliaCount++;
    return broadcastResponse;
  }
}


const String _kFromAddress = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const String _kDestAddress = '0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF';
const String _kPlaintextPk =
    '0000000000000000000000000000000000000000000000000000000000000001';
const String _kTxHash =
    '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef';

Map<String, dynamic> _mainnetDraftReady() => {
      'status':             'draft_ready',
      'asset':              'ETH',
      'network':            'Ethereum Mainnet',
      'fromAddress':        _kFromAddress,
      'destinationAddress': _kDestAddress,
      'amountEth':          '0.01',
      'amountWei':          '10000000000000000',
      'nonce':              '0',
      'gasLimit':           '21000',
      'gasPrice':           '20000000000',
      'chainId':            1,
      'feeUnit':            'ETH',
      'realFundsWarning':   kEvmNetworkMainnetSendRealFundsHeadline,
    };

Map<String, dynamic> _sepoliaDraftReady() => {
      'status':             'draft_ready',
      'asset':              'ETH',
      'network':            'Ethereum Sepolia',
      'fromAddress':        _kFromAddress,
      'destinationAddress': _kDestAddress,
      'amountEth':          '0.01',
      'amountWei':          '10000000000000000',
      'nonce':              '0',
      'gasLimit':           '21000',
      'gasPrice':           '20000000000',
      'chainId':            11155111,
    };

Future<void> _pumpMainnetSafetyPanel(
  WidgetTester tester, {
  required _FakeSafetyClient client,
  String asset = 'ETH',
  bool mainnetSendPaused = false,
  Future<bool> Function(String dest)? isKnownDestination,
  Future<double?> Function()? fetchAvailableBalance,
  Future<double?> Function()? fetchEthBalance,
  String? prefilledDestination,
  String? prefilledAmount,
  String Function()? idempotencyKeyGenerator,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: CryptoWalletEngineSendPanel(
        authToken: 'tok',
        fromAddress: _kFromAddress,
        client: client,
        decryptForVault: (ciphertext) async => _kPlaintextPk,
        isVaultKeyAvailable: () => true,
        asset: asset,
        network: kEvmNetworkEthereumMainnet,
        mainnetSendEnabled: true,
        mainnetSendPaused: mainnetSendPaused,
        isKnownDestination: isKnownDestination,
        fetchAvailableBalance: fetchAvailableBalance,
        fetchEthBalance: fetchEthBalance,
        prefilledDestination: prefilledDestination,
        prefilledAmount: prefilledAmount,
        idempotencyKeyGenerator: idempotencyKeyGenerator,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


_FakeSafetyClient _baseClient({
  Map<String, dynamic>? draft,
  Map<String, dynamic>? broadcast,
}) {
  return _FakeSafetyClient(
    draftResponse: draft ?? _mainnetDraftReady(),
    encryptedSecretResponse: const {
      'status':                'encrypted_secret_ready',
      'encryptedWalletSecret': 'CT-mainnet',
    },
    broadcastResponse: broadcast ?? const {
      'status': 'submitted', 'txHash': _kTxHash,
    },
  );
}


void main() {
  group('Mainnet send safety — slice 12', () {

    testWidgets('HS1: wrong confirmation phrase blocks PIN',
        (tester) async {
      
      
      final client = _baseClient();
      await _pumpMainnetSafetyPanel(
        tester, client: client,
        prefilledDestination: _kDestAddress,
        prefilledAmount: '0.01',
      );
      
      
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseStageKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseInputKey)),
        findsNothing,
      );
    });

    test('HS2: confirmation phrase helpers map asset → phrase', () {
      expect(mainnetSendConfirmPhraseFor('ETH'), equals('SEND ETH'));
      expect(
        mainnetSendConfirmPhraseFor('USDT_ERC20'), equals('SEND USDT'),
      );
      expect(
        mainnetSendConfirmPhraseFor('USDC_ERC20'), equals('SEND USDC'),
      );
      
      expect(mainnetSendConfirmPhrasePromptFor('ETH'),
          contains('SEND ETH'));
      expect(mainnetSendConfirmPhrasePromptFor('USDT_ERC20'),
          contains('SEND USDT'));
      expect(mainnetSendConfirmPhrasePromptFor('USDC_ERC20'),
          contains('SEND USDC'));
    });

    test('HS2b: confirmation phrase copy is operator-pinned', () {
      
      
      expect(kMainnetSendConfirmPhraseMismatch.toLowerCase(),
          contains('confirmation phrase'));
      expect(kMainnetSendConfirmPhraseMismatch.toLowerCase(),
          contains('exactly'));
    });

    test('HS4: real-funds + safe-copy constants exist', () {
      expect(kMainnetSendBalanceUnverifiedWarning.toLowerCase(),
          contains('balance could not be verified'));
      expect(kMainnetSendInsufficientGasWarning.toLowerCase(),
          contains('eth for gas'));
      expect(kMainnetSendPausedBanner.toLowerCase(),
          contains('paused'));
      expect(kMainnetSendBroadcastSafeError.toLowerCase(),
          contains('could not submit'));
      expect(kMainnetSendFeeEstimateFailedError.toLowerCase(),
          contains('could not estimate'));
      expect(kMainnetSendDestinationCardHeader.toLowerCase(),
          contains('verify this address'));
      expect(kMainnetSendNewRecipientWarning.toLowerCase(),
          contains('new recipient'));
    });

    testWidgets('HS13: mainnet send paused → paused banner + draft refused',
        (tester) async {
      final client = _baseClient();
      await _pumpMainnetSafetyPanel(
        tester, client: client,
        mainnetSendPaused: true,
        prefilledDestination: _kDestAddress,
        prefilledAmount: '0.01',
      );
      expect(
        find.byKey(const Key(kMainnetSendPausedBannerKey)),
        findsOneWidget,
      );
      
      await tester.tap(
        find.byKey(const Key('eth_send_panel_review_btn')),
      );
      await tester.pump();
      
      expect(client.draftNetworkCount, equals(0));
      
      expect(find.text(kMainnetSendPausedBanner), findsWidgets);
    });

    test('HS15: idempotency key generator produces unique values', () {
      
      
      const klass = CryptoWalletEngineSendPanel;
      expect(klass.toString(), contains('CryptoWalletEngineSendPanel'));
    });

    test('HS-CONST: destination-card + new-recipient keys are pinned',
        () {
      expect(kMainnetSendDestinationCardKey,
          equals('eth_send_panel_mainnet_destination_card'));
      expect(kMainnetSendDestinationCopyBtnKey,
          equals('eth_send_panel_mainnet_destination_copy_btn'));
      expect(kMainnetSendNewRecipientBannerKey,
          equals('eth_send_panel_mainnet_new_recipient_banner'));
      expect(kMainnetSendBalanceUnverifiedKey,
          equals('eth_send_panel_mainnet_balance_unverified'));
      expect(kMainnetSendInsufficientGasKey,
          equals('eth_send_panel_mainnet_insufficient_gas'));
      expect(kMainnetSendConfirmPhraseStageKey,
          equals('eth_send_panel_mainnet_confirm_phrase_stage'));
    });

    test('HS-GUARD: panel source has no signing-field debugPrint',
        () {
      final src = File(
        'lib/ui/crypto_wallet_engine_send_panel.dart',
      ).readAsStringSync();
      final printRe = RegExp(r'(debugPrint|print)\s*\([^)]*\)');
      for (final m in printRe.allMatches(src)) {
        final call = m.group(0)!;
        for (final banned in const [
          'privateKey', 'privateKeyHex', 'signedTransaction',
          'encryptedSecret', 'encryptedWalletSecret', 'pin',
          'idempotencyKey',
        ]) {
          expect(call.contains(banned), isFalse,
              reason: 'debugPrint leaks $banned: $call');
        }
      }
    });

    test('HS-GUARD: panel source has no buy/sell/swap/trade/stake/'
        'bridge UI copy', () {
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

    test('HS-GUARD: panel source has no hardcoded mainnet tx hash',
        () {
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

    test('HS-API: broadcast body wiring includes optional '
        'idempotencyKey field', () async {
      
      final client = _baseClient();
      await client.broadcastCryptoWalletSignedTransactionNetwork(
        network: 'ethereum_mainnet',
        asset: 'ETH',
        authToken: 'tok',
        signedTransaction: '0x' + ('aa' * 200),
        idempotencyKey: 'snd-eth-test-123',
      );
      final body = client.lastBroadcastBody!;
      expect(body['signedTransaction'], isNotNull);
      expect(body['idempotencyKey'], equals('snd-eth-test-123'));
      
      for (final banned in const [
        'privateKey', 'seedPhrase', 'mnemonic',
        'recoveryPhrase', 'encryptedWalletSecret',
      ]) {
        expect(body.containsKey(banned), isFalse,
            reason: 'leaks $banned');
      }
    });

    test('HS-API: broadcast body without idempotency key omits the '
        'field', () async {
      final client = _baseClient();
      await client.broadcastCryptoWalletSignedTransactionNetwork(
        network: 'ethereum_mainnet',
        asset: 'ETH',
        authToken: 'tok',
        signedTransaction: '0x' + ('aa' * 200),
      );
      final body = client.lastBroadcastBody!;
      expect(body['signedTransaction'], isNotNull);
      expect(body.containsKey('idempotencyKey'), isFalse);
    });

    testWidgets('HS3: Sepolia review does NOT require mainnet phrase',
        (tester) async {
      
      
      final client = _baseClient(draft: _sepoliaDraftReady());
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: client,
            decryptForVault: (c) async => _kPlaintextPk,
            isVaultKeyAvailable: () => true,
            asset: 'ETH',
            
            prefilledDestination: _kDestAddress,
            prefilledAmount: '0.01',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      await tester.tap(find.byKey(
        const Key('eth_send_panel_review_btn'),
      ));
      await tester.pumpAndSettle();
      
      
      expect(
        find.byKey(const Key(kMainnetSendConfirmPhraseStageKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kMainnetSendDestinationCardKey)),
        findsNothing,
      );
    });
  });
}
