import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_memory_import.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

const _owner = 'synthetic-owner';
const _beneficiary = 'synthetic-beneficiary';
const _commitment = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

String _b64(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final size = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(size.buffer.asUint8List());
  builder.add(raw);
}

Future<String> _digest(BytesBuilder builder) async =>
    _b64((await Sha256().hash(builder.toBytes())).bytes);

Future<Map<String, dynamic>> _export(SecretKey ownerMvk) async {
  final key = await VaultKeyHierarchy(ownerMvk).memoryKey();
  final ct = await aesGcmWrap(
      key,
      utf8.encode(jsonEncode({
        'memory_key': 'Beach trip',
        'memory_value': 'Synthetic note only',
      })));
  final rowBuilder = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-memory-source/v1\u0000'));
  for (final value in <Object>[7, 'note', 'memory-synthetic', 'S' * 43, ct]) {
    _feed(rowBuilder, value);
  }
  final rowDigest = await _digest(rowBuilder);
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-memory-inventory/v1\u0000'));
  for (final value in <Object>[41, _owner, _beneficiary, 2, 7]) {
    _feed(inventory, value);
  }
  _feed(inventory, b64urlDecode(rowDigest));
  return {
    'beneficiary_link_id': 41,
    'owner_vault_id': _owner,
    'beneficiary_vault_id': _beneficiary,
    'stage_revision': 2,
    'offer_commitment': _commitment,
    'content_scope': 'memory_only',
    'owner_content_complete': false,
    'source_inventory_sha256': await _digest(inventory),
    'memory_count': 1,
    'ciphertext_bytes': ct.length,
    'memories': [
      {
        'memory_id': 7,
        'memory_type': 'note',
        'memory_record_id': 'memory-synthetic',
      'source_snapshot': 'S' * 43,
        'source_row_sha256': rowDigest,
        'payload_ciphertext': _b64(ct),
      }
    ],
  };
}

Map<String, dynamic> _copies(
  Map<String, dynamic> exported,
  List<Map<String, dynamic>> copied,
) =>
    {
      'beneficiary_link_id': 41,
      'owner_vault_id': _owner,
      'beneficiary_vault_id': _beneficiary,
      'stage_revision': 2,
      'offer_commitment': _commitment,
      'content_scope': 'memory_only',
      'owner_content_complete': false,
      'source_inventory_sha256': exported['source_inventory_sha256'],
      'memory_count': 1,
      'legacy_package_preserved': true,
      'all_memories_copied': copied.length == 1,
      'copies': copied,
    };

void main() {
  late SecretKey ownerMvk;
  late SecretKey beneficiaryMvk;
  late ReleasedLinkedInheritanceV2 released;
  late LinkedReadbackReceipt receipt;
  late Map<String, dynamic> exported;

  setUp(() async {
    ownerMvk = SecretKey(List<int>.filled(32, 27));
    beneficiaryMvk = SecretKey(List<int>.filled(32, 44));
    released = ReleasedLinkedInheritanceV2(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      ownerVaultId: _owner,
      ownerMvk: ownerMvk,
    );
    receipt = LinkedReadbackReceipt(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      readbackAt: DateTime.now().toUtc(),
    );
    exported = await _export(ownerMvk);
  });

  test('copies with fresh proof and verifies recipient ciphertext on retry',
      () async {
    final copied = <Map<String, dynamic>>[];
    var writes = 0;
    var proofs = 0;
    Future<LinkedV2MemoryImport> run() => importLinkedV2Memories(
          released: released,
          readbackReceipt: receipt,
          beneficiaryVaultId: _beneficiary,
          beneficiaryMvk: beneficiaryMvk,
          fetchExport: (_) async => exported,
          copyMemory: (body) async {
            writes++;
            expect(body.keys, isNot(contains('pin')));
            expect(body.keys, isNot(contains('memory_value')));
            expect(body['zk_proof_token'], 'opaque-proof-$proofs');
            expect(body['content_scope'], 'memory_only');
            final key = await VaultKeyHierarchy(beneficiaryMvk).memoryKey();
            final clear = utf8.decode(await aesGcmUnwrap(
              key,
              b64urlDecode(body['payload_ciphertext'] as String),
            ));
            expect(clear, contains('Synthetic note only'));
            copied.add({
              'source_memory_id': 7,
              'beneficiary_memory_id': 100,
              'beneficiary_memory_record_id':
                  body['beneficiary_memory_record_id'],
              'memory_type': body['memory_type'],
              'source_row_sha256': body['source_row_sha256'],
              'memory_lookup_hash': body['memory_lookup_hash'],
              'payload_ciphertext': body['payload_ciphertext'],
            });
            return {
              'beneficiary_link_id': 41,
              'source_memory_id': 7,
              'beneficiary_memory_id': 100,
              'source_inventory_sha256': exported['source_inventory_sha256'],
              'created': true,
              'legacy_package_preserved': true,
            };
          },
          readbackCopies: (_, digest) async {
            expect(digest, exported['source_inventory_sha256']);
            return _copies(exported, copied);
          },
          freshZkProof: () async => 'opaque-proof-${++proofs}',
          accessIsCurrent: () => true,
        );
    final first = await run();
    expect(first.memoryCount, 1);
    expect(first.newMemories, 1);
    final second = await run();
    expect(second.newMemories, 0);
    expect(writes, 1);
    expect(proofs, 1);
  });

  test('PIN-shaped proof and changed inventory never write a copy', () async {
    var writes = 0;
    Future<void> run(Map<String, dynamic> inventory) async {
      await importLinkedV2Memories(
        released: released,
        readbackReceipt: receipt,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        fetchExport: (_) async => inventory,
        copyMemory: (_) async {
          writes++;
          return {};
        },
        readbackCopies: (_, __) async => _copies(inventory, []),
        freshZkProof: () async => '123456',
        accessIsCurrent: () => true,
      );
    }

    await expectLater(run(exported), throwsArgumentError);
    expect(writes, 0);
    final altered = Map<String, dynamic>.from(exported)
      ..['source_inventory_sha256'] = 'B' * 43;
    await expectLater(run(altered), throwsFormatException);
    expect(writes, 0);
  });

  test('revocation after fresh proof stops before the write', () async {
    var active = true;
    var writes = 0;
    await expectLater(
      importLinkedV2Memories(
        released: released,
        readbackReceipt: receipt,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        fetchExport: (_) async => exported,
        copyMemory: (_) async {
          writes++;
          return {};
        },
        readbackCopies: (_, __) async => _copies(exported, []),
        freshZkProof: () async {
          active = false;
          return 'opaque-proof';
        },
        accessIsCurrent: () => active,
      ),
      throwsStateError,
    );
    expect(writes, 0);
  });
}
