import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_mixed_item_import.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

const _owner = 'synthetic-owner';
const _beneficiary = 'synthetic-beneficiary';
const _commitment = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _secret = 'PRIVATE_DEVICE_VALUE_893';

String _b64(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final length = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(length.buffer.asUint8List());
  builder.add(raw);
}

Future<Uint8List> _sha(BytesBuilder builder) async => Uint8List.fromList(
      (await Sha256().hash(builder.toBytes())).bytes,
    );

Future<Map<String, dynamic>> _export(
  SecretKey oldKey,
  SecretKey ownerMvk,
  SecretKey beneficiaryMvk,
) async {
  final codec = LegacyCiphertextMigrationCodec(
    legacyKey: oldKey,
    mvk: beneficiaryMvk,
  );
  final oldCt = await codec.encodeLegacyItem({
    'title': 'Old note',
    'fields': {'value': _secret},
  });
  final ownerMetaKey = await VaultKeyHierarchy(ownerMvk).metadataKey();
  final privateFields = <String, Uint8List>{
    'item_type_ciphertext':
        await aesGcmWrap(ownerMetaKey, utf8.encode('login')),
    'service_ciphertext':
        await aesGcmWrap(ownerMetaKey, utf8.encode('New account')),
    'payload_ciphertext': await aesGcmWrap(
      ownerMetaKey,
      utf8.encode(jsonEncode({
        'fields': {'username': _secret},
      })),
    ),
  };
  final rows = <Map<String, dynamic>>[
    {
      'item_id': 7,
      'source_kind': 'legacy',
      'item_type': 'note',
      'service': 'Old note',
      'encrypted_data': oldCt,
    },
    {
      'item_id': 8,
      'source_kind': 'private',
      for (final field in privateFields.keys)
        field: _b64(privateFields[field]!),
    },
  ];
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-mixed-item-inventory/v1\u0000'));
  for (final value in <Object>[41, _owner, _beneficiary, 2]) {
    _feed(inventory, value);
  }
  for (final row in rows) {
    final id = row['item_id'] as int;
    final kind = row['source_kind'] as String;
    final rowHash = BytesBuilder()
      ..add(utf8.encode('linked-old-v2-mixed-item-source/v1\u0000'));
    _feed(rowHash, id);
    _feed(rowHash, kind);
    if (kind == 'legacy') {
      for (final field in ['item_type', 'service', 'encrypted_data']) {
        _feed(rowHash, row[field] as String);
      }
    } else {
      for (final field in [
        'item_type_ciphertext',
        'service_ciphertext',
        'payload_ciphertext',
      ]) {
        _feed(rowHash, privateFields[field]!);
      }
    }
    final hash = await _sha(rowHash);
    row['source_row_sha256'] = _b64(hash);
    _feed(inventory, id);
    _feed(inventory, kind);
    _feed(inventory, hash);
  }
  return {
    'beneficiary_link_id': 41,
    'owner_vault_id': _owner,
    'beneficiary_vault_id': _beneficiary,
    'stage_revision': 2,
    'offer_commitment': _commitment,
    'content_scope': 'mixed_saved_items_only',
    'owner_content_complete': false,
    'source_inventory_sha256': _b64(await _sha(inventory)),
    'item_count': 2,
    'ciphertext_bytes': utf8.encode(oldCt).length +
        privateFields.values.fold<int>(0, (sum, raw) => sum + raw.length),
    'items': rows,
  };
}

Map<String, dynamic> _readback(
  Map<String, dynamic> exported,
  List<Map<String, dynamic>> copies,
) =>
    {
      'beneficiary_link_id': 41,
      'owner_vault_id': _owner,
      'beneficiary_vault_id': _beneficiary,
      'stage_revision': 2,
      'offer_commitment': _commitment,
      'content_scope': 'mixed_saved_items_only',
      'owner_content_complete': false,
      'legacy_package_preserved': true,
      'source_inventory_sha256': exported['source_inventory_sha256'],
      'item_count': 2,
      'all_items_copied': copies.length == 2,
      'copies': copies,
    };

void main() {
  late SecretKey oldKey;
  late SecretKey ownerMvk;
  late SecretKey beneficiaryMvk;
  late ReleasedLinkedInheritanceV2 released;
  late LinkedReadbackReceipt receipt;
  late Map<String, dynamic> exported;

  setUp(() async {
    oldKey = SecretKey(List<int>.filled(32, 17));
    ownerMvk = SecretKey(List<int>.filled(32, 27));
    beneficiaryMvk = SecretKey(List<int>.filled(32, 44));
    released = ReleasedLinkedInheritanceV2(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      ownerVaultId: _owner,
      ownerMvk: ownerMvk,
      ownerLegacyKey: oldKey,
    );
    receipt = LinkedReadbackReceipt(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      readbackAt: DateTime.now().toUtc(),
    );
    exported = await _export(oldKey, ownerMvk, beneficiaryMvk);
  });

  Future<LinkedV2MixedSavedItemImport> run({
    Map<String, dynamic>? source,
    LinkedReadbackReceipt? proof,
    ReleasedLinkedInheritanceV2? package,
    WriteMixedSavedItem? copyItem,
    ReadbackMixedSavedItems? readbackCopies,
  }) =>
      importReleasedLinkedMixedSavedItems(
        released: package ?? released,
        readbackReceipt: proof ?? receipt,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        fetchExport: (_) async => source ?? exported,
        copyItem: copyItem ?? (_) async => throw StateError('Unexpected copy'),
        readbackCopies:
            readbackCopies ?? (_, __) async => _readback(exported, []),
        accessIsCurrent: () => true,
      );

  test('both formats re-encrypt locally, read back, and retry once', () async {
    final copies = <Map<String, dynamic>>[];
    var writes = 0;
    Future<LinkedV2MixedSavedItemImport> copy() => run(
          copyItem: (body) async {
            writes++;
            final wire = jsonEncode(body);
            expect(wire, isNot(contains(_secret)));
            expect(wire, isNot(contains('Old note')));
            expect(wire, isNot(contains('New account')));
            expect(wire, isNot(contains('pin')));
            expect(wire, isNot(contains('owner_mvk')));
            expect(body['content_scope'], 'mixed_saved_items_only');
            copies.add({
              ...body,
              'beneficiary_item_id': 100 + writes,
            });
            return {
              'beneficiary_link_id': 41,
              'source_item_id': body['source_item_id'],
              'beneficiary_item_id': 100 + writes,
              'source_inventory_sha256': exported['source_inventory_sha256'],
              'legacy_package_preserved': true,
              'created': true,
            };
          },
          readbackCopies: (_, digest) async {
            expect(digest, exported['source_inventory_sha256']);
            return _readback(exported, copies);
          },
        );
    final first = await copy();
    expect(first.itemCount, 2);
    expect(first.newItems, 2);
    expect(copies.map((row) => row['source_item_id']).toSet(), {7, 8});
    final second = await copy();
    expect(second.newItems, 0);
    expect(writes, 2);
  });

  test('changed source and missing old key fail before any copy', () async {
    var writes = 0;
    Future<Map<String, dynamic>> badCopy(Map<String, dynamic> _) async {
      writes++;
      return {};
    }

    await expectLater(
      run(
        source: {...exported, 'source_inventory_sha256': 'B' * 43},
        copyItem: badCopy,
      ),
      throwsFormatException,
    );
    await expectLater(
      run(
        package: ReleasedLinkedInheritanceV2(
          linkId: 41,
          stageRevision: 2,
          offerCommitment: _commitment,
          ownerVaultId: _owner,
          ownerMvk: ownerMvk,
        ),
        copyItem: badCopy,
      ),
      throwsFormatException,
    );
    await expectLater(
      run(
        proof: LinkedReadbackReceipt(
          linkId: 41,
          stageRevision: 3,
          offerCommitment: _commitment,
          readbackAt: DateTime.now().toUtc(),
        ),
        copyItem: badCopy,
      ),
      throwsFormatException,
    );
    expect(writes, 0);
  });

  test('tampered recipient copy cannot satisfy exact readback', () async {
    final copies = <Map<String, dynamic>>[];
    await expectLater(
      run(
        copyItem: (body) async {
          copies.add({
            ...body,
            'beneficiary_item_id': 100 + copies.length,
            'source_row_sha256': 'B' * 43,
          });
          return {
            'beneficiary_link_id': 41,
            'source_item_id': body['source_item_id'],
            'beneficiary_item_id': 100 + copies.length,
            'source_inventory_sha256': exported['source_inventory_sha256'],
            'legacy_package_preserved': true,
            'created': true,
          };
        },
        readbackCopies: (_, __) async => _readback(exported, copies),
      ),
      throwsStateError,
    );
  });
}
