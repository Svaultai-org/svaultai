import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/services/wallet_v2_owner_upgrade.dart';

const _recordId = 'synthetic-wallet-record-1';
const _address = '0x0000000000000000000000000000000000000001';
const _snapshot = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

class _Export extends LegacyCiphertextExportClient {
  _Export(this.source)
      : super(
          post: (_, __) async => throw StateError('Unexpected export call'),
          proofProvider: () async => 'synthetic-export-proof',
        );

  final LegacyCiphertextSource source;
  int reads = 0;

  @override
  Future<List<Map<String, dynamic>>> listItemsBounded({
    required int maxRecords,
  }) async =>
      [
        {'item_id': 1, 'item_type': 'note', 'ciphertext_chars': 100},
        {
          'item_id': 42,
          'item_type': 'crypto_wallet_account',
          'ciphertext_chars': source.ciphertext.length,
        },
      ];

  @override
  Future<LegacyCiphertextSource> readItemSource({
    required int itemId,
    required int ciphertextChars,
  }) async {
    expect(itemId, 42);
    expect(ciphertextChars, source.ciphertext.length);
    reads++;
    return source;
  }
}

class _Server {
  _Server({this.corruptReadback = false});

  final bool corruptReadback;
  final calls = <String>[];
  Map<String, dynamic>? stage;
  bool sourcePresent = true;
  bool verified = false;

  Future<Map<String, dynamic>> post(
      String path, Map<String, dynamic> body) async {
    calls.add(path);
    final wire = jsonEncode(body);
    expect(wire, isNot(contains('synthetic-private-key')));
    expect(wire, isNot(contains('raw_pin')));
    if (path == '/vault/wallet-v2/migrate/stage') {
      expect(sourcePresent, isTrue);
      stage = Map<String, dynamic>.from(body);
      return {
        'wallet_record_id': _recordId,
        'migration_state': 'migration_pending'
      };
    }
    if (path == '/vault/wallet-v2/migrate/retire') {
      expect(sourcePresent, isTrue);
      expect(stage, isNotNull);
      expect(body['zk_proof_token'], 'synthetic-action-proof');
      expect(body['readback_receipt'], 'synthetic-receipt');
      sourcePresent = false;
      verified = true;
      return {'wallet_record_id': _recordId, 'retired': true};
    }
    throw StateError('Unexpected wallet write');
  }

  Future<Map<String, dynamic>> get(String path) async {
    calls.add(path);
    if (path == '/vault/wallet-v2') {
      return {
        'wallets': verified
            ? [
                {
                  'wallet_record_id': _recordId,
                  'chain': 'evm',
                  'network': 'ethereum_mainnet',
                  'asset': 'ETH',
                  'public_address': _address,
                  'wallet_label': 'Synthetic wallet',
                  'migration_state': 'v2_verified',
                }
              ]
            : <Object>[],
      };
    }
    if (path == '/vault/wallet-v2/pending') {
      return {'wallets': <Object>[]};
    }
    if (path == '/vault/wallet-v2/$_recordId') {
      expect(stage, isNotNull);
      return {
        'wallet_record_id': _recordId,
        'chain': 'evm',
        'network': 'ethereum_mainnet',
        'asset': 'ETH',
        'public_address': _address,
        'wallet_label': 'Synthetic wallet',
        'payload_ciphertext': corruptReadback
            ? 'changed-ciphertext'
            : stage!['payload_ciphertext'],
        'envelope_version': 'v2',
        'migration_state': verified ? 'v2_verified' : 'migration_pending',
        'legacy_item_id': verified ? null : 42,
        'legacy_source_snapshot': verified ? null : _snapshot,
        'readback_receipt': verified ? null : 'synthetic-receipt',
      };
    }
    throw StateError('Unexpected wallet read');
  }
}

Future<String> _encryptLegacy(String plaintext, SecretKey key) async {
  final aes = AesGcm.with256bits();
  final nonce = List<int>.generate(12, (i) => i + 1);
  final box =
      await aes.encrypt(utf8.encode(plaintext), secretKey: key, nonce: nonce);
  return base64.encode([...nonce, ...box.cipherText, ...box.mac.bytes]);
}

Future<({WalletV2OwnerUpgrade upgrade, _Export export, _Server server})> _setup(
    {bool corruptReadback = false}) async {
  final legacyKey = SecretKey(List<int>.filled(32, 9));
  final mvk = SecretKey(List<int>.filled(32, 7));
  final secret = await _encryptLegacy('synthetic-private-key', legacyKey);
  final source = LegacyCiphertextSource(
    ciphertext: jsonEncode({
      'schema': 'crypto_wallet_account_v1',
      'asset': 'ETH',
      'network': 'Ethereum Mainnet',
      'publicAddress': _address,
      'walletLabel': 'Synthetic wallet',
      'encryptedWalletSecret': secret,
      'backupStatus': 'encrypted_backup_saved',
    }),
    sourceSnapshot: _snapshot,
    sourceMetadata: const {'item_type': 'crypto_wallet_account'},
  );
  final export = _Export(source);
  final server = _Server(corruptReadback: corruptReadback);
  final wallet = WalletV2ActiveClient(
    codec: WalletV2EnvelopeCodec(mvk),
    post: server.post,
    get: server.get,
    accessIsCurrent: () => true,
    secretMatchesAddress: (chain, key, address) async =>
        chain == 'evm' && key == 'synthetic-private-key' && address == _address,
    newRecordId: () => _recordId,
  );
  return (
    upgrade: WalletV2OwnerUpgrade(
      export: export,
      legacyCodec:
          LegacyCiphertextMigrationCodec(legacyKey: legacyKey, mvk: mvk),
      wallet: wallet,
      proofProvider: () async {
        expect(server.sourcePresent, isTrue);
        return 'synthetic-action-proof';
      },
      accessIsCurrent: () => true,
    ),
    export: export,
    server: server,
  );
}

void main() {
  test('owner upgrade reads only wallet items and verifies V2 after retire',
      () async {
    final fixture = await _setup();
    final result = await fixture.upgrade.run();
    expect(result.migrated, 1);
    expect(result.inspected, 1);
    expect(fixture.export.reads, 1);
    expect(fixture.server.sourcePresent, isFalse);
    expect(fixture.server.verified, isTrue);
    expect(
        fixture.server.calls.indexOf('/vault/wallet-v2/$_recordId'),
        lessThan(
            fixture.server.calls.indexOf('/vault/wallet-v2/migrate/retire')));
    expect(fixture.server.calls.last, '/vault/wallet-v2/$_recordId');
  });

  test('changed readback leaves original wallet and proof untouched', () async {
    final fixture = await _setup(corruptReadback: true);
    await expectLater(fixture.upgrade.run(), throwsFormatException);
    expect(fixture.server.sourcePresent, isTrue);
    expect(fixture.server.verified, isFalse);
    expect(fixture.server.calls,
        isNot(contains('/vault/wallet-v2/migrate/retire')));
  });
}
