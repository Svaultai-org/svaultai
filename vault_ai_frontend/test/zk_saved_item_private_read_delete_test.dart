import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 68));
  setUp(() {
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkActiveMvk.clear();
    setApiClientDeviceId('');
  });

  Future<Map<String, dynamic>> row() async {
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async =>
        b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
    return <String, dynamic>{
      'item_id': 42,
      'item_type_ciphertext': await wrap('login'),
      'service_ciphertext': await wrap('Synthetic account'),
      'payload_ciphertext': await wrap(jsonEncode({
        'fields': {
          'username': 'synthetic-user',
          'password': 'synthetic-secret'
        },
      })),
    };
  }

  test('selected V2 view and delete use only MVK GET and bodyless DELETE',
      () async {
    final encrypted = await row();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        if (request.method == 'GET') {
          return http.Response(jsonEncode([encrypted]), 200);
        }
        expect(request.method, 'DELETE');
        expect(request.url.path, '/vault/ciphertext/vault-items/42');
        expect(request.body, isEmpty);
        return http.Response('{"status":"deleted","item_id":42}', 200);
      }),
    );
    final selected = await client.getZkVaultSecureItemOnly(
      authToken: 'synthetic-session',
      service: 'Synthetic account',
      itemType: 'login',
      itemId: '42',
    );
    expect((selected['fields'] as Map)['password'], 'synthetic-secret');
    final deleted = await client.deleteZkVaultSecureItemOnly(
      authToken: 'synthetic-session',
      service: 'Synthetic account',
      itemType: 'login',
      itemId: '42',
    );
    expect(deleted['status'], 'deleted');
    expect(requests.map((request) => '${request.method} ${request.url.path}'), [
      'GET /vault/ciphertext/vault-items',
      'GET /vault/ciphertext/vault-items',
      'DELETE /vault/ciphertext/vault-items/42',
    ]);
    for (final request in requests) {
      expect(request.body, isNot(contains('synthetic-secret')));
      expect(request.body, isNot(contains('"pin"')));
    }
  }, skip: !kEnableKeylessSavedItemRead);

  test('legacy-only or mismatched selection cannot reach delete', () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.method, 'GET');
        return http.Response('[]', 200);
      }),
      legacyZkItemReader: (_) async =>
          throw StateError('legacy reader must not run'),
    );
    await expectLater(
      client.getZkVaultSecureItemOnly(
        authToken: 'synthetic-session',
        service: 'Legacy account',
        itemType: 'login',
        itemId: '77',
      ),
      throwsStateError,
    );
    await expectLater(
      client.deleteZkVaultSecureItemOnly(
        authToken: 'synthetic-session',
        service: 'Legacy account',
        itemType: 'login',
        itemId: '77',
      ),
      throwsStateError,
    );
    expect(requests.every((request) => request.method == 'GET'), isTrue);
    expect(
        requests.every(
            (request) => request.url.path == '/vault/ciphertext/vault-items'),
        isTrue);
  }, skip: !kEnableKeylessSavedItemRead);

  test('concurrent backend update-required guard stops after one DELETE',
      () async {
    final encrypted = await row();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        return request.method == 'GET'
            ? http.Response(jsonEncode([encrypted]), 200)
            : http.Response('{"detail":{"code":"update_app_required"}}', 409);
      }),
    );
    await expectLater(
      client.deleteZkVaultSecureItemOnly(
        authToken: 'synthetic-session',
        service: 'Synthetic account',
        itemType: 'login',
        itemId: '42',
      ),
      throwsA(isA<SavedItemUpdateRequiredException>()),
    );
    expect(
        requests.where((request) => request.method == 'DELETE'), hasLength(1));
    expect(requests.any((request) => request.url.path == '/delete-secure-item'),
        isFalse);
  }, skip: !kEnableKeylessSavedItemRead);

  test('MVK loss after list blocks delete', () async {
    final encrypted = await row();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        ZkActiveMvk.clear();
        return http.Response(jsonEncode([encrypted]), 200);
      }),
    );
    await expectLater(
      client.deleteZkVaultSecureItemOnly(
        authToken: 'synthetic-session',
        service: 'Synthetic account',
        itemType: 'login',
        itemId: '42',
      ),
      throwsStateError,
    );
    expect(requests, hasLength(1));
    expect(requests.single.method, 'GET');
  }, skip: !kEnableKeylessSavedItemRead);
}
