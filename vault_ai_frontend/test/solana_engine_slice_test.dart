

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_receive_panel.dart';


class _SolanaSpyClient extends VaultAIClient {
  final List<String> receiveNetworkCalls = [];
  final List<String> createNetworkCalls = [];
  final List<String> lastCreateBodies = [];
  final List<String> balanceNetworkCalls = [];
  Map<String, dynamic> nextReceiveResponse = {
    'wallet_engine': 'create_solana_wallet_first',
    'network':       'solana_mainnet',
  };
  String? lastEncryptedSecretSeen;
  String? lastPublicAddressSeen;

  _SolanaSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveNetworkCalls.add('$network/$asset');
    return nextReceiveResponse;
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccountNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String encryptedWalletSecret,
    int? restoreHeight,
    String? scannerMode,
  }) async {
    createNetworkCalls.add('$network/$asset');
    lastEncryptedSecretSeen = encryptedWalletSecret;
    lastPublicAddressSeen = publicAddress;
    lastCreateBodies.add(jsonEncode({
      'network':               network,
      'asset':                 asset,
      'walletLabel':           walletLabel,
      'publicAddress':         publicAddress,
      'encryptedWalletSecret': encryptedWalletSecret,
    }));
    return {'wallet_engine': 'created'};
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceNetworkCalls.add('$network/$asset');
    return {'balanceStatus': 'unavailable', 'reason': 'no_wallet_yet'};
  }
}


CryptoWalletFeatures _features({bool solanaOn = true}) {
  return CryptoWalletFeatures.fromBackend({
    'walletEngineEnabled':      true,
    'sepoliaReceiveEnabled':    true,
    'sepoliaSendEnabled':       true,
    'mainnetReceiveEnabled':    false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':       false,
    'mainnetSendPaused':        false,
    'defaultNetwork':           'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'solanaEnabled':            solanaOn,
    'solanaReceiveEnabled':     solanaOn,
    'solanaBalanceEnabled':     solanaOn,
    'solanaSendEnabled':        false,
    'solanaActivityConnected':  false,
    'supportedNetworks':        solanaOn
        ? ['ethereum_sepolia', 'ethereum_mainnet', 'solana_mainnet']
        : ['ethereum_sepolia', 'ethereum_mainnet'],
    'supportedAssetsByNetwork': const {
      'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'solana_mainnet':   ['SOL'],
    },
  });
}


Future<void> _pumpSolanaPanel(
  WidgetTester tester, {
  required _SolanaSpyClient client,
  CryptoWalletFeatures? features,
  bool vaultKeyAvailable = true,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: CryptoWalletEngineSolanaReceivePanel(
          authToken: 'test-token',
          client: client,
          encryptForVault: (plaintext) async =>
              'ciphertext:${plaintext.length}',
          isVaultKeyAvailable: () => vaultKeyAvailable,
          features: features,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('base58 encode/decode round-trip', () {
    test('encode empty bytes returns empty string', () {
      expect(base58Encode(Uint8List(0)), equals(''));
    });

    test('encode 32-byte fixed vector matches known Solana address', () {
      final zeros = Uint8List(32);
      final encoded = base58Encode(zeros);
      expect(encoded, equals('11111111111111111111111111111111'));
    });

    test('decode encode round-trip preserves 32 random-ish bytes', () {
      final input = Uint8List.fromList(List<int>.generate(
        32, (i) => (i * 17 + 7) & 0xff,
      ));
      final encoded = base58Encode(input);
      final decoded = base58Decode(encoded);
      expect(decoded, isNotNull);
      expect(decoded!.length, equals(32));
      for (var i = 0; i < 32; i++) {
        expect(decoded[i], equals(input[i]));
      }
    });

    test('decode invalid character returns null', () {
      expect(base58Decode('0OIl'), isNull);
    });
  });

  group('isValidSolanaAddress classifier', () {
    test('accepts the wrapped-SOL native address', () {
      expect(
        isValidSolanaAddress(
          'So11111111111111111111111111111111111111112',
        ),
        isTrue,
      );
    });

    test('rejects empty and null', () {
      expect(isValidSolanaAddress(null), isFalse);
      expect(isValidSolanaAddress(''), isFalse);
    });

    test('rejects Ethereum-shape 0x prefix', () {
      expect(
        isValidSolanaAddress('0x${'a' * 40}'),
        isFalse,
      );
    });

    test('rejects too-short base58', () {
      expect(isValidSolanaAddress('1abc'), isFalse);
    });
  });

  group('client-side Solana wallet generation', () {
    test('generateSolanaWallet produces a valid base58 address', () async {
      final wallet = await generateSolanaWallet();
      expect(isValidSolanaAddress(wallet.publicAddress), isTrue);
      expect(wallet.secretKeyBytes.length, equals(64));
    });

    test('two generations produce distinct keypairs', () async {
      final a = await generateSolanaWallet();
      final b = await generateSolanaWallet();
      expect(a.publicAddress, isNot(equals(b.publicAddress)));
      var identical = true;
      for (var i = 0; i < 64; i++) {
        if (a.secretKeyBytes[i] != b.secretKeyBytes[i]) {
          identical = false;
          break;
        }
      }
      expect(identical, isFalse);
    });

    test('wipeSecretKey zeroes every byte', () async {
      final wallet = await generateSolanaWallet();
      wipeSecretKey(wallet.secretKeyBytes);
      for (final b in wallet.secretKeyBytes) {
        expect(b, equals(0));
      }
    });
  });

  group('CryptoWalletFeatures solana fields', () {
    test('unknown() reports solana disabled', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.solanaEnabled, isFalse);
      expect(f.solanaReceiveEnabled, isFalse);
      expect(f.solanaBalanceEnabled, isFalse);
      expect(f.solanaSendEnabled, isFalse);
      expect(f.solanaActivityConnected, isFalse);
    });

    test('fromBackend parses solana flags', () {
      final f = CryptoWalletFeatures.fromBackend({
        'solanaEnabled':           true,
        'solanaReceiveEnabled':    true,
        'solanaBalanceEnabled':    true,
        'solanaSendEnabled':       false,
        'solanaActivityConnected': false,
      });
      expect(f.solanaEnabled, isTrue);
      expect(f.solanaReceiveEnabled, isTrue);
      expect(f.solanaSendEnabled, isFalse);
    });
  });

  group('Solana receive panel — coming-next state', () {
    testWidgets(
        'when features.solanaEnabled is false, panel shows '
        'coming-next disabled banner and never calls receive API',
        (tester) async {
      final client = _SolanaSpyClient();
      await _pumpSolanaPanel(
        tester, client: client, features: _features(solanaOn: false),
      );
      expect(client.receiveNetworkCalls, isEmpty);
      expect(
        find.byKey(const Key(kSolanaReceivePanelDisabledKey)),
        findsOneWidget,
      );
    });
  });

  group('Solana receive panel — create flow', () {
    testWidgets(
        'when Solana is enabled and no wallet exists, panel calls '
        'mainnet-solana receive endpoint and offers Create button',
        (tester) async {
      final client = _SolanaSpyClient();
      await _pumpSolanaPanel(tester, client: client, features: _features());
      expect(client.receiveNetworkCalls,
          equals(['solana_mainnet/SOL']));
      expect(
        find.byKey(const Key(kSolanaReceivePanelCreateBtnKey)),
        findsOneWidget,
      );
    });

    testWidgets(
        'tapping Create sends only ciphertext + publicAddress to backend',
        (tester) async {
      final client = _SolanaSpyClient();
      await _pumpSolanaPanel(tester, client: client, features: _features());


      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': 'So11111111111111111111111111111111111111112',
        'walletLabel':   'VaultAI SOL wallet',
        'warning':       'Only send SOL on Solana to this address.',
      };

      await tester.tap(
        find.byKey(const Key(kSolanaReceivePanelCreateBtnKey)),
      );
      await tester.pumpAndSettle();

      expect(client.createNetworkCalls,
          equals(['solana_mainnet/SOL']));
      expect(client.lastEncryptedSecretSeen, isNotNull);
      expect(client.lastEncryptedSecretSeen,
          startsWith('ciphertext:'));
      expect(client.lastPublicAddressSeen, isNotNull);
      expect(
        isValidSolanaAddress(client.lastPublicAddressSeen),
        isTrue,
      );


      final serialized = client.lastCreateBodies.first;
      for (final banned in [
        'privateKey', 'private_key', 'secretKey', 'secret_key',
        'seed', 'seedPhrase', 'mnemonic', 'recoveryPhrase',
      ]) {
        expect(serialized, isNot(contains('"$banned":')),
            reason: 'Solana create body must not carry $banned');
      }
    });
  });

  group('Solana receive panel — ready state', () {
    testWidgets(
        'ready state renders QR + address + warning + copy button',
        (tester) async {
      final client = _SolanaSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': 'So11111111111111111111111111111111111111112',
        'walletLabel':   'VaultAI SOL wallet',
        'warning':       'Only send SOL on Solana to this address.',
      };
      await _pumpSolanaPanel(tester, client: client, features: _features());
      expect(
        find.byKey(const Key(kSolanaReceivePanelQrKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kSolanaReceivePanelAddressTextKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kSolanaReceivePanelCopyBtnKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kSolanaReceivePanelWarningKey)),
        findsOneWidget,
      );
    });

    testWidgets(
        'warning contains "Solana" and never "Ethereum" / "Sepolia"',
        (tester) async {
      final client = _SolanaSpyClient();
      client.nextReceiveResponse = {
        'wallet_engine': 'receive_ready',
        'publicAddress': 'So11111111111111111111111111111111111111112',
        'walletLabel':   'VaultAI SOL wallet',
        'warning':       'Only send SOL on Solana to this address.',
      };
      await _pumpSolanaPanel(tester, client: client, features: _features());
      final warningWidget = tester.widget<Text>(
        find.byKey(const Key(kSolanaReceivePanelWarningKey)),
      );
      final txt = warningWidget.data?.toLowerCase() ?? '';
      expect(txt, contains('sol'));
      expect(txt, contains('solana'));
      expect(txt, isNot(contains('ethereum')));
      expect(txt, isNot(contains('sepolia')));
      expect(txt, isNot(contains('erc20')));
    });
  });

  group('non-exchange surface', () {
    test('Solana receive copy contains no exchange verbs', () {
      final blobs = [
        kSolanaReceivePanelTitle,
        kSolanaReceiveNetworkBadge,
        kSolanaReceiveCreateButtonLabel,
        kSolanaReceiveAssetWarning,
        kSolanaReceiveNonCustodialAttestation,
        kSolanaReceiveDisabledMessage,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap', 'stake', 'bridge',
                              ' buy ', ' sell ', ' trade ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'Solana copy leaked banned language: $b');
        }
      }
    });

    test('Solana copy never references TRC20 / bitcoin / bnb', () {
      for (final b in [
        kSolanaReceivePanelTitle,
        kSolanaReceiveAssetWarning,
        kSolanaReceiveDisabledMessage,
      ]) {
        final lower = b.toLowerCase();
        expect(lower, isNot(contains('trc20')));
        expect(lower, isNot(contains('bitcoin')));
        expect(lower, isNot(contains('bnb')));
      }
    });
  });

  group('Solana wallet service imports never carry send-side crypto', () {
    test('solana_wallet.dart never imports transaction signers', () async {
      final src = await File(
        'lib/services/solana_wallet.dart',
      ).readAsString();
      final lower = src.toLowerCase();
      for (final banned in [
        'sendtransaction',
        'send_transaction',
        'solanatransaction',
        'sign_transaction',
      ]) {
        expect(lower, isNot(contains(banned)),
            reason: 'solana_wallet.dart leaked banned symbol: '
                '$banned');
      }
    });
  });
}
