

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/tron_transaction.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';


const String _kFromAddr = 'TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq';
const String _kDestAddr = 'TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9';
const String _kValidTxId =
    '0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20';


class _SendSpyClient extends VaultAIClient {
  Map<String, dynamic> nextDraftResponse = {};
  Map<String, dynamic> nextSecretResponse = {
    'wallet_engine':         'encrypted_secret_ready',
    'encryptedWalletSecret': 'ct-tron-secret',
  };
  Map<String, dynamic> nextBroadcastResponse = {
    'status': 'submitted',
    'txHash': _kValidTxId,
  };
  List<Object> broadcastCalls = [];
  Map<String, dynamic>? capturedBroadcastPayload;
  final List<String> statusCalls = [];
  List<String> nextStatuses = ['pending', 'confirmed'];
  int _statusIdx = 0;

  _SendSpyClient() : super(baseUrl: 'http://localhost:0');

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
    return {
      ...nextDraftResponse,
      'destinationAddress': destinationAddress,
      'amountUsdt':          amountUsdt ?? '',
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    return nextSecretResponse;
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
    capturedBroadcastPayload = {
      'signedTransaction': signedTransaction,
      'idempotencyKey':    idempotencyKey,
    };
    broadcastCalls.add(signedTransaction);
    return nextBroadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletTransactionStatusNetwork({
    required String network,
    required String asset,
    required String txHash,
    required String authToken,
  }) async {
    statusCalls.add(txHash);
    if (_statusIdx >= nextStatuses.length) {
      _statusIdx = nextStatuses.length - 1;
    }
    final s = nextStatuses[_statusIdx++];
    return {'transactionStatus': s};
  }
}


CryptoWalletFeatures _features({
  bool tronOn = true,
  bool sendOn = true,
  bool sendPaused = false,
}) {
  return CryptoWalletFeatures.fromBackend({
    'walletEngineEnabled':       true,
    'sepoliaReceiveEnabled':     true,
    'sepoliaSendEnabled':        true,
    'mainnetReceiveEnabled':     false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':        false,
    'mainnetSendPaused':         false,
    'defaultNetwork':            'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'solanaEnabled':             false,
    'solanaReceiveEnabled':      false,
    'solanaBalanceEnabled':      false,
    'solanaSendEnabled':         false,
    'solanaSendPaused':          false,
    'solanaActivityConnected':   false,
    'solanaStatusReady':         false,
    'solanaFeeReady':            false,
    'tronEnabled':               tronOn,
    'tronReceiveEnabled':        tronOn,
    'tronBalanceEnabled':        tronOn,
    'tronSendEnabled':           tronOn && sendOn && !sendPaused,
    'tronSendPaused':            tronOn && sendPaused,
    'tronActivityConnected':     false,
    'tronUsdtContractConfigured': tronOn,
    'supportedNetworks': const [
      'ethereum_sepolia', 'ethereum_mainnet', 'tron_mainnet',
    ],
    'supportedAssetsByNetwork': const {
      'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'tron_mainnet':     ['USDT_TRC20'],
    },
  });
}


Map<String, dynamic> _draftReady({String amount = '5.5'}) {
  return {
    'status':              'draft_ready',
    'wallet_engine':       'draft_ready',
    'asset':               'USDT_TRC20',
    'network':             'tron_mainnet',
    'networkLabel':        'TRON',
    'tokenStandard':       'TRC20',
    'fromAddress':         _kFromAddr,
    'destinationAddress':  _kDestAddr,
    'amountUsdt':          amount,
    'amountBaseUnits':     '5500000',
    'unsignedTransaction': {
      'txID':         _kValidTxId,
      'raw_data':     {'contract': []},
      'raw_data_hex': '0a0b0c0d',
    },
    'txID':                _kValidTxId,
    'rawDataHex':          '0a0b0c0d',
    'feeLimitSun':         100000000,
    'feeLimitTrx':         '100',
    'feeStatus':           'estimated',
    'trxBalanceSun':       200000000,
    'trxBalance':          '200',
    'resourceStatus':      'ready',
    'feeWarning':          'USDT TRC20 transfers require TRX for TRON '
                            'network fees.',
    'warning':             'Review carefully. TRON transactions '
                            'cannot be reversed.',
  };
}


Map<String, dynamic> _draftLowTrx() {
  final base = _draftReady();
  base['resourceStatus'] = 'low_trx';
  base['trxBalanceSun'] = 500;
  base['trxBalance'] = '0.0005';
  return base;
}


String _secretJson(String pkHex) => jsonEncode({
      'schema':        'tron_secret_v1',
      'keyOrigin':     'generated_client_side',
      'privateKeyHex': pkHex,
    });





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('TronTransactionSigning', () {
    test('signTronTxIDHex yields 130 hex chars', () {
      final wallet = generateTronWallet();
      final sig = signTronTxIDHex(
        txIDHex: _kValidTxId,
        privateKeyHex: wallet.privateKeyHex,
      );
      expect(sig.length, 130);
      expect(RegExp(r'^[0-9a-f]{130}$').hasMatch(sig), isTrue);
    });

    test('signature deterministic for same inputs', () {
      final wallet = generateTronWallet();
      final a = signTronTxIDHex(
        txIDHex: _kValidTxId,
        privateKeyHex: wallet.privateKeyHex,
      );
      final b = signTronTxIDHex(
        txIDHex: _kValidTxId,
        privateKeyHex: wallet.privateKeyHex,
      );
      expect(a, equals(b));
    });

    test('signTronTxIDHex rejects malformed txID', () {
      final wallet = generateTronWallet();
      expect(
        () => signTronTxIDHex(
          txIDHex: 'shorttxid',
          privateKeyHex: wallet.privateKeyHex,
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('attachTronSignatureToUnsigned includes signature array', () {
      final wallet = generateTronWallet();
      final sig = signTronTxIDHex(
        txIDHex: _kValidTxId,
        privateKeyHex: wallet.privateKeyHex,
      );
      final unsigned = <String, dynamic>{
        'txID':         _kValidTxId,
        'raw_data':     const {'contract': []},
        'raw_data_hex': '0a0b0c0d',
      };
      final signed = attachTronSignatureToUnsigned(
        unsignedTransaction: unsigned,
        signatureHex: sig,
      );
      expect(signed['signature'], isA<List>());
      expect((signed['signature'] as List).length, 1);
      expect(signed['txID'], _kValidTxId);
      expect(signed['raw_data_hex'], '0a0b0c0d');
    });

    test('parseUsdtAmountToBaseUnits enforces 6 decimals max', () {
      expect(parseUsdtAmountToBaseUnits('5'), 5000000);
      expect(parseUsdtAmountToBaseUnits('5.5'), 5500000);
      expect(parseUsdtAmountToBaseUnits('0.000001'), 1);
      expect(
        () => parseUsdtAmountToBaseUnits('1.1234567'),
        throwsA(isA<ArgumentError>()),
      );
      expect(
        () => parseUsdtAmountToBaseUnits('0'),
        throwsA(isA<ArgumentError>()),
      );
      expect(
        () => parseUsdtAmountToBaseUnits('-1'),
        throwsA(isA<ArgumentError>()),
      );
    });
  });


  group('TronSendFeaturesFlags', () {
    test('send disabled when backend says false', () {
      final f = _features(tronOn: true, sendOn: false);
      expect(f.tronSendEnabled, isFalse);
    });

    test('send enabled when backend says true', () {
      final f = _features(tronOn: true, sendOn: true);
      expect(f.tronSendEnabled, isTrue);
      expect(f.tronSendPaused, isFalse);
    });

    test('send paused reflected in flags', () {
      final f = _features(
        tronOn: true, sendOn: true, sendPaused: true,
      );
      expect(f.tronSendEnabled, isFalse);
      expect(f.tronSendPaused, isTrue);
    });
  });


  group('TronSendPanelStates', () {
    testWidgets(
      'disabled banner when send flag false',
      (t) async {
        final client = _SendSpyClient();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(sendOn: false),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kTronSendDisabledBannerKey)),
          findsOneWidget,
        );
        expect(client.broadcastCalls, isEmpty);
      },
    );

    testWidgets(
      'paused banner when send paused',
      (t) async {
        final client = _SendSpyClient();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(sendPaused: true),
            ),
          ),
        ));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kTronSendPausedBannerKey)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'input rejects invalid TRON address',
      (t) async {
        final client = _SendSpyClient();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          '0x' + 'a' * 40,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        expect(
          find.text(kTronSendInvalidDestinationCopy),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'input rejects more than 6 decimals',
      (t) async {
        final client = _SendSpyClient();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '1.1234567',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        expect(
          find.text(kTronSendInvalidAmountCopy),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'review shows amount / from / to / warning / fee warning',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftReady();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5.5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kTronSendReviewCardKey)),
          findsOneWidget,
        );
        expect(find.text('USDT TRC20'), findsOneWidget);
        expect(find.text('TRON'), findsOneWidget);
        expect(find.text('5.5 USDT'), findsOneWidget);
        expect(
          find.byKey(const Key(kTronSendWarningKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kTronSendFeeWarningKey)),
          findsOneWidget,
        );
        expect(find.textContaining('TRX'), findsWidgets);
      },
    );

    testWidgets(
      'low TRX warning renders when resourceStatus=low_trx',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftLowTrx();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async => '',
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key(kTronSendLowTrxWarningKey)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'wrong PIN blocks signing and broadcast',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftReady();
        final wallet = generateTronWallet();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async =>
                  _secretJson(wallet.privateKeyHex),
              isVaultKeyAvailable: () => true,
              verifyPin: (pin) async => false,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key(kTronSendConfirmButtonKey)));
        await t.pump();
        expect(find.byKey(const Key('tron_send_pin_dialog')),
            findsOneWidget);
        await t.enterText(
          find.byKey(const Key(kTronSendPinInputKey)),
          '9999',
        );
        await t.tap(find.byKey(const Key(kTronSendPinConfirmBtnKey)));
        await t.pumpAndSettle();
        expect(client.capturedBroadcastPayload, isNull);
        expect(client.broadcastCalls, isEmpty);
      },
    );

    testWidgets(
      'successful send signs locally, sends signedTransaction only',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftReady();
        final wallet = generateTronWallet();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async =>
                  _secretJson(wallet.privateKeyHex),
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key(kTronSendConfirmButtonKey)));
        await t.pumpAndSettle();

        expect(client.capturedBroadcastPayload, isNotNull);
        final payload = client.capturedBroadcastPayload!;
        expect(payload['idempotencyKey'], isA<String>());
        expect((payload['idempotencyKey'] as String).length,
            greaterThanOrEqualTo(8));

        final signed = payload['signedTransaction'];
        expect(signed, isA<Map<String, dynamic>>());
        final signedMap = signed as Map<String, dynamic>;
        expect(signedMap['txID'], _kValidTxId);
        expect(signedMap['raw_data_hex'], '0a0b0c0d');
        expect(signedMap['signature'], isA<List>());
        expect((signedMap['signature'] as List).length, 1);
        final sigHex = (signedMap['signature'] as List)[0] as String;
        expect(sigHex.length, 130);

        final serialised = jsonEncode(payload);
        for (final banned in const [
          'privateKey', 'tronPrivateKey', 'encryptedWalletSecret',
          'seed', 'mnemonic', 'recoveryPhrase', 'seedPhrase', 'wif',
          'xprv',
        ]) {
          expect(serialised.contains(banned), isFalse,
              reason: 'payload leaked $banned');
        }
        expect(serialised.contains(wallet.privateKeyHex), isFalse,
            reason: 'payload leaked plaintext private key');

        expect(find.byKey(const Key(kTronSendSubmittedCardKey)),
            findsOneWidget);
        expect(find.text(_kValidTxId), findsOneWidget);
      },
    );

    testWidgets(
      'submitted screen never renders fake confirmed until poll returns confirmed',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftReady()
          ..nextStatuses = ['pending'];
        final wallet = generateTronWallet();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async =>
                  _secretJson(wallet.privateKeyHex),
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key(kTronSendConfirmButtonKey)));
        await t.pumpAndSettle();
        expect(find.byKey(const Key(kTronSendStatusTextKey)),
            findsOneWidget);
        expect(find.text(kTronSendStatusConfirmedCopy),
            findsNothing);
      },
    );

    testWidgets(
      'confirm tap only broadcasts once even if pressed rapidly',
      (t) async {
        final client = _SendSpyClient()
          ..nextDraftResponse = _draftReady();
        final wallet = generateTronWallet();
        await t.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoWalletEngineTronSendPanel(
              authToken: 'tok',
              fromAddress: _kFromAddr,
              client: client,
              decryptForVault: (_) async =>
                  _secretJson(wallet.privateKeyHex),
              isVaultKeyAvailable: () => true,
              features: _features(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.enterText(
          find.byKey(const Key(kTronSendDestinationInputKey)),
          _kDestAddr,
        );
        await t.enterText(
          find.byKey(const Key(kTronSendAmountInputKey)),
          '5',
        );
        await t.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key(kTronSendConfirmButtonKey)));
        await t.pumpAndSettle();
        expect(client.broadcastCalls.length, 1);
      },
    );
  });


  group('TronSendCopyIntegrity', () {
    test(
      'copy never mentions buy/sell/swap/trade/stake/bridge or eth/sol',
      () {
        for (final s in const [
          kTronSendPanelTitle,
          kTronSendReviewHeading,
          kTronSendConfirmationWarning,
          kTronSendFeeWarning,
          kTronSendLowTrxWarning,
          kTronSendNotEnabledMessage,
          kTronSendPausedMessage,
          kTronSendPinDialogTitle,
          kTronSendPinDialogBody,
          kTronSendSubmittedHeading,
          kTronSendSubmittedBody,
          kTronSendDestinationLabel,
          kTronSendAmountLabel,
        ]) {
          final low = s.toLowerCase();
          for (final w in const [
            'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
            'market', 'profit', 'loss', 'exchange',
          ]) {
            expect(low.contains(w), isFalse,
                reason: 'copy "$s" leaked "$w"');
          }
          expect(low.contains('ethereum'), isFalse,
              reason: 'copy "$s" leaked ethereum');
          expect(low.contains('solana'), isFalse,
              reason: 'copy "$s" leaked solana');
          expect(low.contains('sepolia'), isFalse,
              reason: 'copy "$s" leaked sepolia');
          expect(low.contains('erc20'), isFalse,
              reason: 'copy "$s" leaked erc20');
        }
      },
    );
  });
}
