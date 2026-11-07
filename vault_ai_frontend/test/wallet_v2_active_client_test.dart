import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/ethereum_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';

void main() {
  const secret =
      '0000000000000000000000000000000000000000000000000000000000000001';
  const slot = WalletV2AccountSlot('evm', 'ethereum_mainnet', 'ETH');
  final address = deriveEthereumAddressFromPrivateKeyHex(secret);
  const id = 'synthetic-new-wallet-record-1';

  test('new wallet stages and publishes only after local exact readback',
      () async {
    final posts = <String>[];
    var state = '';
    Map<String, dynamic>? staged;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
      accessIsCurrent: () => true,
      creationEnabled: true,
      newRecordId: () => id,
      post: (path, body) async {
        posts.add(path);
        expect(jsonEncode(body), isNot(contains(secret)));
        expect(body, isNot(containsPair('pin', '123456')));
        if (path == '/vault/wallet-v2') {
          staged = body;
          state = 'migration_pending';
          return {'wallet_record_id': id, 'migration_state': state};
        }
        expect(path, '/vault/wallet-v2/$id/publish-new');
        expect(body['readback_receipt'], 'synthetic-receipt');
        expect(body['client_verified_exact_bytes'], true);
        state = 'v2_verified';
        return {'wallet_record_id': id, 'migration_state': state};
      },
      get: (path) async {
        if (path == '/vault/wallet-v2/pending') {
          return {'wallets': <Object>[]};
        }
        if (path == '/vault/wallet-v2') {
          return {'wallets': state == 'v2_verified' ? [
            {
              'wallet_record_id': id, 'chain': 'evm',
              'network': 'ethereum_mainnet', 'asset': 'ETH',
              'public_address': address, 'wallet_label': 'Synthetic wallet',
              'migration_state': state,
            },
          ] : <Object>[]};
        }
        expect(path, '/vault/wallet-v2/$id');
        return {
          ...staged!, 'migration_state': state,
          'legacy_item_id': null, 'readback_receipt': 'synthetic-receipt',
        };
      },
    );
    final created = await client.createNew(
      slot: slot, publicAddress: address, label: 'Synthetic wallet',
      secret: secret,
    );
    expect(created.recordId, id);
    expect(posts, [
      '/vault/wallet-v2', '/vault/wallet-v2/$id/publish-new',
    ]);
    expect((await client.findVerified(slot))!.publicAddress, address);
    expect(await client.readSigningSecret(created), secret);
  });

  test('bad address and changed ciphertext never publish', () async {
    final posts = <String>[];
    Map<String, dynamic>? staged;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
      accessIsCurrent: () => true,
      creationEnabled: true,
      newRecordId: () => id,
      post: (path, body) async {
        posts.add(path);
        staged = body;
        return {'wallet_record_id': id, 'migration_state': 'migration_pending'};
      },
      get: (path) async =>
          path == '/vault/wallet-v2' || path == '/vault/wallet-v2/pending'
          ? {'wallets': <Object>[]}
          : {
              ...staged!, 'payload_ciphertext': 'changed',
              'readback_receipt': 'synthetic-receipt',
            },
    );
    await expectLater(
      client.createNew(slot: slot,
          publicAddress: '0x0000000000000000000000000000000000000002',
          label: 'Synthetic wallet', secret: secret),
      throwsFormatException,
    );
    expect(posts, isEmpty);
    await expectLater(
      client.createNew(slot: slot, publicAddress: address,
          label: 'Synthetic wallet', secret: secret),
      throwsFormatException,
    );
    expect(posts, ['/vault/wallet-v2']);
  });

  test('session loss during readback prevents publish', () async {
    var current = true;
    final posts = <String>[];
    Map<String, dynamic>? staged;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
      accessIsCurrent: () => current,
      creationEnabled: true,
      newRecordId: () => id,
      post: (path, body) async {
        posts.add(path);
        staged = body;
        return {'wallet_record_id': id, 'migration_state': 'migration_pending'};
      },
      get: (path) async {
        if (path == '/vault/wallet-v2' ||
            path == '/vault/wallet-v2/pending') {
          return {'wallets': <Object>[]};
        }
        current = false;
        return {...staged!, 'readback_receipt': 'synthetic-receipt'};
      },
    );
    await expectLater(
      client.createNew(slot: slot, publicAddress: address,
          label: 'Synthetic wallet', secret: secret),
      throwsStateError,
    );
    expect(posts, ['/vault/wallet-v2']);
  });

  test('only canonical supported account slots are accepted', () {
    expect(() => const WalletV2AccountSlot('evm', 'ethereum_mainnet', 'ETH')
        .validate(), returnsNormally);
    expect(() => const WalletV2AccountSlot('evm', 'ethereum-mainnet', 'ETH')
        .validate(), throwsFormatException);
    expect(() => const WalletV2AccountSlot('tron', 'tron_mainnet', 'ETH')
        .validate(), throwsFormatException);
  });

  test('new-wallet creation is disabled by default', () async {
    var sent = false;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
      accessIsCurrent: () => true,
      post: (_, __) async { sent = true; return {}; },
      get: (_) async { sent = true; return {}; },
    );
    await expectLater(
      client.createNew(slot: slot, publicAddress: address,
          label: 'Synthetic wallet', secret: secret),
      throwsStateError,
    );
    expect(sent, isFalse);
  });

  test('signing secret is bound to the displayed verified address', () async {
    final codec = WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9)));
    final identity = WalletV2Identity(
      recordId: id, chain: 'evm', network: 'ethereum_mainnet', asset: 'ETH',
      publicAddress: address, label: 'Synthetic wallet',
    );
    final ciphertext = await codec.wrap(identity, secret);
    var detailReads = 0;
    final client = WalletV2ActiveClient(
      codec: codec,
      accessIsCurrent: () => true,
      post: (_, __) async => throw StateError('Unexpected write'),
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': [
          {
            'wallet_record_id': id, 'chain': 'evm',
            'network': 'ethereum_mainnet', 'asset': 'ETH',
            'public_address': address, 'wallet_label': 'Synthetic wallet',
            'migration_state': 'v2_verified',
          }
        ]};
        detailReads++;
        return {
          'wallet_record_id': id, 'chain': 'evm',
          'network': 'ethereum_mainnet', 'asset': 'ETH',
          'public_address': address, 'wallet_label': 'Synthetic wallet',
          'migration_state': 'v2_verified', 'envelope_version': 'v2',
          'payload_ciphertext': ciphertext,
        };
      },
    );
    await expectLater(
      client.readSigningSecretForAddress(
        slot, '0x0000000000000000000000000000000000000002'),
      throwsFormatException,
    );
    expect(detailReads, 0);
    expect(await client.readSigningSecretForAddress(slot, address), secret);
    expect(detailReads, 1);
  });

  test('non-EVM addresses retain case-sensitive identity', () async {
    var detailReads = 0;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
      accessIsCurrent: () => true,
      post: (_, __) async => throw StateError('Unexpected write'),
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': [
          {
            'wallet_record_id': id, 'chain': 'solana',
            'network': 'solana_mainnet', 'asset': 'SOL',
            'public_address': 'AbCd', 'wallet_label': 'Synthetic wallet',
            'migration_state': 'v2_verified',
          },
        ]};
        detailReads++;
        throw StateError('Unexpected detail read');
      },
    );
    await expectLater(
      client.readSigningSecretForAddress(
        const WalletV2AccountSlot('solana', 'solana_mainnet', 'SOL'), 'abcd'),
      throwsFormatException,
    );
    expect(detailReads, 0);
  });

  test('session loss during secret fetch never returns a signing key', () async {
    var current = true;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
      accessIsCurrent: () => current,
      post: (_, __) async => throw StateError('Unexpected write'),
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': [
          {
            'wallet_record_id': id, 'chain': 'evm',
            'network': 'ethereum_mainnet', 'asset': 'ETH',
            'public_address': address, 'wallet_label': 'Synthetic wallet',
            'migration_state': 'v2_verified',
          },
        ]};
        current = false;
        return {'wallet_record_id': id};
      },
    );
    await expectLater(
      client.readSigningSecretForAddress(slot, address), throwsStateError,
    );
  });

  test('interrupted new wallet resumes the exact pending secret', () async {
    final codec = WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 4)));
    final identity = WalletV2Identity(
      recordId: id, chain: 'evm', network: 'ethereum_mainnet',
      asset: 'ETH', publicAddress: address, label: 'Synthetic wallet',
    );
    final ciphertext = await codec.wrap(identity, secret);
    var verified = false;
    var newIds = 0;
    final posts = <String>[];
    final metadata = {
      'wallet_record_id': id, 'chain': 'evm',
      'network': 'ethereum_mainnet', 'asset': 'ETH',
      'public_address': address, 'wallet_label': 'Synthetic wallet',
      'migration_state': 'migration_pending',
      'legacy_item_id': null, 'legacy_source_snapshot': null,
    };
    final client = WalletV2ActiveClient(
      codec: codec, accessIsCurrent: () => true, creationEnabled: true,
      newRecordId: () { newIds++; return 'unexpected-new-record-id'; },
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': verified
            ? [{...metadata, 'migration_state': 'v2_verified'}]
            : <Object>[]};
        if (path == '/vault/wallet-v2/pending') return {'wallets': verified
            ? <Object>[] : [metadata]};
        expect(path, '/vault/wallet-v2/$id');
        return {
          ...metadata, 'migration_state': verified
              ? 'v2_verified' : 'migration_pending',
          'envelope_version': 'v2', 'payload_ciphertext': ciphertext,
          'readback_receipt': 'fresh-synthetic-receipt',
        };
      },
      post: (path, body) async {
        posts.add(path);
        expect(path, '/vault/wallet-v2/$id/publish-new');
        expect(body['readback_receipt'], 'fresh-synthetic-receipt');
        verified = true;
        return {'wallet_record_id': id, 'migration_state': 'v2_verified'};
      },
    );
    final recovered = await client.recoverPendingNew(slot);
    expect(recovered!.recordId, id);
    expect(newIds, 0);
    expect(posts, ['/vault/wallet-v2/$id/publish-new']);
    expect(await client.readSigningSecret(recovered), secret);
    expect((await client.recoverPendingNew(slot))!.recordId, id);
    expect(posts, ['/vault/wallet-v2/$id/publish-new']);
  });

  test('corrupt pending wallet blocks fresh creation without deleting it',
      () async {
    var posts = 0;
    var newIds = 0;
    final pending = {
      'wallet_record_id': id, 'chain': 'evm',
      'network': 'ethereum_mainnet', 'asset': 'ETH',
      'public_address': address, 'wallet_label': 'Synthetic wallet',
      'migration_state': 'migration_pending',
      'legacy_item_id': null, 'legacy_source_snapshot': null,
    };
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 4))),
      accessIsCurrent: () => true, creationEnabled: true,
      newRecordId: () { newIds++; return 'unexpected-new-record-id'; },
      get: (path) async {
        if (path == '/vault/wallet-v2') return {'wallets': <Object>[]};
        if (path == '/vault/wallet-v2/pending') return {'wallets': [pending]};
        return {
          ...pending, 'envelope_version': 'v2',
          'payload_ciphertext': 'corrupt-ciphertext',
          'readback_receipt': 'fresh-synthetic-receipt',
        };
      },
      post: (_, __) async { posts++; return {}; },
    );
    await expectLater(client.recoverPendingNew(slot), throwsA(isA<Exception>()));
    await expectLater(
      client.createNew(slot: slot, publicAddress: address,
          label: 'Synthetic wallet', secret: secret),
      throwsA(isA<WalletV2PendingStageError>()),
    );
    expect(posts, 0);
    expect(newIds, 0);
  });

  test('a pending legacy migration cannot be published as a new wallet',
      () async {
    var posts = 0;
    final client = WalletV2ActiveClient(
      codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 4))),
      accessIsCurrent: () => true, creationEnabled: true,
      get: (path) async => path == '/vault/wallet-v2'
          ? {'wallets': <Object>[]}
          : {'wallets': [
              {
                'wallet_record_id': id, 'chain': 'evm',
                'network': 'ethereum_mainnet', 'asset': 'ETH',
                'public_address': address, 'wallet_label': 'Synthetic wallet',
                'migration_state': 'migration_pending',
                'legacy_item_id': 42,
                'legacy_source_snapshot': List.filled(43, 'x').join(),
              },
            ]},
      post: (_, __) async { posts++; return {}; },
    );
    await expectLater(
      client.recoverPendingNew(slot),
      throwsA(isA<WalletV2PendingStageError>()),
    );
    expect(posts, 0);
  });
}
