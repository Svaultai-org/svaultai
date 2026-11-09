import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const _enabled = bool.fromEnvironment(
  'VAULTAI_ENABLE_LINKED_INHERITANCE_ITEM_IMPORT',
  defaultValue: false,
);
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

void main() {
  test('item import transport is opt-in and sends ciphertext only', () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 27));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 44));
    final sourceKey = await VaultKeyHierarchy(ownerMvk).metadataKey();
    final fields = <String, Uint8List>{
      'item_type_ciphertext': await aesGcmWrap(sourceKey, utf8.encode('login')),
      'service_ciphertext': await aesGcmWrap(sourceKey, utf8.encode('Example')),
      'payload_ciphertext': await aesGcmWrap(sourceKey, utf8.encode(jsonEncode({
        'fields': {'username': 'synthetic-user'},
      }))),
    };
    final itemDigest = BytesBuilder()
      ..add(utf8.encode('linked-old-v2-item-source/v1\u0000'));
    _feed(itemDigest, 7);
    for (final field in fields.values) {
      _feed(itemDigest, field);
    }
    final inventory = BytesBuilder()
      ..add(utf8.encode('linked-old-v2-item-inventory/v1\u0000'));
    for (final value in [
      41, 'synthetic-owner', 'synthetic-beneficiary', 2, 7,
    ]) {
      _feed(inventory, value);
    }
    for (final field in fields.values) {
      _feed(inventory, field);
    }
    final inventoryHash = await _digest(inventory);
    final rowHash = await _digest(itemDigest);
    final exported = {
      'beneficiary_link_id': 41,
      'owner_vault_id': 'synthetic-owner',
      'beneficiary_vault_id': 'synthetic-beneficiary',
      'stage_revision': 2,
      'offer_commitment': _commitment,
      'content_scope': 'saved_items_only',
      'owner_content_complete': false,
      'source_inventory_sha256': inventoryHash,
      'item_count': 1,
      'ciphertext_bytes':
          fields.values.fold<int>(0, (sum, value) => sum + value.length),
      'items': [
        {
          'item_id': 7,
          'source_row_sha256': rowHash,
          for (final entry in fields.entries) entry.key: _b64(entry.value),
        },
      ],
    };
    final released = ReleasedLinkedInheritanceV2(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
    );
    final receipt = LinkedReadbackReceipt(
      linkId: 41,
      stageRevision: 2,
      offerCommitment: _commitment,
      readbackAt: DateTime.now().toUtc(),
    );
    final copied = <Map<String, dynamic>>[];
    final paths = <String>[];
    setApiClientDeviceId('synthetic-device');
    ZkActiveMvk.set(
      mvk: beneficiaryMvk,
      vaultId: 'synthetic-beneficiary',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        if (request.url.path ==
            '/inheritance/old-link-v2/41/vault-items') {
          expect(request.method, 'GET');
          return http.Response(jsonEncode(exported), 200);
        }
        if (request.url.path ==
            '/inheritance/old-link-v2/41/item-copies') {
          expect(request.method, 'GET');
          expect(request.url.queryParameters['source_inventory_sha256'],
              inventoryHash);
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'owner_vault_id': 'synthetic-owner',
            'beneficiary_vault_id': 'synthetic-beneficiary',
            'stage_revision': 2,
            'offer_commitment': _commitment,
            'content_scope': 'saved_items_only',
            'owner_content_complete': false,
            'source_inventory_sha256': inventoryHash,
            'item_count': 1,
            'legacy_package_preserved': true,
            'all_items_copied': copied.length == 1,
            'copies': copied,
          }), 200);
        }
        if (request.url.path == '/inheritance/old-link-v2/item-copy') {
          expect(request.method, 'POST');
          expect(request.body, isNot(contains('synthetic-user')));
          expect(request.body, isNot(contains('"pin"')));
          expect(request.body, isNot(contains('"owner_mvk"')));
          expect(request.body, isNot(contains('"service"')));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          copied.add({
            'source_item_id': 7,
            'beneficiary_item_id': 100,
            'source_row_sha256': rowHash,
            'title_lookup_hash': body['title_lookup_hash'],
            'item_type_ciphertext': body['item_type_ciphertext'],
            'service_ciphertext': body['service_ciphertext'],
            'payload_ciphertext': body['payload_ciphertext'],
          });
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'source_item_id': 7,
            'beneficiary_item_id': 100,
            'source_inventory_sha256': inventoryHash,
            'created': true,
            'legacy_package_preserved': true,
          }), 200);
        }
        fail('Unexpected ${request.method} ${request.url.path}');
      }),
    );
    Future<void> run() async {
      final result = await client.importLinkedOldInheritanceV2SavedItems(
        authToken: 'synthetic-session',
        beneficiaryVaultId: 'synthetic-beneficiary',
        beneficiaryMvk: beneficiaryMvk,
        released: released,
        readbackReceipt: receipt,
      );
      expect(result.itemCount, 1);
      expect(result.newItems, 1);
    }
    if (_enabled) {
      await run();
      expect(paths, [
        '/inheritance/old-link-v2/41/vault-items',
        '/inheritance/old-link-v2/41/item-copies',
        '/inheritance/old-link-v2/item-copy',
        '/inheritance/old-link-v2/41/item-copies',
      ]);
    } else {
      await expectLater(run(), throwsStateError);
      expect(paths, isEmpty);
    }
  });
}
