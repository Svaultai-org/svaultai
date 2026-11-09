import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_item_import.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

const _owner = 'synthetic-owner';
const _beneficiary = 'synthetic-beneficiary';
const _commitment =
    'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

String _b64(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final size = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(size.buffer.asUint8List());
  builder.add(raw);
}

Future<String> _digest(BytesBuilder builder) async =>
    _b64((await Sha256().hash(builder.toBytes())).bytes);

Future<Map<String, dynamic>> _export(
  SecretKey ownerMvk, {
  String itemType = 'login',
}) async {
  final key = await VaultKeyHierarchy(ownerMvk).metadataKey();
  final ciphertext = <String, Uint8List>{
    'item_type_ciphertext':
        await aesGcmWrap(key, utf8.encode(itemType)),
    'service_ciphertext':
        await aesGcmWrap(key, utf8.encode('Example')),
    'payload_ciphertext': await aesGcmWrap(
      key,
      utf8.encode(jsonEncode({
        'fields': {'username': 'synthetic-user'},
      })),
    ),
  };
  final rowBuilder = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-item-source/v1\u0000'));
  _feed(rowBuilder, 7);
  for (final bytes in ciphertext.values) {
    _feed(rowBuilder, bytes);
  }
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-item-inventory/v1\u0000'));
  for (final value in [41, _owner, _beneficiary, 2, 7]) {
    _feed(inventory, value);
  }
  for (final bytes in ciphertext.values) {
    _feed(inventory, bytes);
  }
  return {
    'beneficiary_link_id': 41,
    'owner_vault_id': _owner,
    'beneficiary_vault_id': _beneficiary,
    'stage_revision': 2,
    'offer_commitment': _commitment,
    'content_scope': 'saved_items_only',
    'owner_content_complete': false,
    'source_inventory_sha256': await _digest(inventory),
    'item_count': 1,
    'ciphertext_bytes':
        ciphertext.values.fold<int>(0, (sum, field) => sum + field.length),
    'items': [
      {
        'item_id': 7,
        'source_row_sha256': await _digest(rowBuilder),
        for (final entry in ciphertext.entries) entry.key: _b64(entry.value),
      },
    ],
  };
}

Map<String, dynamic> _copies(
  Map<String, dynamic> exported,
  List<Map<String, dynamic>> copied,
) => {
      'beneficiary_link_id': 41,
      'owner_vault_id': _owner,
      'beneficiary_vault_id': _beneficiary,
      'stage_revision': 2,
      'offer_commitment': _commitment,
      'content_scope': 'saved_items_only',
      'owner_content_complete': false,
      'source_inventory_sha256': exported['source_inventory_sha256'],
      'item_count': 1,
      'legacy_package_preserved': true,
      'all_items_copied': copied.length == 1,
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

  test('bounded encrypted copy verifies destination and retry is idempotent',
      () async {
    final copied = <Map<String, dynamic>>[];
    var writes = 0;
    Future<LinkedV2SavedItemImport> run() => importLinkedV2SavedItems(
          released: released,
          readbackReceipt: receipt,
          beneficiaryVaultId: _beneficiary,
          beneficiaryMvk: beneficiaryMvk,
          fetchExport: (_) async => exported,
          copyItem: (body) async {
            writes++;
            expect(body.keys, isNot(contains('pin')));
            expect(body.keys, isNot(contains('owner_mvk')));
            expect(body.keys, isNot(contains('service')));
            expect(body['content_scope'], 'saved_items_only');
            final lookup = await VaultKeyHierarchy(beneficiaryMvk)
                .savedItemTitleLookupKey();
            final titleHash = await keyedLookupHash(
              lookup,
              utf8.encode('login\u0000example (inherited 41-7)'),
            );
            expect(body['title_lookup_hash'], _b64(titleHash));
            final key = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
            final decrypted = utf8.decode(await aesGcmUnwrap(
              key,
              b64urlDecode(body['payload_ciphertext'] as String),
            ));
            expect(decrypted, contains('synthetic-user'));
            copied.add({
              'source_item_id': 7,
              'beneficiary_item_id': 100,
              'source_row_sha256': body['source_row_sha256'],
              'title_lookup_hash': body['title_lookup_hash'],
              'item_type_ciphertext': body['item_type_ciphertext'],
              'service_ciphertext': body['service_ciphertext'],
              'payload_ciphertext': body['payload_ciphertext'],
            });
            return {
              'beneficiary_link_id': 41,
              'source_item_id': 7,
              'beneficiary_item_id': 100,
              'source_inventory_sha256': exported['source_inventory_sha256'],
              'created': true,
              'legacy_package_preserved': true,
            };
          },
          readbackCopies: (_, digest) async {
            expect(digest, exported['source_inventory_sha256']);
            return _copies(exported, copied);
          },
          accessIsCurrent: () => true,
        );
    final first = await run();
    expect(first.newItems, 1);
    expect(first.itemCount, 1);
    final second = await run();
    expect(second.newItems, 0);
    expect(writes, 1);
  });

  test('changed inventory and mismatched receipt fail before copy', () async {
    var writes = 0;
    Future<void> run({required Map<String, dynamic> source,
        required LinkedReadbackReceipt proof}) async {
      await importLinkedV2SavedItems(
        released: released,
        readbackReceipt: proof,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        fetchExport: (_) async => source,
        copyItem: (_) async {
          writes++;
          return {};
        },
        readbackCopies: (_, __) async => _copies(exported, []),
        accessIsCurrent: () => true,
      );
    }
    await expectLater(run(
      source: {...exported, 'source_inventory_sha256': 'B' * 43},
      proof: receipt,
    ), throwsFormatException);
    await expectLater(run(
      source: exported,
      proof: LinkedReadbackReceipt(
        linkId: 41,
        stageRevision: 3,
        offerCommitment: _commitment,
        readbackAt: DateTime.now().toUtc(),
      ),
    ), throwsFormatException);
    expect(writes, 0);
  });

  test('wallet records require their own import before any item write',
      () async {
    exported = await _export(ownerMvk, itemType: 'crypto_wallet_account');
    var writes = 0;
    await expectLater(importLinkedV2SavedItems(
      released: released,
      readbackReceipt: receipt,
      beneficiaryVaultId: _beneficiary,
      beneficiaryMvk: beneficiaryMvk,
      fetchExport: (_) async => exported,
      copyItem: (_) async {
        writes++;
        return {};
      },
      readbackCopies: (_, __) async => _copies(exported, []),
      accessIsCurrent: () => true,
    ), throwsStateError);
    expect(writes, 0);
  });

  test('revoked readback and tampered destination never confirm import',
      () async {
    var writes = 0;
    Future<void> run({required bool revoked}) async {
      Map<String, dynamic>? copied;
      await importLinkedV2SavedItems(
        released: released,
        readbackReceipt: receipt,
        beneficiaryVaultId: _beneficiary,
        beneficiaryMvk: beneficiaryMvk,
        fetchExport: (_) async => exported,
        copyItem: (body) async {
          writes++;
          copied = {
            'source_item_id': 7,
            'beneficiary_item_id': 100,
            'source_row_sha256': body['source_row_sha256'],
            'title_lookup_hash': body['title_lookup_hash'],
            'item_type_ciphertext': body['item_type_ciphertext'],
            'service_ciphertext': body['service_ciphertext'],
            'payload_ciphertext': body['payload_ciphertext'],
          };
          return {
            'beneficiary_link_id': 41,
            'source_item_id': 7,
            'beneficiary_item_id': 100,
            'source_inventory_sha256': exported['source_inventory_sha256'],
            'created': true,
            'legacy_package_preserved': true,
          };
        },
        readbackCopies: (_, __) async {
          if (revoked && copied != null) {
            throw StateError('Inheritance link revoked');
          }
          if (copied == null) return _copies(exported, []);
          return _copies(exported, [{
            ...copied!,
            'service_ciphertext': exported['items'][0]
                ['service_ciphertext'],
          }]);
        },
        accessIsCurrent: () => true,
      );
    }
    await expectLater(run(revoked: true), throwsStateError);
    await expectLater(run(revoked: false),
        throwsA(isA<SecretBoxAuthenticationError>()));
    expect(writes, 2);
  });
}
