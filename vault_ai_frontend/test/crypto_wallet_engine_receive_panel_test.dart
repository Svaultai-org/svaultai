

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/ethereum_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';

class _FakeClient extends VaultAIClient {
  Map<String, dynamic> _receiveResponse;
  Map<String, dynamic> _createResponse;
  bool throwOnCreate;

  
  String? lastCreateAsset;
  String? lastCreatePublicAddress;
  String? lastCreateEncryptedSecret;
  String? lastCreateNetwork;
  String? lastCreateWalletLabel;
  String? lastCreateAuthToken;
  int createCallCount = 0;
  int receiveCallCount = 0;

  _FakeClient({
    required Map<String, dynamic> initialReceiveResponse,
    Map<String, dynamic>? createResponse,
    this.throwOnCreate = false,
  })  : _receiveResponse = initialReceiveResponse,
        _createResponse = createResponse ?? <String, dynamic>{
          'wallet_engine': 'created',
          'account': <String, dynamic>{},
        },
        super(baseUrl: 'http://test.invalid');

  void setReceiveResponse(Map<String, dynamic> body) {
    _receiveResponse = body;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    receiveCallCount++;
    return _receiveResponse;
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccount({
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String network,
    required String encryptedWalletSecret,
  }) async {
    createCallCount++;
    lastCreateAsset = asset;
    lastCreatePublicAddress = publicAddress;
    lastCreateEncryptedSecret = encryptedWalletSecret;
    lastCreateNetwork = network;
    lastCreateWalletLabel = walletLabel;
    lastCreateAuthToken = authToken;
    if (throwOnCreate) {
      throw Exception('create failed');
    }
    return _createResponse;
  }
}

void main() {
  group('crypto_wallet_engine_receive_panel slice 2', () {
    testWidgets('RP1: no_account state renders Create button + attestation',
        (tester) async {
      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'no_account', 'asset': 'ETH',
        },
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct_$p',
            isVaultKeyAvailable: () => true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('eth_receive_panel_create_state')),
          findsOneWidget);
      expect(find.byKey(const Key('eth_receive_panel_create_btn')),
          findsOneWidget);
      expect(find.text(kEthReceiveNonCustodialAttestation), findsOneWidget);
      expect(find.text(kEthReceiveCreateButtonLabel), findsOneWidget);
    });

    testWidgets('RP2: Create blocked when vault key is NOT available',
        (tester) async {
      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'no_account', 'asset': 'ETH',
        },
      );
      var encryptCallCount = 0;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async {
              encryptCallCount++;
              return 'ct_$p';
            },
            isVaultKeyAvailable: () => false,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
      await tester.pump();
      
      expect(find.text(kEthReceiveCreateBlockedNoVaultKey), findsOneWidget);
      
      expect(encryptCallCount, equals(0));
      expect(client.createCallCount, equals(0));
    });

    testWidgets(
        'RP3: Create with vault key — wallet generated, encrypted, persisted',
        (tester) async {
      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'no_account', 'asset': 'ETH',
        },
      );
      String? capturedPlaintext;
      var encryptCallCount = 0;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async {
              encryptCallCount++;
              capturedPlaintext = p;
              return 'CT::$p';
            },
            isVaultKeyAvailable: () => true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      expect(client.receiveCallCount, equals(1));
      
      
      client.setReceiveResponse(const {
        'wallet_engine': 'receive_ready',
        'asset': 'ETH',
        'network': 'Ethereum Sepolia',
        'walletLabel': 'VaultAI ETH wallet',
        'publicAddress': '0x0000000000000000000000000000000000000001',
        'warning': 'asset warning',
      });
      await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
      await tester.pumpAndSettle();

      
      expect(encryptCallCount, equals(1));
      
      expect(capturedPlaintext, isNotNull);
      expect(
        RegExp(r'^[0-9a-f]{64}$').hasMatch(capturedPlaintext!),
        isTrue,
        reason: 'encryptForVault must receive the 64-hex private key, '
            'not the address or any other value.',
      );
      
      expect(client.createCallCount, equals(1));
      
      expect(client.lastCreateEncryptedSecret,
          equals('CT::$capturedPlaintext'));
      
      expect(client.lastCreatePublicAddress, isNotNull);
      final expectedAddr =
          deriveEthereumAddressFromPrivateKeyHex(capturedPlaintext!);
      expect(client.lastCreatePublicAddress, equals(expectedAddr));
      
      expect(client.lastCreateEncryptedSecret!.contains(capturedPlaintext!),
          isTrue,
          reason: 'the create call should carry "CT::<plaintext>" '
              '(ciphertext from the closure) — the closure embedded the '
              'plaintext as part of its return value for verification.');
      
      for (final v in <String?>[
        client.lastCreatePublicAddress,
        client.lastCreateNetwork,
        client.lastCreateWalletLabel,
        client.lastCreateAuthToken,
        client.lastCreateAsset,
      ]) {
        expect(
          v?.contains(capturedPlaintext!) ?? false,
          isFalse,
          reason: 'plaintext private key must NEVER appear in non-secret '
              'fields',
        );
      }
      
      expect(client.receiveCallCount, equals(2));
    });

    testWidgets('RP4: ready state renders address + QR + copy + warning',
        (tester) async {
      
      
      const fakeWarning = 'Only send Ethereum (Sepolia testnet) to this '
          'address.';
      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'receive_ready',
          'asset': 'ETH',
          'network': 'Ethereum Sepolia',
          'walletLabel': 'VaultAI ETH wallet',
          'publicAddress': '0x1234567890aBCdef1234567890aBcDEF12345678',
          'warning': fakeWarning,
        },
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct',
            isVaultKeyAvailable: () => true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('eth_receive_panel_ready_state')),
          findsOneWidget);
      expect(find.byKey(const Key('eth_receive_panel_qr')), findsOneWidget);
      expect(find.byKey(const Key('eth_receive_panel_address_text')),
          findsOneWidget);
      expect(find.byKey(const Key('eth_receive_panel_copy_btn')),
          findsOneWidget);
      expect(find.text(fakeWarning), findsOneWidget);
    });

    testWidgets('RP5: Copy puts the address on the clipboard', (tester) async {
      
      
      const addr = '0x1234567890aBCdef1234567890aBcDEF12345678';
      Object? clipboardWrite;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboardWrite = (call.arguments as Map?)?['text'];
        }
        return null;
      });
      addTearDown(() {
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform, null);
      });

      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'receive_ready',
          'asset': 'ETH', 'network': 'Ethereum Sepolia',
          'walletLabel': 'eth', 'publicAddress': addr,
          'warning': 'asset warning copy',
        },
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct',
            isVaultKeyAvailable: () => true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('eth_receive_panel_copy_btn')));
      await tester.pump();
      expect(clipboardWrite, equals(addr));
      expect(find.text(kEthReceiveCopyDoneSnackbar), findsOneWidget);
    });

    testWidgets(
        'RP6: engine_disabled state renders the closed-set dark message',
        (tester) async {
      
      
      final client = _FakeClient(
        initialReceiveResponse: const {
          'wallet_engine': 'engine_disabled',
          'message': 'The Crypto Wallet Engine is not yet enabled.',
        },
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineReceivePanel(
            authToken: 'tok',
            client: client,
            encryptForVault: (p) async => 'ct',
            isVaultKeyAvailable: () => true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('eth_receive_panel_engine_disabled')),
          findsOneWidget);
      expect(
        find.text('Crypto Wallet Engine is disabled by the backend.'),
        findsOneWidget,
      );
      
      expect(
        find.textContaining('Crypto Vault Lite remains available'),
        findsNothing,
      );
    });
  });
}
