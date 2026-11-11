import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_legacy_item_import.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

const _owner = 'synthetic-owner';
const _beneficiary = 'synthetic-beneficiary';
const _commitment = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _secret = 'DEVICE_ONLY_SECRET_572';

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

Future<Map<String, dynamic>> _export(SecretKey oldKey, SecretKey newKey,
    {String itemType = 'note'}) async {
  final codec = LegacyCiphertextMigrationCodec(
    legacyKey: oldKey,
    mvk: newKey,
  );
  final encrypted = await codec.encodeLegacyItem({
    'title': 'Recovery',
    'fields': {'secret': _secret},
    'notes': 'private notes',
  });
  final row = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-legacy-item-source/v1\u0000'));
  for (final value in <Object>[7, itemType, 'Recovery', encrypted]) {
    _feed(row, value);
  }
  final rowHash = await _sha(row);
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-legacy-item-inventory/v1\u0000'));
  for (final value in <Object>[
    41,
    _owner,
    _beneficiary,
    2,
    7,
    rowHash,
  ]) {
    _feed(inventory, value);
  }
  return {
    'beneficiary_link_id': 41,
    'owner_vault_id': _owner,
    'beneficiary_vault_id': _beneficiary,
    'stage_revision': 2,
    'offer_commitment': _commitment,
    'content_scope': 'legacy_saved_items_only',
    'owner_content_complete': false,
    'source_inventory_sha256': _b64(await _sha(inventory)),
    'item_count': 1,
    'ciphertext_bytes': utf8.encode(encrypted).length,
    'items': [
      {
        'item_id': 7,
        'item_type': itemType,
        'service': 'Recovery',
        'encrypted_data': encrypted,
        'source_row_sha256': _b64(rowHash),
      },
    ],
  };
}

Map<String, dynamic> _readback(
  PreparedLinkedLegacyItems prepared,
  List<Map<String, Object>> copies,
) =>
    {
      'beneficiary_link_id': prepared.linkId,
      'owner_vault_id': prepared.ownerVaultId,
      'beneficiary_vault_id': prepared.beneficiaryVaultId,
      'stage_revision': prepared.stageRevision,
      'offer_commitment': prepared.offerCommitment,
      'content_scope': 'legacy_saved_items_only',
      'owner_content_complete': false,
      'legacy_package_preserved': true,
      'source_inventory_sha256': prepared.sourceInventorySha256,
      'item_count': prepared.itemCount,
      'all_items_copied': copies.length == prepared.itemCount,
      'copies': copies,
    };

void main() {
  late SecretKey oldKey;
  late SecretKey beneficiaryMvk;
  late ReleasedLinkedInheritanceV2 released;
  late LinkedReadbackReceipt receipt;
  late Map<String, dynamic> exported;

  setUp(() async {
    oldKey = SecretKey(List<int>.filled(32, 17));
    beneficiaryMvk = SecretKey(List<int>.filled(32, 44));
    released = ReleasedLinkedInheritanceV2(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      ownerVaultId: _owner,
      ownerMvk: SecretKey(List<int>.filled(32, 27)),
      ownerLegacyKey: oldKey,
    );
    receipt = LinkedReadbackReceipt(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      readbackAt: DateTime.now().toUtc(),
    );
    exported = await _export(oldKey, beneficiaryMvk);
  });

  Future<PreparedLinkedLegacyItems> prepare({
    Map<String, dynamic>? source,
    ReleasedLinkedInheritanceV2? package,
    LinkedReadbackReceipt? proof,
    bool Function()? accessIsCurrent,
  }) =>
      prepareReleasedLinkedLegacyItems(
        released: package ?? released,
        readbackReceipt: proof ?? receipt,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        exported: source ?? exported,
        accessIsCurrent: accessIsCurrent ?? () => true,
      );

  test('prepares ciphertext-only copy and verifies decrypted readback',
      () async {
    final prepared = await prepare();
    expect(prepared.itemCount, 1);
    final body = prepared.copyBodies.single;
    final wire = jsonEncode(body);
    expect(wire, isNot(contains(_secret)));
    expect(wire, isNot(contains('private notes')));
    expect(wire, isNot(contains('Recovery')));
    expect(wire, isNot(contains('pin')));
    expect(wire, isNot(contains('owner_mvk')));
    expect(wire, isNot(contains(exported['items'][0]['encrypted_data'])));
    expect(body['content_scope'], 'legacy_saved_items_only');
    final key = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
    final payload = jsonDecode(utf8.decode(await aesGcmUnwrap(
      key,
      b64urlDecode(body['payload_ciphertext'] as String),
    )));
    expect(payload['fields']['secret'], _secret);
    expect(payload['legacy_record']['notes'], 'private notes');
    expect(payload['_svaultai_inheritance_source_v2']['item_id'], 7);

    final copied = <Map<String, Object>>[
      {...body, 'beneficiary_item_id': 100},
    ];
    final verified = await verifyLinkedLegacyItemCopies(
      prepared: prepared,
      readback: _readback(prepared, copied),
      beneficiaryMvk: beneficiaryMvk,
      accessIsCurrent: () => true,
    );
    expect(verified, {7});
  });

  test('wrong release, key, and changed inventory fail before preparation',
      () async {
    await expectLater(
      prepare(source: {...exported, 'source_inventory_sha256': 'B' * 43}),
      throwsFormatException,
    );
    await expectLater(
      prepare(
          proof: LinkedReadbackReceipt(
        linkId: 41,
        stageRevision: 3,
        offerCommitment: _commitment,
        readbackAt: DateTime.now().toUtc(),
      )),
      throwsFormatException,
    );
    await expectLater(
      prepare(
          package: ReleasedLinkedInheritanceV2(
        linkId: 41,
        stageRevision: 2,
        offerCommitment: _commitment,
        ownerVaultId: _owner,
        ownerMvk: released.ownerMvk,
      )),
      throwsFormatException,
    );
    await expectLater(
      prepare(
          package: ReleasedLinkedInheritanceV2(
        linkId: 41,
        stageRevision: 2,
        offerCommitment: _commitment,
        ownerVaultId: _owner,
        ownerMvk: released.ownerMvk,
        ownerLegacyKey: SecretKey(List<int>.filled(32, 9)),
      )),
      throwsA(isA<Exception>()),
    );
  });

  test('tampered destination, wallet item, and lost access do not verify',
      () async {
    final prepared = await prepare();
    final body = prepared.copyBodies.single;
    final badCopy = <Map<String, Object>>[
      {...body, 'beneficiary_item_id': 100, 'source_row_sha256': 'B' * 43},
    ];
    await expectLater(
      verifyLinkedLegacyItemCopies(
        prepared: prepared,
        readback: _readback(prepared, badCopy),
        beneficiaryMvk: beneficiaryMvk,
        accessIsCurrent: () => true,
      ),
      throwsStateError,
    );
    await expectLater(
      verifyLinkedLegacyItemCopies(
        prepared: prepared,
        readback: _readback(prepared, []),
        beneficiaryMvk: beneficiaryMvk,
        accessIsCurrent: () => false,
      ),
      throwsStateError,
    );
    await expectLater(
      prepare(
          source: await _export(
        oldKey,
        beneficiaryMvk,
        itemType: 'crypto_wallet_account',
      )),
      throwsStateError,
    );
  });
}
