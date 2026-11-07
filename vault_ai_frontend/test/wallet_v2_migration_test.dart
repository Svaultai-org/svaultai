import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';

const identity = WalletV2Identity(
  recordId: 'synthetic-wallet-record-1',
  chain: 'evm',
  network: 'ethereum_mainnet',
  asset: 'ETH',
  publicAddress: '0x0000000000000000000000000000000000000001',
  label: 'Synthetic wallet',
);
final legacyTestKey = SecretKey(List<int>.filled(32, 9));
final legacyAes = AesGcm.with256bits();

Future<String> encryptLegacy(String plaintext) async {
  final nonce = List<int>.generate(12, (i) => i + 1);
  final box = await legacyAes.encrypt(
    utf8.encode(plaintext),
    secretKey: legacyTestKey,
    nonce: nonce,
  );
  return base64.encode([...nonce, ...box.cipherText, ...box.mac.bytes]);
}

Future<String> decryptLegacy(String ciphertext) async {
  final bytes = base64.decode(ciphertext);
  final box = SecretBox(
    bytes.sublist(12, bytes.length - 16),
    nonce: bytes.sublist(0, 12),
    mac: Mac(bytes.sublist(bytes.length - 16)),
  );
  return utf8.decode(await legacyAes.decrypt(box, secretKey: legacyTestKey));
}

Future<LegacyCiphertextSource> walletEngineSource() async {
  final inner = await encryptLegacy('synthetic-private-key');
  final outer = jsonEncode({
    'schema': 'crypto_wallet_account_v1',
    'asset': identity.asset,
    'network': 'Ethereum Mainnet',
    'publicAddress': identity.publicAddress,
    'walletLabel': identity.label,
    'encryptedWalletSecret': inner,
    'backupStatus': 'encrypted_backup_saved',
    'scannerMode': 'synthetic_scan_mode',
    'restoreHeight': 123,
  });
  return LegacyCiphertextSource(
    ciphertext: outer,
    sourceSnapshot: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    sourceMetadata: const {'item_type': 'crypto_wallet_account'},
  );
}

Future<LegacyCiphertextSource> encryptedSource() async {
  final engine = await walletEngineSource();
  return LegacyCiphertextSource(
    ciphertext: await encryptLegacy(engine.ciphertext),
    sourceSnapshot: engine.sourceSnapshot,
    sourceMetadata: engine.sourceMetadata,
  );
}

void main() {
  final codec = WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7)));

  test('MVK envelope binds the wallet identity and secret locally', () async {
    final ct = await codec.wrap(identity, 'synthetic-private-key');
    expect(ct, isNot(contains('synthetic-private-key')));
    expect((await codec.unwrap(identity, ct)).secret, 'synthetic-private-key');
    await expectLater(
      codec.unwrap(
          const WalletV2Identity(
            recordId: 'synthetic-wallet-record-1',
            chain: 'evm',
            network: 'ethereum_mainnet',
            asset: 'ETH',
            publicAddress: '0x0000000000000000000000000000000000000002',
            label: 'Synthetic wallet',
          ),
          ct),
      throwsFormatException,
    );
    await expectLater(
      WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 8)))
          .unwrap(identity, ct),
      throwsA(isA<Exception>()),
    );
  });

  test('owner migration stages, verifies exact GET, then retires by proof',
      () async {
    final source = await walletEngineSource();
    final calls = <String>[];
    Map<String, dynamic>? staged;
    final client = WalletV2MigrationClient(
      codec: codec,
      accessIsCurrent: () => true,
      decryptLegacyItem: (_) async => throw StateError(
        'wallet-engine outer JSON must not be decrypted as ciphertext',
      ),
      decryptLegacySecret: decryptLegacy,
      secretMatchesAddress: (secret, address) async =>
          secret == 'synthetic-private-key' &&
          address == identity.publicAddress,
      proofProvider: () async {
        calls.add('proof');
        return 'synthetic-opaque-proof';
      },
      post: (path, body) async {
        calls.add(path);
        final wire = jsonEncode(body);
        expect(wire, isNot(contains('synthetic-private-key')));
        expect(wire, isNot(contains(source.ciphertext)));
        expect(wire, isNot(contains('"pin"')));
        if (path.endsWith('/stage')) {
          staged = body;
          return {
            'wallet_record_id': identity.recordId,
            'migration_state': 'migration_pending'
          };
        }
        expect(calls, contains('/vault/wallet-v2/${identity.recordId}'));
        expect(body['readback_receipt'], 'synthetic-readback-receipt');
        expect(body['zk_proof_token'], 'synthetic-opaque-proof');
        return {'wallet_record_id': identity.recordId, 'retired': true};
      },
      get: (path) async {
        calls.add(path);
        if (path == '/vault/wallet-v2/pending') {
          return {'wallets': <Object>[]};
        }
        expect(staged, isNotNull);
        return {
          'wallet_record_id': identity.recordId,
          'migration_state': 'migration_pending',
          'envelope_version': 'v2',
          'chain': identity.chain,
          'network': identity.network,
          'asset': identity.asset,
          'public_address': identity.publicAddress,
          'wallet_label': identity.label,
          'legacy_item_id': 42,
          'legacy_source_snapshot': source.sourceSnapshot,
          'payload_ciphertext': staged!['payload_ciphertext'],
          'readback_receipt': 'synthetic-readback-receipt',
        };
      },
    );
    expect(
        await client.migrateLegacy(
          legacyItemId: 42,
          source: source,
          identity: identity,
        ),
        identity.recordId);
    expect(calls, [
      '/vault/wallet-v2/pending',
      '/vault/wallet-v2/migrate/stage',
      '/vault/wallet-v2/${identity.recordId}',
      'proof',
      '/vault/wallet-v2/migrate/retire',
    ]);
    final decoded = await codec.unwrap(
      identity,
      staged!['payload_ciphertext'] as String,
    );
    expect(decoded.secret, 'synthetic-private-key');
    expect(decoded.legacyRecord['backupStatus'], 'encrypted_backup_saved');
    expect(decoded.legacyRecord['scannerMode'], 'synthetic_scan_mode');
    expect(decoded.legacyRecord['restoreHeight'], 123);
    expect(decoded.legacyRecord, isNot(contains('encryptedWalletSecret')));
  });

  test('mismatched readback keeps source and does not request a retire proof',
      () async {
    final source = await encryptedSource();
    var proofCalls = 0;
    var retireCalls = 0;
    final client = WalletV2MigrationClient(
      codec: codec,
      accessIsCurrent: () => true,
      decryptLegacyItem: decryptLegacy,
      decryptLegacySecret: decryptLegacy,
      secretMatchesAddress: (_, __) async => true,
      proofProvider: () async {
        proofCalls++;
        return 'proof';
      },
      post: (path, body) async {
        if (path.endsWith('/retire')) retireCalls++;
        return {
          'wallet_record_id': identity.recordId,
          'migration_state': 'migration_pending'
        };
      },
      get: (path) async => path == '/vault/wallet-v2/pending'
          ? {'wallets': <Object>[]}
          : {
        'wallet_record_id': identity.recordId,
        'migration_state': 'migration_pending',
        'envelope_version': 'v2',
        'chain': identity.chain,
        'network': identity.network,
        'asset': identity.asset,
        'public_address': identity.publicAddress,
        'wallet_label': identity.label,
        'legacy_item_id': 42,
        'legacy_source_snapshot': source.sourceSnapshot,
        'payload_ciphertext': 'different-ciphertext',
        'readback_receipt': 'receipt',
      },
    );
    await expectLater(
        client.migrateLegacy(
          legacyItemId: 42,
          source: source,
          identity: identity,
        ),
        throwsFormatException);
    expect(proofCalls, 0);
    expect(retireCalls, 0);
  });

  test('interrupted legacy migration resumes original stage and fresh proof',
      () async {
    final source = await walletEngineSource();
    final preserved = Map<String, dynamic>.from(
      jsonDecode(source.ciphertext) as Map<String, dynamic>,
    )..remove('encryptedWalletSecret');
    final ciphertext = await codec.wrap(
      identity, 'synthetic-private-key', legacyRecord: preserved,
    );
    const retryIdentity = WalletV2Identity(
      recordId: 'synthetic-retry-wallet-record-2',
      chain: 'evm', network: 'ethereum_mainnet', asset: 'ETH',
      publicAddress: '0x0000000000000000000000000000000000000001',
      label: 'Synthetic wallet',
    );
    var stageCalls = 0;
    var retireCalls = 0;
    var proofCalls = 0;
    final client = WalletV2MigrationClient(
      codec: codec, accessIsCurrent: () => true,
      decryptLegacyItem: (_) async => throw StateError('Not needed'),
      decryptLegacySecret: decryptLegacy,
      secretMatchesAddress: (secret, address) async =>
          secret == 'synthetic-private-key' &&
          address == identity.publicAddress,
      proofProvider: () async { proofCalls++; return 'fresh-opaque-proof'; },
      get: (path) async {
        if (path == '/vault/wallet-v2/pending') return {'wallets': [
          {
            'wallet_record_id': identity.recordId, 'chain': identity.chain,
            'network': identity.network, 'asset': identity.asset,
            'public_address': identity.publicAddress,
            'wallet_label': identity.label,
            'migration_state': 'migration_pending',
            'legacy_item_id': 42,
            'legacy_source_snapshot': source.sourceSnapshot,
          },
        ]};
        expect(path, '/vault/wallet-v2/${identity.recordId}');
        return {
          'wallet_record_id': identity.recordId, 'chain': identity.chain,
          'network': identity.network, 'asset': identity.asset,
          'public_address': identity.publicAddress,
          'wallet_label': identity.label,
          'migration_state': 'migration_pending',
          'legacy_item_id': 42,
          'legacy_source_snapshot': source.sourceSnapshot,
          'envelope_version': 'v2',
          'payload_ciphertext': ciphertext,
          'readback_receipt': 'fresh-session-receipt',
        };
      },
      post: (path, body) async {
        if (path.endsWith('/stage')) {
          stageCalls++;
          throw StateError('Must reuse old ciphertext');
        }
        retireCalls++;
        expect(path, '/vault/wallet-v2/migrate/retire');
        expect(body['wallet_record_id'], identity.recordId);
        expect(body['readback_receipt'], 'fresh-session-receipt');
        expect(body['zk_proof_token'], 'fresh-opaque-proof');
        return {'wallet_record_id': identity.recordId, 'retired': true};
      },
    );
    expect(await client.migrateLegacy(
      legacyItemId: 42, source: source, identity: retryIdentity,
    ), identity.recordId);
    expect(stageCalls, 0);
    expect(retireCalls, 1);
    expect(proofCalls, 1);
  });

  test('changed legacy source refreshes only the same pending record ID',
      () async {
    final original = await walletEngineSource();
    final source = LegacyCiphertextSource(
      ciphertext: original.ciphertext,
      sourceSnapshot: 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB',
      sourceMetadata: original.sourceMetadata,
    );
    const retryIdentity = WalletV2Identity(
      recordId: 'synthetic-retry-wallet-record-2',
      chain: 'evm', network: 'ethereum_mainnet', asset: 'ETH',
      publicAddress: '0x0000000000000000000000000000000000000001',
      label: 'Synthetic wallet',
    );
    Map<String, dynamic>? staged;
    var proofCalls = 0;
    final client = WalletV2MigrationClient(
      codec: codec, accessIsCurrent: () => true,
      decryptLegacyItem: (_) async => throw StateError('Not needed'),
      decryptLegacySecret: decryptLegacy,
      secretMatchesAddress: (secret, address) async =>
          secret == 'synthetic-private-key' &&
          address == identity.publicAddress,
      proofProvider: () async { proofCalls++; return 'fresh-opaque-proof'; },
      get: (path) async {
        if (path == '/vault/wallet-v2/pending') return {'wallets': [
          {
            'wallet_record_id': identity.recordId, 'chain': identity.chain,
            'network': identity.network, 'asset': identity.asset,
            'public_address': identity.publicAddress,
            'wallet_label': identity.label,
            'migration_state': 'migration_pending',
            'legacy_item_id': 42,
            'legacy_source_snapshot': original.sourceSnapshot,
          },
        ]};
        expect(path, '/vault/wallet-v2/${identity.recordId}');
        return {
          ...staged!, 'migration_state': 'migration_pending',
          'legacy_source_snapshot': source.sourceSnapshot,
          'legacy_item_id': 42,
          'readback_receipt': 'fresh-session-receipt',
        };
      },
      post: (path, body) async {
        if (path.endsWith('/stage')) {
          staged = body;
          expect(body['wallet_record_id'], identity.recordId);
          expect(body['source_snapshot'], source.sourceSnapshot);
          return {'wallet_record_id': identity.recordId,
                  'migration_state': 'migration_pending'};
        }
        expect(path, '/vault/wallet-v2/migrate/retire');
        expect(body['wallet_record_id'], identity.recordId);
        return {'wallet_record_id': identity.recordId, 'retired': true};
      },
    );
    expect(await client.migrateLegacy(
      legacyItemId: 42, source: source, identity: retryIdentity,
    ), identity.recordId);
    expect(staged, isNotNull);
    expect(proofCalls, 1);
  });

  test('invalid legacy secret never reaches wallet staging', () async {
    final source = await encryptedSource();
    var requests = 0;
    final client = WalletV2MigrationClient(
      codec: codec,
      accessIsCurrent: () => true,
      decryptLegacyItem: decryptLegacy,
      decryptLegacySecret: (_) async => 'synthetic-wrong-key',
      secretMatchesAddress: (_, __) async => false,
      proofProvider: () async => throw StateError('must not request proof'),
      post: (_, __) async {
        requests++;
        return const {};
      },
      get: (_) async {
        requests++;
        return const {};
      },
    );
    await expectLater(
      client.migrateLegacy(
        legacyItemId: 42,
        source: source,
        identity: identity,
      ),
      throwsFormatException,
    );
    expect(requests, 0);
  });

  test('read adapter opens only verified matching V2 records', () async {
    final ciphertext = await codec.wrap(identity, 'synthetic-private-key');
    var state = 'migration_pending';
    final client = WalletV2MigrationClient(
      codec: codec,
      accessIsCurrent: () => true,
      decryptLegacyItem: (_) async => throw StateError('not migrating'),
      decryptLegacySecret: (_) async => throw StateError('not migrating'),
      secretMatchesAddress: (secret, address) async =>
          secret == 'synthetic-private-key' &&
          address == identity.publicAddress,
      proofProvider: () async => throw StateError('read uses no proof'),
      post: (_, __) async => throw StateError('read uses no write'),
      get: (_) async => {
        'wallet_record_id': identity.recordId,
        'chain': identity.chain,
        'network': identity.network,
        'asset': identity.asset,
        'public_address': identity.publicAddress,
        'wallet_label': identity.label,
        'envelope_version': 'v2',
        'migration_state': state,
        'payload_ciphertext': ciphertext,
      },
    );
    await expectLater(client.readVerified(identity), throwsFormatException);
    state = 'v2_verified';
    expect(
        (await client.readVerified(identity)).secret, 'synthetic-private-key');
  });
}
