

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';


class _FakeReceiveClient extends VaultAIClient {
  Map<String, dynamic> _receiveResponse;
  String? lastReceiveAsset;
  int receiveCallCount = 0;

  _FakeReceiveClient({required Map<String, dynamic> receiveResponse})
      : _receiveResponse = receiveResponse,
        super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    receiveCallCount++;
    lastReceiveAsset = asset;
    return _receiveResponse;
  }
}

class _FakeTokenSendClient extends VaultAIClient {
  Map<String, dynamic> _draftResponse;
  Map<String, dynamic> _encryptedSecretResponse;
  Map<String, dynamic> _broadcastResponse;

  int draftCallCount = 0;
  int encryptedSecretCallCount = 0;
  int broadcastCallCount = 0;

  String? lastDraftAsset;
  String? lastEncryptedSecretAsset;
  Map<String, dynamic>? lastDraftBody;
  Map<String, dynamic>? lastBroadcastBody;

  _FakeTokenSendClient({
    required Map<String, dynamic> draftResponse,
    required Map<String, dynamic> encryptedSecretResponse,
    required Map<String, dynamic> broadcastResponse,
  })  : _draftResponse = draftResponse,
        _encryptedSecretResponse = encryptedSecretResponse,
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
    lastDraftAsset = asset;
    lastDraftBody = {
      'asset':             asset,
      'fromAddress':       fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth':         amountEth,
    };
    return _draftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async {
    encryptedSecretCallCount++;
    lastEncryptedSecretAsset = asset;
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
      'asset':             asset,
      'signedTransaction': signedTransaction,
    };
    return _broadcastResponse;
  }
}

const String _kFromAddress = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const String _kDestAddress = '0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF';
const String _kTokenContract = '0x' '111111' '1111111111111111111111111111111111';
const String _kPlaintextPk =
    '0000000000000000000000000000000000000000000000000000000000000001';




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('Crypto Wallet Engine slice 4 — ERC20 closed-set catalogs', () {
    test('T1: kAssetsWithLiveReceive is the closed-set ETH+USDT+USDC',
        () {
      expect(
        kAssetsWithLiveReceive,
        equals({'ETH', 'USDT_ERC20', 'USDC_ERC20'}),
      );
    });

    test('T2: kAssetsWithLiveSend is the closed-set ETH+USDT+USDC', () {
      expect(
        kAssetsWithLiveSend,
        equals({'ETH', 'USDT_ERC20', 'USDC_ERC20'}),
      );
    });

    test('T3: kReceivePanelTokenAssets is the closed-set USDT+USDC', () {
      expect(
        kReceivePanelTokenAssets,
        equals({'USDT_ERC20', 'USDC_ERC20'}),
      );
    });
  });

  group('Crypto Wallet Engine slice 4 — token receive panel', () {
    testWidgets(
        'T4: token receive renders create-ETH-first banner when no ETH wallet',
        (tester) async {
      final client = _FakeReceiveClient(receiveResponse: const {
        'wallet_engine':   'create_eth_wallet_first',
        'asset':           'USDT_ERC20',
        'underlyingAsset': 'ETH',
        'message':         'Create ETH wallet first.',
      });
      await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct_$p',
            isVaultKeyAvailable: () => true,
            asset: 'USDT_ERC20',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      expect(client.lastReceiveAsset, equals('USDT_ERC20'));
      
      expect(
        find.byKey(const Key('eth_receive_panel_create_eth_first_state')),
        findsOneWidget,
      );
      expect(
        find.text(kTokenReceiveCreateEthFirstBanner),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('eth_receive_panel_create_btn')),
        findsNothing,
      );
    });

    testWidgets(
        'T5: token receive renders shared-address banner + ETH address + '
        'token warning',
        (tester) async {
      final client = _FakeReceiveClient(receiveResponse: const {
        'wallet_engine':   'receive_ready',
        'asset':           'USDT_ERC20',
        'underlyingAsset': 'ETH',
        'network':         'Ethereum Sepolia',
        'walletLabel':     'VaultAI ETH wallet',
        'publicAddress':   _kFromAddress,
        'unit':            'USDT',
        'warning': 'Only send USDT on Ethereum Sepolia to this address. ...',
      });
      await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct_$p',
            isVaultKeyAvailable: () => true,
            asset: 'USDT_ERC20',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('eth_receive_panel_token_shared_banner')),
        findsOneWidget,
      );
      expect(
        find.text(kTokenReceiveSharedAddressBanner),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('eth_receive_panel_address_text')),
        findsOneWidget,
      );
      expect(find.text(_kFromAddress), findsOneWidget);
      
      expect(
        find.byKey(const Key('eth_receive_panel_qr')),
        findsOneWidget,
      );
      
      
      expect(find.textContaining('USDT'), findsAtLeastNWidgets(1));
    });
  });

  group('Crypto Wallet Engine slice 4 — token send panel', () {
    Map<String, dynamic> tokenDraftResponse() => const {
      'status':              'draft_ready',
      'asset':               'USDT_ERC20',
      'network':             'Ethereum Sepolia',
      'fromAddress':         _kFromAddress,
      'destinationAddress':  _kDestAddress,
      'amount':              '10',
      'amountBaseUnits':     '10000000',
      'unit':                'USDT',
      'tokenContract':       _kTokenContract,
      'decimals':            6,
      'transactionTo':       _kTokenContract,
      'transactionValueWei': '0',
      
      'dataHex':
          '0xa9059cbb000000000000000000000000'
              '2b5ad5c4795c026514f8317c7a215e218dccd6cf'
              '0000000000000000000000000000000000000000000000000000000000989680',
      'nonce':              '0',
      'gasLimit':           '65000',
      'gasPrice':           '20000000000',
      'chainId':            11155111,
      'feeUnit':            'ETH',
    };

    Future<void> _walkToReview(WidgetTester tester) async {
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_destination_input')),
        _kDestAddress,
      );
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_amount_input')),
        '10',
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
      await tester.pumpAndSettle();
    }

    Future<void> _walkThroughPin(WidgetTester tester, String pin) async {
      await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('eth_send_panel_pin_input')),
        pin,
      );
      await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
      await tester.pumpAndSettle();
    }

    testWidgets(
        'T6: token send panel calls draft endpoint with TOKEN asset id',
        (tester) async {
      final client = _FakeTokenSendClient(
        draftResponse: tokenDraftResponse(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        },
      );
      await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: client,
            decryptForVault: (ct) async => _kPlaintextPk,
            isVaultKeyAvailable: () => true,
            verifyPin: (pin) async => true,
            asset: 'USDT_ERC20',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await _walkToReview(tester);
      
      expect(client.lastDraftAsset, equals('USDT_ERC20'));
      expect(client.lastDraftBody!['amountEth'], equals('10'));
    });

    testWidgets(
        'T7+T8+T10: end-to-end — encrypted-secret + sign(dataHex) + broadcast',
        (tester) async {
      final client = _FakeTokenSendClient(
        draftResponse: tokenDraftResponse(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
          'underlyingAsset': 'ETH',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        },
      );
      await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: client,
            decryptForVault: (ct) async => _kPlaintextPk,
            isVaultKeyAvailable: () => true,
            verifyPin: (pin) async => true,
            asset: 'USDT_ERC20',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await _walkToReview(tester);
      await _walkThroughPin(tester, '123456');

      
      expect(client.encryptedSecretCallCount, equals(1));
      expect(client.lastEncryptedSecretAsset, equals('USDT_ERC20'));
      
      expect(client.broadcastCallCount, equals(1));
      
      expect(
        client.lastBroadcastBody!.keys.toSet(),
        equals({'asset', 'signedTransaction'}),
      );
      
      expect(client.lastBroadcastBody!['asset'], equals('USDT_ERC20'));
      final signed = client.lastBroadcastBody!['signedTransaction'] as String;
      
      expect(signed.startsWith('0x'), isTrue);
      expect(signed.length, greaterThan(200));
      
      
      expect(signed.contains('a9059cbb'), isTrue,
          reason: 'signed RLP must carry the ERC20 transfer '
              'selector (0xa9059cbb) inside its data field');
      
      expect(
        find.byKey(const Key('eth_send_panel_submitted_stage')),
        findsOneWidget,
      );
    });

    testWidgets(
        'T9: review renders amount in TOKEN units; fee in ETH',
        (tester) async {
      final client = _FakeTokenSendClient(
        draftResponse: tokenDraftResponse(),
        encryptedSecretResponse: const {
          'status': 'encrypted_secret_ready',
          'encryptedWalletSecret': 'CT-xyz',
        },
        broadcastResponse: const {
          'status': 'submitted',
          'txHash':
              '0x' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        },
      );
      await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEngineSendPanel(
            authToken: 'tok',
            fromAddress: _kFromAddress,
            client: client,
            decryptForVault: (ct) async => _kPlaintextPk,
            isVaultKeyAvailable: () => true,
            verifyPin: (pin) async => true,
            asset: 'USDT_ERC20',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await _walkToReview(tester);
      
      expect(find.textContaining('10 USDT'), findsOneWidget);
      
      expect(find.textContaining('ETH'), findsAtLeastNWidgets(1));
      
      expect(
        find.textContaining('Gas requires Sepolia ETH'),
        findsOneWidget,
      );
    });
  });
}
