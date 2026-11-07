import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(() {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 39)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(ZkActiveMvk.clear);

  test('keyless list and selected detail never send the cached PIN', () async {
    final mvk = ZkActiveMvk.current()!;
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async => b64urlEncode(
          await aesGcmWrap(key, utf8.encode(value)),
        );
    final seen = <http.Request>[];
    final mock = MockClient((request) async {
      seen.add(request);
      expect(request.headers['authorization'], 'Bearer synthetic-session');
      expect(request.headers['x-device-id'], 'synthetic-device');
      expect(request.body, isNot(contains('synthetic-pin-marker')));
      if (request.url.path == '/vault/ciphertext/vault-items') {
        return http.Response('[]', 200);
      }
      if (request.url.path == '/vault/items/metadata') {
        expect(request.url.queryParameters['after_item_id'], '0');
        expect(request.url.queryParameters['limit'], '100');
        return http.Response(jsonEncode(<String, dynamic>{
          'records': <Map<String, dynamic>>[
            <String, dynamic>{
              'item_id': 42,
              'item_type_ciphertext': await wrap('login'),
              'service_ciphertext': await wrap('Synthetic account'),
              'item_type': null,
              'service': null,
              'is_legacy': true,
              'has_v2_payload': false,
            },
          ],
          'has_more': false,
          'next_after_item_id': 42,
        }), 200);
      }
      fail('Unexpected route ${request.url.path}');
    });
    var reads = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: mock,
      legacyZkItemReader: (id) async {
        reads++;
        expect(id, 42);
        return <String, dynamic>{
          'id': 42,
          'item_type': 'login',
          'service': 'Synthetic account',
          'fields': <String, String>{'username': 'synthetic-user'},
        };
      },
    );
    final listed = await client.listVaultSecureItems(
      vaultName: 'synthetic-vault',
      pin: 'synthetic-pin-marker',
      authToken: 'synthetic-session',
    );
    final rows = listed['items'] as List;
    expect(rows, hasLength(1));
    expect((rows.single as Map)['id'], 42);
    expect((rows.single as Map)['service'], 'Synthetic account');
    final detail = await client.getVaultSecureItem(
      vaultName: 'synthetic-vault',
      service: 'Synthetic account',
      itemType: 'login',
      itemId: '42',
      pin: 'synthetic-pin-marker',
      authToken: 'synthetic-session',
    );
    expect(detail['fields'], <String, String>{'username': 'synthetic-user'});
    expect(reads, 1);
    expect(seen.every((request) => request.method == 'GET'), isTrue);
    expect(seen.any((request) => request.url.path == '/get-secure-item'), isFalse);
    final noReader = VaultAIClient(
      baseUrl: 'https://synthetic.example', httpClient: mock,
    );
    await expectLater(noReader.getVaultSecureItem(
      vaultName: '', service: 'Synthetic account', itemType: 'login',
      itemId: '42', pin: 'synthetic-pin-marker',
      authToken: 'synthetic-session',
    ), throwsStateError);
    final raw = await client.listZkItemMetadataRaw(authToken: 'synthetic-session');
    expect(raw.single['is_legacy'], isTrue);
  }, skip: !kEnableKeylessSavedItemRead);

  test('key loss during metadata response cannot trigger legacy mutation', () async {
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/vault/items/metadata') {
          ZkActiveMvk.clear();
          return http.Response('{"records":[],"has_more":false}', 200);
        }
        fail('Unexpected route ${request.url.path}');
      }),
    );
    await expectLater(client.updateVaultSecureItem(
      vaultName: '', oldService: 'Synthetic account', itemType: 'login',
      itemId: '42', fields: <String, dynamic>{'username': 'changed'},
      pin: 'synthetic-pin-marker', authToken: 'synthetic-session',
    ), throwsStateError);
    expect(paths, isNot(contains('/update-secure-item')));
  }, skip: !kEnableKeylessSavedItemRead);

  test('missing metadata route fails closed without a PIN fallback', () async {
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        return http.Response('{"detail":"not_found"}', 404);
      }),
    );
    await expectLater(
      client.listVaultSecureItems(
        vaultName: '', pin: 'synthetic-pin-marker',
        authToken: 'synthetic-session',
      ),
      throwsException,
    );
    expect(paths, contains('/vault/items/metadata'));
    expect(paths, isNot(contains('/list-secure-items')));
  }, skip: !kEnableKeylessSavedItemRead);

  test('ZK legacy edit/delete refuse raw PIN route and preserve data', () async {
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/vault/items/metadata') {
          return http.Response(jsonEncode(<String, dynamic>{
            'records': <Map<String, dynamic>>[
              <String, dynamic>{
                'item_id': 42,
                'item_type': 'login',
                'service': 'Synthetic account',
                'is_legacy': true,
                'has_v2_payload': false,
              },
            ],
            'has_more': false,
            'next_after_item_id': 42,
          }), 200);
        }
        fail('Unexpected route ${request.url.path}');
      }),
    );
    await expectLater(client.updateVaultSecureItem(
      vaultName: '', oldService: 'Synthetic account', itemType: 'login',
      itemId: '42', fields: <String, dynamic>{'username': 'changed'},
      pin: 'synthetic-pin-marker', authToken: 'synthetic-session',
    ), throwsStateError);
    await expectLater(client.deleteVaultSecureItem(
      vaultName: '', service: 'Synthetic account', itemType: 'login',
      itemId: '42', pin: 'synthetic-pin-marker',
      authToken: 'synthetic-session',
    ), throwsStateError);
    expect(paths, isNot(contains('/update-secure-item')));
    expect(paths, isNot(contains('/delete-secure-item')));
  }, skip: !kEnableKeylessSavedItemRead);

  test('legacy edit uses the local replacement adapter without sending a PIN',
      () async {
    final paths = <String>[];
    var edits = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.body, isNot(contains('synthetic-pin-marker')));
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/vault/items/metadata') {
          return http.Response(jsonEncode(<String, dynamic>{
            'records': <Map<String, dynamic>>[
              <String, dynamic>{
                'item_id': 42,
                'item_type': 'login',
                'service': 'Synthetic account',
                'is_legacy': true,
                'has_v2_payload': false,
              },
            ],
            'has_more': false,
            'next_after_item_id': 42,
          }), 200);
        }
        fail('Unexpected route ${request.url.path}');
      }),
      legacyZkItemUpdater: ({required itemId, required itemType,
          required oldService, newService, fields}) async {
        edits++;
        expect(itemId, 42);
        expect(itemType, 'login');
        expect(oldService, 'Synthetic account');
        expect(newService, 'Updated account');
        expect(fields, <String, dynamic>{'username': 'changed'});
        return <String, dynamic>{
          'id': 42, 'item_id': 42, 'item_type': 'login',
          'service': 'Updated account', 'updated': true,
        };
      },
    );
    final response = await client.updateVaultSecureItem(
      vaultName: '', oldService: 'Synthetic account', itemType: 'login',
      itemId: '42', newService: 'Updated account',
      fields: <String, dynamic>{'username': 'changed'},
      pin: 'synthetic-pin-marker', authToken: 'synthetic-session',
    );
    expect(response['updated'], true);
    expect(edits, 1);
    expect(paths, <String>[
      '/vault/ciphertext/vault-items', '/vault/items/metadata',
    ]);
  }, skip: !kEnableKeylessLegacySavedItemEdit);
}
