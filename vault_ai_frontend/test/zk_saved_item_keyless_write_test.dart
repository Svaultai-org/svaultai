import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 93));
  setUp(() {
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-saved-item-vault',
      vaultHandle: 'synthetic-saved-item-handle',
    );
    setApiClientDeviceId('synthetic-saved-item-device');
  });
  tearDown(() {
    ZkActiveMvk.clear();
    setApiClientDeviceId('');
  });

  test('create and edit use MVK ciphertext with exact readback', () async {
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> unwrap(Object? value) async => utf8.decode(
          await aesGcmUnwrap(key, b64urlDecode(value as String)),
        );
    final rows = <Map<String, dynamic>>[];
    final requests = <http.Request>[];
    var nextId = 42;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-saved-item-device');
        expect(request.body, isNot(contains('synthetic-secret-marker')));
        expect(request.body, isNot(contains('Synthetic account')));
        expect(request.body, isNot(contains('"pin"')));
        switch ('${request.method} ${request.url.path}') {
          case 'GET /vault/items/metadata':
            return http.Response(
                jsonEncode(<String, dynamic>{
                  'records': <Map<String, dynamic>>[
                    for (final row in rows)
                      <String, dynamic>{
                        'item_id': row['item_id'],
                        'item_type_ciphertext': row['item_type_ciphertext'],
                        'service_ciphertext': row['service_ciphertext'],
                        'is_legacy': false,
                        'has_v2_payload': true,
                      },
                  ],
                  'has_more': false,
                  'next_after_item_id': rows.isEmpty ? 0 : rows.last['item_id'],
                }),
                200);
          case 'GET /vault/ciphertext/vault-items':
            return http.Response(jsonEncode(rows), 200);
          case 'POST /vault/ciphertext/vault-items':
            final body =
                Map<String, dynamic>.from(jsonDecode(request.body) as Map);
            final id = (body['item_id'] as int?) ?? nextId++;
            rows.removeWhere((row) => row['item_id'] == id);
            rows.add(<String, dynamic>{...body, 'item_id': id});
            return http.Response(
                jsonEncode(<String, dynamic>{
                  'item_id': id,
                  'created': body['item_id'] == null,
                }),
                200);
        }
        fail('Unexpected route ${request.method} ${request.url.path}');
      }),
    );

    final created = await client.saveZkVaultSecureItem(
      authToken: 'synthetic-session',
      itemType: 'login',
      service: 'Synthetic account',
      fields: <String, dynamic>{
        'username': 'synthetic-user',
        'password': 'synthetic-secret-marker',
      },
    );
    expect(created, <String, dynamic>{'item_id': 42, 'created': true});
    expect(rows, hasLength(1));
    expect(rows.single['mutation_intent'], 'create');
    expect(await unwrap(rows.single['item_type_ciphertext']), 'login');
    expect(
        await unwrap(rows.single['service_ciphertext']), 'Synthetic account');
    final createdPayload = jsonDecode(
      await unwrap(rows.single['payload_ciphertext']),
    ) as Map;
    expect(createdPayload['fields'], <String, dynamic>{
      'username': 'synthetic-user',
      'password': 'synthetic-secret-marker',
    });

    // Unknown encrypted payload fields must survive an edit. The editor only
    // replaces the visible `fields` map.
    final retainedPayload = <String, dynamic>{
      ...createdPayload,
      'notes': 'synthetic-note',
      'draft_id': 'synthetic-draft',
      'future_schema_value': <String, Object>{'retain': true},
    };
    rows.single['payload_ciphertext'] = b64urlEncode(
      await aesGcmWrap(key, utf8.encode(jsonEncode(retainedPayload))),
    );
    final edited = await client.saveZkVaultSecureItem(
      authToken: 'synthetic-session',
      itemType: 'login',
      service: 'Synthetic renamed account',
      expectedOldService: 'Synthetic account',
      itemId: 42,
      fields: <String, dynamic>{
        'username': 'synthetic-user',
        'password': 'synthetic-updated-secret-marker',
      },
    );
    expect(edited, <String, dynamic>{'item_id': 42, 'created': false});
    expect(rows, hasLength(1));
    expect(rows.single['mutation_intent'], 'edit');
    expect(await unwrap(rows.single['service_ciphertext']),
        'Synthetic renamed account');
    final editedPayload = jsonDecode(
      await unwrap(rows.single['payload_ciphertext']),
    ) as Map;
    expect(editedPayload['notes'], 'synthetic-note');
    expect(editedPayload['draft_id'], 'synthetic-draft');
    expect(
        editedPayload['future_schema_value'], <String, Object>{'retain': true});
    expect((editedPayload['fields'] as Map)['password'],
        'synthetic-updated-secret-marker');
    expect(requests.where((r) => r.method == 'POST'), hasLength(2));
    expect(
        requests.any((r) => <String>{
              '/list-secure-items',
              '/get-secure-item',
              '/update-secure-item',
            }.contains(r.url.path)),
        isFalse);
  }, skip: !(kEnableKeylessSavedItemRead && kEnableKeylessSavedItemWrite));

  test('legacy duplicate and incomplete V2 inventory fail before mutation',
      () async {
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async =>
        b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
    final routes = <String>[];
    var incomplete = false;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        routes.add('${request.method} ${request.url.path}');
        if (request.url.path == '/vault/items/metadata') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'item_id': 7,
                    'item_type_ciphertext': await wrap('login'),
                    'service_ciphertext': await wrap('Synthetic account'),
                    'is_legacy': !incomplete,
                    'has_v2_payload': incomplete,
                  },
                ],
                'has_more': false,
              }),
              200);
        }
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        fail('Mutation or unexpected route ${request.url.path}');
      }),
    );
    await expectLater(
      client.saveZkVaultSecureItem(
        authToken: 'synthetic-session',
        itemType: 'login',
        service: '  synthetic   account  ',
        fields: const <String, dynamic>{'username': 'synthetic-user'},
      ),
      throwsA(isA<SavedItemConflictException>()),
    );
    incomplete = true;
    await expectLater(
      client.saveZkVaultSecureItem(
        authToken: 'synthetic-session',
        itemType: 'login',
        service: 'Another synthetic account',
        fields: const <String, dynamic>{'username': 'synthetic-user'},
      ),
      throwsFormatException,
    );
    expect(routes, isNot(contains('POST /vault/ciphertext/vault-items')));
    expect(routes, isNot(contains('POST /list-secure-items')));
  }, skip: !(kEnableKeylessSavedItemRead && kEnableKeylessSavedItemWrite));

  test('MVK loss and missing metadata route never fall back to PIN', () async {
    final routes = <String>[];
    var loseMvk = true;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        routes.add('${request.method} ${request.url.path}');
        if (request.url.path == '/vault/items/metadata') {
          if (loseMvk) ZkActiveMvk.clear();
          return loseMvk
              ? http.Response('{"records":[],"has_more":false}', 200)
              : http.Response('{"detail":"not_found"}', 404);
        }
        fail('Unexpected route ${request.url.path}');
      }),
    );
    Future<void> save() async {
      await client.saveZkVaultSecureItem(
        authToken: 'synthetic-session',
        itemType: 'login',
        service: 'Synthetic account',
        fields: const <String, dynamic>{'username': 'synthetic-user'},
      );
    }

    await expectLater(save(), throwsStateError);
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-saved-item-vault',
      vaultHandle: 'synthetic-saved-item-handle',
    );
    loseMvk = false;
    await expectLater(save(), throwsException);
    expect(routes, isNot(contains('POST /vault/ciphertext/vault-items')));
    expect(routes, isNot(contains('POST /list-secure-items')));
    expect(routes, isNot(contains('POST /update-secure-item')));
  }, skip: !(kEnableKeylessSavedItemRead && kEnableKeylessSavedItemWrite));

  test('write method remains disabled in ordinary builds', () async {
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((_) async => fail('Disabled write reached HTTP')),
    );
    await expectLater(
      client.saveZkVaultSecureItem(
        authToken: 'synthetic-session',
        itemType: 'login',
        service: 'Synthetic account',
        fields: const <String, dynamic>{},
      ),
      throwsStateError,
    );
  }, skip: kEnableKeylessSavedItemWrite);
}
