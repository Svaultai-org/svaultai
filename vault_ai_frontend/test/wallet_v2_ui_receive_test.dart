import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/ethereum_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';

class _ReceiveOnlyClient extends VaultAIClient {
  _ReceiveOnlyClient(this.receiveBody) : super(baseUrl: 'http://test.invalid');

  final Map<String, dynamic> receiveBody;
  var legacyCreates = 0;

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async => receiveBody;

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccount({
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String network,
    required String encryptedWalletSecret,
  }) async {
    legacyCreates++;
    throw StateError('Legacy wallet write attempted');
  }
}

class _StaleAfterReadWallet extends WalletV2ActiveClient {
  _StaleAfterReadWallet({
    required this.identity,
    required this.expire,
    required bool Function() current,
  }) : super(
          codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 6))),
          accessIsCurrent: current,
          get: (_) async => throw StateError('Unexpected wallet GET'),
          post: (_, __) async => throw StateError('Unexpected wallet POST'),
        );

  final WalletV2Identity identity;
  final void Function() expire;

  @override
  Future<WalletV2Identity?> findVerified(WalletV2AccountSlot slot) async =>
      identity;

  @override
  Future<String> readSigningSecret(WalletV2Identity identity) async {
    expire(); // The vault locks after the last awaited verification.
    return 'synthetic-local-secret';
  }
}

void main() {
  const recordId = 'synthetic-wallet-ui-record-1';
  const address = '0x0000000000000000000000000000000000000001';
  const label = 'Synthetic wallet';

  WalletV2ActiveClient walletClient({
    required Future<Map<String, dynamic>> Function(String) get,
    required Future<Map<String, dynamic>> Function(
      String, Map<String, dynamic>) post,
    bool creationEnabled = false,
  }) => WalletV2ActiveClient(
    codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 6))),
    accessIsCurrent: () => true,
    creationEnabled: creationEnabled,
    newRecordId: () => recordId,
    get: get,
    post: post,
  );

  testWidgets('verified V2 address opens from a no-account receive result',
      (tester) async {
    const secret =
        '0000000000000000000000000000000000000000000000000000000000000001';
    final verifiedAddress = deriveEthereumAddressFromPrivateKeyHex(secret);
    final identity = WalletV2Identity(
      recordId: recordId, chain: 'evm', network: 'ethereum_sepolia',
      asset: 'ETH', publicAddress: verifiedAddress, label: label,
    );
    final ciphertext = await WalletV2EnvelopeCodec(
      SecretKey(List<int>.filled(32, 6)),
    ).wrap(identity, secret);
    final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
    final wallet = walletClient(
      get: (path) async => path == '/vault/wallet-v2'
          ? {'wallets': [
              {
                'wallet_record_id': recordId, 'chain': 'evm',
                'network': 'ethereum_sepolia', 'asset': 'ETH',
                'public_address': verifiedAddress, 'wallet_label': label,
                'migration_state': 'v2_verified',
              },
            ]}
          : {
              'wallet_record_id': recordId, 'chain': 'evm',
              'network': 'ethereum_sepolia', 'asset': 'ETH',
              'public_address': verifiedAddress, 'wallet_label': label,
              'migration_state': 'v2_verified', 'envelope_version': 'v2',
              'payload_ciphertext': ciphertext,
            },
      post: (_, __) async => throw StateError('Unexpected write'),
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eth_receive_panel_ready_state')),
        findsOneWidget);
    expect(find.text(verifiedAddress), findsOneWidget);
    expect(api.legacyCreates, 0);
  });

  for (final tokenAsset in const ['USDT_ERC20', 'USDC_ERC20']) {
    testWidgets('$tokenAsset receive uses the verified ETH wallet backup',
        (tester) async {
      const secret =
          '0000000000000000000000000000000000000000000000000000000000000001';
      final verifiedAddress = deriveEthereumAddressFromPrivateKeyHex(secret);
      final identity = WalletV2Identity(
        recordId: recordId, chain: 'evm', network: 'ethereum_sepolia',
        asset: 'ETH', publicAddress: verifiedAddress, label: label,
      );
      final ciphertext = await WalletV2EnvelopeCodec(
        SecretKey(List<int>.filled(32, 6)),
      ).wrap(identity, secret);
      final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
      final wallet = walletClient(
        get: (path) async => path == '/vault/wallet-v2'
            ? {'wallets': [
                {
                  'wallet_record_id': recordId, 'chain': 'evm',
                  'network': 'ethereum_sepolia', 'asset': 'ETH',
                  'public_address': verifiedAddress, 'wallet_label': label,
                  'migration_state': 'v2_verified',
                },
              ]}
            : {
                'wallet_record_id': recordId, 'chain': 'evm',
                'network': 'ethereum_sepolia', 'asset': 'ETH',
                'public_address': verifiedAddress, 'wallet_label': label,
                'migration_state': 'v2_verified', 'envelope_version': 'v2',
                'payload_ciphertext': ciphertext,
              },
        post: (_, __) async => throw StateError('Unexpected write'),
      );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body:
        CryptoWalletEngineReceivePanel(
          authToken: 'synthetic-token', client: api,
          asset: tokenAsset, walletV2: wallet,
          encryptForVault: (_) async => throw StateError('Legacy encryption'),
          isVaultKeyAvailable: () => true,
        ),
      )));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('eth_receive_panel_ready_state')),
          findsOneWidget);
      expect(find.text(verifiedAddress), findsOneWidget);
      expect(api.legacyCreates, 0);
    });
  }

  testWidgets('unreadable V2 backup never renders a receive address',
      (tester) async {
    final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
    final wallet = walletClient(
      get: (path) async => path == '/vault/wallet-v2'
          ? {'wallets': [
              {
                'wallet_record_id': recordId, 'chain': 'evm',
                'network': 'ethereum_sepolia', 'asset': 'ETH',
                'public_address': address, 'wallet_label': label,
                'migration_state': 'v2_verified',
              },
            ]}
          : {
              'wallet_record_id': recordId, 'chain': 'evm',
              'network': 'ethereum_sepolia', 'asset': 'ETH',
              'public_address': address, 'wallet_label': label,
              'migration_state': 'v2_verified', 'envelope_version': 'v2',
              'payload_ciphertext': 'corrupted-ciphertext',
            },
      post: (_, __) async => throw StateError('Unexpected write'),
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eth_receive_panel_error')), findsOneWidget);
    expect(find.byKey(const Key('eth_receive_panel_ready_state')),
        findsNothing);
  });

  testWidgets('a vault lock after V2 readback cannot publish receive address',
      (tester) async {
    var current = true;
    final identity = WalletV2Identity(
      recordId: recordId, chain: 'evm', network: 'ethereum_sepolia',
      asset: 'ETH', publicAddress: address, label: label,
    );
    final wallet = _StaleAfterReadWallet(
      identity: identity,
      current: () => current,
      expire: () => current = false,
    );
    final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => current,
      ),
    )));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(current, isFalse);
    expect(find.text(address), findsNothing);
    expect(find.byKey(const Key('eth_receive_panel_ready_state')),
        findsNothing);
  });

  testWidgets('V2 receive rejects a backend identity mismatch',
      (tester) async {
    final api = _ReceiveOnlyClient({
      'wallet_engine': 'receive_ready', 'publicAddress': address,
      'walletRecordId': 'different-wallet-record-id',
      'backupStatus': 'wallet_v2_encrypted',
    });
    final wallet = walletClient(
      get: (_) async => {'wallets': [
        {
          'wallet_record_id': recordId, 'chain': 'evm',
          'network': 'ethereum_sepolia', 'asset': 'ETH',
          'public_address': address, 'wallet_label': label,
          'migration_state': 'v2_verified',
        },
      ]},
      post: (_, __) async => throw StateError('Unexpected write'),
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eth_receive_panel_error')), findsOneWidget);
    expect(find.textContaining('Wallet account verification failed'),
        findsOneWidget);
    expect(api.legacyCreates, 0);
  });

  testWidgets('legacy address is marked as needing migration in V2 mode',
      (tester) async {
    final api = _ReceiveOnlyClient({
      'wallet_engine': 'receive_ready', 'publicAddress': address,
      'walletLabel': label, 'backupStatus': 'encrypted_backup_saved',
    });
    final wallet = walletClient(
      get: (_) async => {'wallets': <Object>[]},
      post: (_, __) async => throw StateError('Unexpected write'),
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eth_receive_panel_migration_warning')),
        findsOneWidget);
    expect(find.text(kEthReceiveLegacyMigrationWarning), findsOneWidget);
    expect(find.byKey(const Key('eth_receive_panel_qr')), findsNothing);
    expect(find.byKey(const Key('eth_receive_panel_address_text')),
        findsNothing);
  });

  testWidgets('V2 creation uses staged ciphertext and no legacy write',
      (tester) async {
    final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
    Map<String, dynamic>? staged;
    var verified = false;
    final wallet = walletClient(
      creationEnabled: true,
      get: (path) async {
        if (path == '/vault/wallet-v2/pending') {
          return {'wallets': <Object>[]};
        }
        if (path == '/vault/wallet-v2') return {'wallets': verified ? [
          {
            'wallet_record_id': recordId, 'chain': 'evm',
            'network': 'ethereum_sepolia', 'asset': 'ETH',
            'public_address': staged!['public_address'],
            'wallet_label': staged!['wallet_label'],
            'migration_state': 'v2_verified',
          },
        ] : <Object>[]};
        return {
          ...staged!, 'migration_state': verified
              ? 'v2_verified' : 'migration_pending',
          'legacy_item_id': null, 'readback_receipt': 'synthetic-receipt',
        };
      },
      post: (path, body) async {
        if (path == '/vault/wallet-v2') {
          staged = body;
          expect(body, isNot(contains('pin')));
          expect(body['payload_ciphertext'], isA<String>());
          return {'wallet_record_id': recordId,
                  'migration_state': 'migration_pending'};
        }
        expect(path, '/vault/wallet-v2/$recordId/publish-new');
        expect(body['readback_receipt'], 'synthetic-receipt');
        verified = true;
        return {'wallet_record_id': recordId,
                'migration_state': 'v2_verified'};
      },
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.pumpAndSettle();
    expect(verified, isTrue);
    expect(find.byKey(const Key('eth_receive_panel_ready_state')),
        findsOneWidget);
    expect(api.legacyCreates, 0);
  });

  testWidgets('create button resumes pending V2 wallet before new generation',
      (tester) async {
    const secret =
        '0000000000000000000000000000000000000000000000000000000000000001';
    final resumedAddress = deriveEthereumAddressFromPrivateKeyHex(secret);
    final codec = WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 6)));
    final identity = WalletV2Identity(
      recordId: recordId, chain: 'evm', network: 'ethereum_sepolia',
      asset: 'ETH', publicAddress: resumedAddress, label: label,
    );
    final ciphertext = await codec.wrap(identity, secret);
    final pending = {
      'wallet_record_id': recordId, 'chain': 'evm',
      'network': 'ethereum_sepolia', 'asset': 'ETH',
      'public_address': resumedAddress, 'wallet_label': label,
      'migration_state': 'migration_pending', 'legacy_item_id': null,
      'legacy_source_snapshot': null,
    };
    var verified = false;
    var publishCalls = 0;
    final wallet = walletClient(
      creationEnabled: true,
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': verified
            ? [{...pending, 'migration_state': 'v2_verified'}]
            : <Object>[]};
        if (path == '/vault/wallet-v2/pending') return {'wallets': verified
            ? <Object>[] : [pending]};
        expect(path, '/vault/wallet-v2/$recordId');
        return {
          ...pending, 'migration_state': verified
              ? 'v2_verified' : 'migration_pending',
          'envelope_version': 'v2', 'payload_ciphertext': ciphertext,
          'readback_receipt': 'synthetic-fresh-receipt',
        };
      },
      post: (path, body) async {
        expect(path, '/vault/wallet-v2/$recordId/publish-new');
        expect(body['readback_receipt'], 'synthetic-fresh-receipt');
        publishCalls++;
        verified = true;
        return {'wallet_record_id': recordId,
                'migration_state': 'v2_verified'};
      },
    );
    final api = _ReceiveOnlyClient({'wallet_engine': 'no_account'});
    await tester.pumpWidget(MaterialApp(home: Scaffold(body:
      CryptoWalletEngineReceivePanel(
        authToken: 'synthetic-token', client: api,
        walletV2: wallet,
        encryptForVault: (_) async => throw StateError('Legacy encryption'),
        isVaultKeyAvailable: () => true,
      ),
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eth_receive_panel_create_btn')));
    await tester.pumpAndSettle();
    expect(publishCalls, 1);
    expect(find.text(resumedAddress), findsOneWidget);
    expect(api.legacyCreates, 0);
  });
}
