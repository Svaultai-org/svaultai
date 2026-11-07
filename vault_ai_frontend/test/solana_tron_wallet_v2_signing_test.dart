import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';

const _solDestination = '11111111111111111111111111111111';
const _solBlockhash = 'FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE';
const _tronDestination = 'TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9';
const _tronTxId =
    '0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20';

class _NoBroadcastApi extends VaultAIClient {
  _NoBroadcastApi(this.chain, this.fromAddress)
      : super(baseUrl: 'http://test.invalid');

  final String chain;
  final String fromAddress;
  int legacySecretCalls = 0;
  int expiryChecks = 0;
  int broadcastCalls = 0;
  bool expireAfterSigning = true;
  void Function()? onSecondExpiryCheck;

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
    expect(fromAddress, this.fromAddress);
    if (chain == 'solana') {
      return {
        'status': 'draft_ready',
        'asset': 'SOL',
        'network': 'solana_mainnet',
        'fromAddress': this.fromAddress,
        'destinationAddress': destinationAddress,
        'amountSol': '0.5',
        'lamports': '500000000',
        'recentBlockhash': _solBlockhash,
        'draftId': 'synthetic-sol-draft',
        'feeLamports': 5000,
      };
    }
    return {
      'status': 'draft_ready',
      'asset': 'USDT_TRC20',
      'network': 'tron_mainnet',
      'fromAddress': this.fromAddress,
      'destinationAddress': destinationAddress,
      'amountUsdt': '5.5',
      'amountBaseUnits': '5500000',
      'unsignedTransaction': {
        'txID': _tronTxId,
        'raw_data': {'contract': [], 'expiration': 99999999999999},
        'raw_data_hex': '0a0b0c0d',
      },
      'txID': _tronTxId,
      'rawDataHex': '0a0b0c0d',
      'feeLimitSun': 100000000,
      'trxBalanceSun': 200000000,
      'resourceStatus': 'ready',
      'draftId': 'synthetic-tron-draft',
      'expirationMs': 99999999999999,
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    legacySecretCalls++;
    throw StateError('Legacy secret read attempted');
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletDraftExpiryNetwork({
    required String network,
    required String draftId,
    required String authToken,
  }) async {
    expiryChecks++;
    if (expiryChecks == 2) onSecondExpiryCheck?.call();
    // The first check permits local signing. The second check stops before
    // broadcast, proving the V2 signing path without sending a transaction.
    return {'expired': expireAfterSigning && expiryChecks >= 2};
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
    broadcastCalls++;
    throw StateError('Broadcast must not run in this test');
  }
}

Future<WalletV2ActiveClient> _verifiedWallet(
    WalletV2AccountSlot slot, String address, String secret,
    {bool Function()? accessIsCurrent}) async {
  final identity = WalletV2Identity(
    recordId: 'synthetic-${slot.chain}-record',
    chain: slot.chain,
    network: slot.network,
    asset: slot.asset,
    publicAddress: address,
    label: 'Synthetic wallet',
  );
  final ciphertext = await WalletV2EnvelopeCodec(
    SecretKey(List<int>.filled(32, 27)),
  ).wrap(identity, secret);
  return WalletV2ActiveClient(
    codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 27))),
    accessIsCurrent: accessIsCurrent ?? () => true,
    get: (path) async {
      if (path == '/vault/wallet-v2') {
        return {
          'wallets': [
            {
              'wallet_record_id': identity.recordId,
              'chain': identity.chain,
              'network': identity.network,
              'asset': identity.asset,
              'public_address': identity.publicAddress,
              'wallet_label': identity.label,
              'migration_state': 'v2_verified',
            },
          ],
        };
      }
      expect(path, '/vault/wallet-v2/${identity.recordId}');
      return {
        'wallet_record_id': identity.recordId,
        'chain': identity.chain,
        'network': identity.network,
        'asset': identity.asset,
        'public_address': identity.publicAddress,
        'wallet_label': identity.label,
        'envelope_version': 'v2',
        'migration_state': 'v2_verified',
        'payload_ciphertext': ciphertext,
      };
    },
    post: (_, __) async => throw StateError('Unexpected V2 write'),
  );
}

CryptoWalletFeatures _features(String chain) =>
    CryptoWalletFeatures.fromBackend({
      'walletEngineEnabled': true,
      'sepoliaReceiveEnabled': true,
      'sepoliaSendEnabled': true,
      'mainnetReceiveEnabled': false,
      'mainnetErc20ReceiveEnabled': false,
      'mainnetSendEnabled': false,
      'mainnetSendPaused': false,
      'defaultNetwork': 'ethereum_sepolia',
      'defaultNetworkConfigValid': true,
      'solanaEnabled': chain == 'solana',
      'solanaReceiveEnabled': chain == 'solana',
      'solanaBalanceEnabled': chain == 'solana',
      'solanaSendEnabled': chain == 'solana',
      'solanaSendPaused': false,
      'tronEnabled': chain == 'tron',
      'tronReceiveEnabled': chain == 'tron',
      'tronBalanceEnabled': chain == 'tron',
      'tronSendEnabled': chain == 'tron',
      'tronSendPaused': false,
      'tronUsdtContractConfigured': chain == 'tron',
      'supportedNetworks': ['ethereum_sepolia', '${chain}_mainnet'],
      'supportedAssetsByNetwork': {
        'ethereum_sepolia': ['ETH'],
        '${chain}_mainnet': [chain == 'solana' ? 'SOL' : 'USDT_TRC20'],
      },
    });

void main() {
  testWidgets('Solana V2 signs locally then stops at expiry, no legacy read',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final generated = await generateSolanaWallet();
    final address = generated.publicAddress;
    final secret = jsonEncode({
      'schema': 'solana_secret_v1',
      'keyOrigin': 'generated_client_side',
      'secretKeyBase58': generated.secretKeyBase58,
    });
    final wallet = await _verifiedWallet(
      const WalletV2AccountSlot('solana', 'solana_mainnet', 'SOL'),
      address,
      secret,
    );
    final api = _NoBroadcastApi('solana', address);
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
          body: CryptoWalletEngineSolanaSendPanel(
        authToken: 'synthetic-token',
        fromAddress: address,
        client: api,
        walletV2: wallet,
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        features: _features('solana'),
        fetchAvailableLamports: () async => BigInt.from(1000000000000),
      )),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key(kSolanaSendDestinationInputKey)), _solDestination);
    await tester.enterText(
        find.byKey(const Key(kSolanaSendAmountInputKey)), '0.5');
    await tester.tap(find.byKey(const Key(kSolanaSendReviewButtonKey)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key(kSolanaSendConfirmButtonKey)));
    await tester.pump();
    await tester.enterText(
        find.byKey(const Key(kSolanaSendPinInputKey)), '123456');
    await tester.tap(find.byKey(const Key(kSolanaSendPinConfirmBtnKey)));
    await tester.pumpAndSettle();
    expect(api.expiryChecks, 2,
        reason: 'second expiry check runs only after local signing');
    expect(api.legacySecretCalls, 0);
    expect(api.broadcastCalls, 0);
    wipeSecretKey(generated.secretKeyBytes);
  });

  testWidgets('Solana V2 refuses broadcast if vault locks after signing',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final generated = await generateSolanaWallet();
    final address = generated.publicAddress;
    var accessCurrent = true;
    final wallet = await _verifiedWallet(
      const WalletV2AccountSlot('solana', 'solana_mainnet', 'SOL'),
      address,
      jsonEncode({
        'schema': 'solana_secret_v1',
        'keyOrigin': 'generated_client_side',
        'secretKeyBase58': generated.secretKeyBase58,
      }),
      accessIsCurrent: () => accessCurrent,
    );
    final api = _NoBroadcastApi('solana', address)
      ..expireAfterSigning = false
      ..onSecondExpiryCheck = () => accessCurrent = false;
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
          body: CryptoWalletEngineSolanaSendPanel(
        authToken: 'synthetic-token',
        fromAddress: address,
        client: api,
        walletV2: wallet,
        isVaultKeyAvailable: () => accessCurrent,
        verifyPin: (_) async => true,
        features: _features('solana'),
        fetchAvailableLamports: () async => BigInt.from(1000000000000),
      )),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key(kSolanaSendDestinationInputKey)), _solDestination);
    await tester.enterText(
        find.byKey(const Key(kSolanaSendAmountInputKey)), '0.5');
    await tester.tap(find.byKey(const Key(kSolanaSendReviewButtonKey)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key(kSolanaSendConfirmButtonKey)));
    await tester.pump();
    await tester.enterText(
        find.byKey(const Key(kSolanaSendPinInputKey)), '123456');
    await tester.tap(find.byKey(const Key(kSolanaSendPinConfirmBtnKey)));
    await tester.pumpAndSettle();
    expect(api.expiryChecks, 2);
    expect(accessCurrent, isFalse);
    expect(api.legacySecretCalls, 0);
    expect(api.broadcastCalls, 0);
    wipeSecretKey(generated.secretKeyBytes);
  });

  testWidgets('TRON V2 signs locally then stops at expiry, no legacy read',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final generated = generateTronWallet();
    final address = generated.publicAddress;
    final secret = jsonEncode({
      'schema': 'tron_secret_v1',
      'keyOrigin': 'generated_client_side',
      'privateKeyHex': generated.privateKeyHex,
    });
    final wallet = await _verifiedWallet(
      const WalletV2AccountSlot('tron', 'tron_mainnet', 'USDT_TRC20'),
      address,
      secret,
    );
    final api = _NoBroadcastApi('tron', address);
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
          body: CryptoWalletEngineTronSendPanel(
        authToken: 'synthetic-token',
        fromAddress: address,
        client: api,
        walletV2: wallet,
        isVaultKeyAvailable: () => true,
        verifyPin: (_) async => true,
        features: _features('tron'),
        fetchAvailableTokenBaseUnits: () async => BigInt.from(999999999999),
        fetchTrxBalanceSun: () async => BigInt.from(999999999999999),
      )),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key(kTronSendDestinationInputKey)), _tronDestination);
    await tester.enterText(
        find.byKey(const Key(kTronSendAmountInputKey)), '5.5');
    await tester.tap(find.byKey(const Key(kTronSendReviewButtonKey)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key(kTronSendConfirmButtonKey)));
    await tester.pump();
    await tester.enterText(
        find.byKey(const Key(kTronSendPinInputKey)), '123456');
    await tester.tap(find.byKey(const Key(kTronSendPinConfirmBtnKey)));
    await tester.pumpAndSettle();
    expect(api.expiryChecks, 2,
        reason: 'second expiry check runs only after local signing');
    expect(api.legacySecretCalls, 0);
    expect(api.broadcastCalls, 0);
    wipeTronPrivateKeyHex(generated.privateKeyHex);
  });
}
