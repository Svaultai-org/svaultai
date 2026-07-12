

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/solana_transaction.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';


class _SolanaSendSpyClient extends VaultAIClient {
  Map<String, dynamic> nextDraftResponse = {};
  Map<String, dynamic> nextSecretResponse = {
    'wallet_engine':         'encrypted_secret_ready',
    'encryptedWalletSecret': 'ct-solana-secret',
  };
  Map<String, dynamic> nextBroadcastResponse = {
    'status':    'submitted',
    'signature': 'sig-real-1234',
  };
  final List<Map<String, dynamic>> draftBodies = [];
  final List<Map<String, dynamic>> broadcastBodies = [];
  int secretCalls = 0;
  int broadcastCalls = 0;

  _SolanaSendSpyClient() : super(baseUrl: 'http://localhost:0');

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
    draftBodies.add({
      'network':            network,
      'asset':              asset,
      'fromAddress':        fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth':          amountEth,
      'amountSol':          amountSol,
      'amountUsdt':         amountUsdt,
    });
    return nextDraftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    secretCalls++;
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
    broadcastCalls++;
    broadcastBodies.add({
      'network':           network,
      'asset':             asset,
      'signedTransaction': signedTransaction,
      'idempotencyKey':    idempotencyKey,
    });
    return nextBroadcastResponse;
  }
}


CryptoWalletFeatures _features({
  bool solanaOn = true,
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
    'solanaEnabled':             solanaOn,
    'solanaReceiveEnabled':      solanaOn,
    'solanaBalanceEnabled':      solanaOn,
    'solanaSendEnabled':         sendOn,
    'solanaSendPaused':          sendPaused,
    'solanaActivityConnected':   false,
    'supportedNetworks': const [
      'ethereum_sepolia', 'ethereum_mainnet', 'solana_mainnet',
    ],
    'supportedAssetsByNetwork': const {
      'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'solana_mainnet':   ['SOL'],
    },
  });
}


const String _kAddrA =
    'So11111111111111111111111111111111111111112';
const String _kAddrB = '11111111111111111111111111111111';
const String _kBlockhash =
    'FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE';


Future<void> _pump(
  WidgetTester tester, {
  required _SolanaSendSpyClient client,
  required CryptoWalletFeatures features,
  Future<bool> Function(String)? verifyPin,
  String? prefilledDestination,
  String? prefilledAmount,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoWalletEngineSolanaSendPanel(
          authToken: 'test-token',
          fromAddress: _kAddrA,
          client: client,
          decryptForVault: (ct) async => jsonEncode({
            'schema':          'solana_secret_v1',
            'keyOrigin':       'generated_client_side',
            'secretKeyBase58': _fixedTestSecretB58,
          }),
          isVaultKeyAvailable: () => true,
          verifyPin: verifyPin,
          features: features,
          prefilledDestination: prefilledDestination,
          prefilledAmount: prefilledAmount,
          idempotencyKeyGenerator: () => 'sol-fixed-idem',
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


final String _fixedTestSecretB58 = () {
  final bytes = Uint8List(64);
  for (var i = 0; i < 32; i++) bytes[i] = (i + 1) & 0xff;
  return base58Encode(bytes);
}();





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('Solana transaction — compact-u16 + signing shapes', () {
    test('parseSolAmountToLamports handles common inputs', () {
      expect(parseSolAmountToLamports('1'), equals(1000000000));
      expect(parseSolAmountToLamports('0.5'), equals(500000000));
      expect(parseSolAmountToLamports('0.000000001'), equals(1));
    });

    test('parseSolAmountToLamports rejects invalid amounts', () {
      expect(
        () => parseSolAmountToLamports('0'),
        throwsA(isA<SolanaSigningError>()),
      );
      expect(
        () => parseSolAmountToLamports('-1'),
        throwsA(isA<SolanaSigningError>()),
      );
      expect(
        () => parseSolAmountToLamports('abc'),
        throwsA(isA<SolanaSigningError>()),
      );
      expect(
        () => parseSolAmountToLamports('0.1234567890'),
        throwsA(isA<SolanaSigningError>()),
      );
    });

    test('buildSolanaTransferInstructionData is 12 bytes for u64 lamports',
        () {
      final data = buildSolanaTransferInstructionData(1000000000);
      expect(data.length, equals(12));
      expect(data[0], equals(2));
      expect(data[1], equals(0));
      expect(data[2], equals(0));
      expect(data[3], equals(0));
    });

    test('signSolanaTransfer produces a 64-byte signature', () async {
      final seed = Uint8List(32);
      for (var i = 0; i < 32; i++) seed[i] = (i + 1) & 0xff;
      final signed = await signSolanaTransfer(
        fromAddressBase58: _kAddrA,
        destinationAddressBase58: _kAddrB,
        lamports: 500000000,
        recentBlockhashBase58: _kBlockhash,
        ed25519Seed32: seed,
      );
      expect(signed.wireTransaction.bytes.length, greaterThan(64));

      final compactByte = signed.wireTransaction.bytes[0];
      expect(compactByte, equals(1));
      final signatureBytes = signed.wireTransaction.bytes.sublist(1, 65);
      expect(signatureBytes.length, equals(64));
    });

    test('wire transaction is deterministic for same inputs', () async {
      final seed = Uint8List(32);
      for (var i = 0; i < 32; i++) seed[i] = (i + 1) & 0xff;
      final a = await signSolanaTransfer(
        fromAddressBase58: _kAddrA,
        destinationAddressBase58: _kAddrB,
        lamports: 500000000,
        recentBlockhashBase58: _kBlockhash,
        ed25519Seed32: seed,
      );
      final b = await signSolanaTransfer(
        fromAddressBase58: _kAddrA,
        destinationAddressBase58: _kAddrB,
        lamports: 500000000,
        recentBlockhashBase58: _kBlockhash,
        ed25519Seed32: seed,
      );
      expect(
        a.wireTransaction.base64,
        equals(b.wireTransaction.base64),
      );
    });
  });

  group('Solana send panel — disabled and paused', () {
    testWidgets('disabled banner when solanaSendEnabled is false',
        (tester) async {
      final client = _SolanaSendSpyClient();
      await _pump(
        tester,
        client: client,
        features: _features(sendOn: false),
      );
      expect(
        find.byKey(const Key(kSolanaSendDisabledBannerKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kSolanaSendReviewButtonKey)),
        findsNothing,
      );
    });

    testWidgets('paused banner when solanaSendPaused is true',
        (tester) async {
      final client = _SolanaSendSpyClient();
      await _pump(
        tester,
        client: client,
        features: _features(sendPaused: true),
      );
      expect(
        find.byKey(const Key(kSolanaSendPausedBannerKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kSolanaSendReviewButtonKey)),
        findsNothing,
      );
    });
  });

  group('Solana send panel — input validation', () {
    testWidgets('invalid destination is rejected before draft call',
        (tester) async {
      final client = _SolanaSendSpyClient();
      await _pump(
        tester, client: client, features: _features(),
      );
      await tester.enterText(
        find.byKey(const Key(kSolanaSendDestinationInputKey)),
        'not-a-solana-address',
      );
      await tester.enterText(
        find.byKey(const Key(kSolanaSendAmountInputKey)),
        '0.1',
      );
      await tester.tap(
        find.byKey(const Key(kSolanaSendReviewButtonKey)),
      );
      await tester.pumpAndSettle();
      expect(client.draftBodies, isEmpty);
      expect(
        find.text(kSolanaSendInvalidDestinationCopy),
        findsOneWidget,
      );
    });

    testWidgets('self-send is rejected before draft call',
        (tester) async {
      final client = _SolanaSendSpyClient();
      await _pump(
        tester, client: client, features: _features(),
      );
      await tester.enterText(
        find.byKey(const Key(kSolanaSendDestinationInputKey)),
        _kAddrA,
      );
      await tester.enterText(
        find.byKey(const Key(kSolanaSendAmountInputKey)),
        '0.1',
      );
      await tester.tap(
        find.byKey(const Key(kSolanaSendReviewButtonKey)),
      );
      await tester.pumpAndSettle();
      expect(client.draftBodies, isEmpty);
      expect(find.text(kSolanaSendSelfSendCopy), findsOneWidget);
    });
  });

  group('Solana send panel — review + broadcast flow', () {
    testWidgets(
      'happy path draft/review/confirm sends signedTransaction only',
      (tester) async {
        final client = _SolanaSendSpyClient();
        client.nextDraftResponse = {
          'status':             'draft_ready',
          'schema':             'crypto_wallet_send_draft_v1',
          'asset':              'SOL',
          'network':            'solana_mainnet',
          'networkLabel':       'Solana',
          'fromAddress':        _kAddrA,
          'destinationAddress': _kAddrB,
          'amountSol':          '0.5',
          'lamports':           '500000000',
          'recentBlockhash':    _kBlockhash,
          'feeSol':             '0.000005',
          'warning': 'Review carefully. Solana transactions cannot be reversed.',
        };
        await _pump(tester, client: client, features: _features());
        await tester.enterText(
          find.byKey(const Key(kSolanaSendDestinationInputKey)),
          _kAddrB,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendAmountInputKey)),
          '0.5',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        await tester.pumpAndSettle();

        expect(client.draftBodies.length, equals(1));
        expect(client.draftBodies[0]['network'],
            equals('solana_mainnet'));
        expect(client.draftBodies[0]['amountSol'], equals('0.5'));
        expect(client.draftBodies[0]['amountEth'], isNull);

        expect(
          find.byKey(const Key(kSolanaSendReviewCardKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kSolanaSendWarningKey)),
          findsOneWidget,
        );

        await tester.tap(
          find.byKey(const Key(kSolanaSendConfirmButtonKey)),
        );
        await tester.pumpAndSettle();

        expect(client.secretCalls, equals(1));
        expect(client.broadcastCalls, equals(1));
        final body = client.broadcastBodies[0];
        expect(body['network'], equals('solana_mainnet'));
        expect(body['asset'],   equals('SOL'));
        expect(body['idempotencyKey'], equals('sol-fixed-idem'));

        final signedTx = (body['signedTransaction'] as String);
        expect(signedTx, isNotEmpty);
        for (final banned in [
          'privateKey', 'private_key', 'secretKey', 'secret_key',
          'seedPhrase', 'mnemonic', 'recoveryPhrase',
          'encryptedWalletSecret',
        ]) {
          expect(body.keys, isNot(contains(banned)),
              reason: 'Broadcast body must not carry $banned');
        }

        expect(
          find.byKey(const Key(kSolanaSendSubmittedCardKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('solana_send_panel_signature_text')),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'double-tap Confirm broadcasts only once',
      (tester) async {
        final client = _SolanaSendSpyClient();
        client.nextDraftResponse = {
          'status':             'draft_ready',
          'schema':             'crypto_wallet_send_draft_v1',
          'asset':              'SOL',
          'network':            'solana_mainnet',
          'fromAddress':        _kAddrA,
          'destinationAddress': _kAddrB,
          'amountSol':          '0.5',
          'lamports':           '500000000',
          'recentBlockhash':    _kBlockhash,
        };
        await _pump(tester, client: client, features: _features());
        await tester.enterText(
          find.byKey(const Key(kSolanaSendDestinationInputKey)),
          _kAddrB,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendAmountInputKey)),
          '0.5',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        await tester.pumpAndSettle();


        await tester.tap(
          find.byKey(const Key(kSolanaSendConfirmButtonKey)),
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendConfirmButtonKey)),
          warnIfMissed: false,
        );
        await tester.pumpAndSettle();
        expect(client.broadcastCalls, equals(1));
      },
    );

    testWidgets(
      'wrong PIN prevents broadcast',
      (tester) async {
        final client = _SolanaSendSpyClient();
        client.nextDraftResponse = {
          'status':             'draft_ready',
          'schema':             'crypto_wallet_send_draft_v1',
          'asset':              'SOL',
          'network':            'solana_mainnet',
          'fromAddress':        _kAddrA,
          'destinationAddress': _kAddrB,
          'amountSol':          '0.5',
          'lamports':           '500000000',
          'recentBlockhash':    _kBlockhash,
        };
        await _pump(
          tester,
          client: client,
          features: _features(),
          verifyPin: (pin) async => false,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendDestinationInputKey)),
          _kAddrB,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendAmountInputKey)),
          '0.5',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        await tester.pumpAndSettle();

        await tester.tap(
          find.byKey(const Key(kSolanaSendConfirmButtonKey)),
        );
        await tester.pumpAndSettle();

        await tester.enterText(
          find.byKey(const Key(kSolanaSendPinInputKey)),
          '0000',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendPinConfirmBtnKey)),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Cancel'));
        await tester.pumpAndSettle();
        expect(client.broadcastCalls, equals(0));
      },
    );
  });

  group('non-exchange surface', () {
    test('Solana send copy contains no exchange verbs', () {
      final blobs = [
        kSolanaSendPanelTitle,
        kSolanaSendReviewHeading,
        kSolanaSendConfirmationWarning,
        kSolanaSendNotEnabledMessage,
        kSolanaSendPausedMessage,
        kSolanaSendPinDialogTitle,
        kSolanaSendPinDialogBody,
        kSolanaSendSubmittedHeading,
        kSolanaSendSubmittedBody,
        kSolanaSendReviewButtonLabel,
        kSolanaSendConfirmButtonLabel,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap ', 'stake ', 'bridge ',
                              ' buy ', ' sell ', ' trade ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'Solana send copy leaked: $b');
        }
      }
    });
  });
}
