import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_item_read_session.dart';

void main() {
  const token = 'synthetic-opaque-session';
  const pin = 'raw-pin-marker';

  setUp(() {
    SessionTermination.instance.resetForTests();
    SessionTermination.instance.bindSession(token);
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 39)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
  });

  test(
    'unoffered OPAQUE session lists and reads older item without raw PIN',
    () async {
      final key = await VaultKeyHierarchy(ZkActiveMvk.current()!).metadataKey();
      Future<String> wrap(String value) async =>
          b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
      final requests = <http.Request>[];
      var detailReads = 0;
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          expect(request.headers['authorization'], 'Bearer $token');
          expect(request.body, isNot(contains(pin)));
          if (request.url.path == '/vault/ciphertext/vault-items') {
            return http.Response('[]', 200);
          }
          if (request.url.path == '/vault/items/metadata') {
            return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'item_id': 42,
                    'item_type_ciphertext': await wrap('login'),
                    'service_ciphertext': await wrap('Synthetic account'),
                    'is_legacy': true,
                    'has_v2_payload': false,
                  },
                ],
                'has_more': false,
                'next_after_item_id': 42,
              }),
              200,
            );
          }
          fail('Unexpected route ${request.url.path}');
        }),
        legacyZkItemReader: (id) async {
          detailReads++;
          expect(id, 42);
          return <String, dynamic>{
            'id': id,
            'item_type': 'login',
            'service': 'Synthetic account',
            'fields': <String, String>{'username': 'synthetic-user'},
          };
        },
      );

      final listed = await client.listVaultSecureItems(
        vaultName: 'synthetic-vault',
        pin: pin,
        authToken: token,
      );
      expect((listed['items'] as List).single['service'], 'Synthetic account');
      final detail = await client.getVaultSecureItem(
        vaultName: 'synthetic-vault',
        pin: pin,
        authToken: token,
        service: 'Synthetic account',
        itemType: 'login',
        itemId: '42',
      );
      expect(detail['fields'], <String, String>{'username': 'synthetic-user'});
      expect(detailReads, 1);
      expect(requests.map((r) => r.url.path), <String>[
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
      ]);
      expect(requests.every((r) => r.method == 'GET'), isTrue);
    },
    skip: !kEnableKeylessSavedItemRead,
  );

  test(
    'missing trusted metadata route cannot retry the old PIN list',
    () async {
      final paths = <String>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          paths.add(request.url.path);
          expect(request.body, isNot(contains(pin)));
          if (request.url.path == '/vault/ciphertext/vault-items') {
            return http.Response('[]', 200);
          }
          return http.Response('{"detail":"not_found"}', 404);
        }),
      );
      await expectLater(
        client.listVaultSecureItems(
          vaultName: 'synthetic-vault',
          pin: pin,
          authToken: token,
        ),
        throwsException,
      );
      await expectLater(
        client.getVaultSecureItem(
          vaultName: 'synthetic-vault',
          pin: pin,
          authToken: token,
          service: 'Synthetic account',
          itemType: 'login',
        ),
        throwsException,
      );
      expect(paths, <String>[
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
      ]);
    },
    skip: !kEnableKeylessSavedItemRead,
  );

  test(
    'no detail adapter or lost key never sends the raw PIN detail',
    () async {
      final paths = <String>[];
      final noReader = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          paths.add(request.url.path);
          if (request.url.path == '/vault/ciphertext/vault-items') {
            return http.Response('[]', 200);
          }
          if (request.url.path == '/vault/items/metadata') {
            return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'item_id': 42,
                    'item_type': 'login',
                    'service': 'Synthetic account',
                    'is_legacy': true,
                  },
                ],
                'has_more': false,
                'next_after_item_id': 42,
              }),
              200,
            );
          }
          fail('Raw PIN route reached ${request.url.path}');
        }),
      );
      await expectLater(
        noReader.getVaultSecureItem(
          vaultName: 'synthetic-vault',
          pin: pin,
          authToken: token,
          service: 'Synthetic account',
          itemType: 'login',
          itemId: '42',
        ),
        throwsStateError,
      );
      expect(paths, <String>[
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
      ]);

      paths.clear();
      final lostKey = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          paths.add(request.url.path);
          ZkActiveMvk.clear();
          return http.Response('[]', 200);
        }),
      );
      await expectLater(
        lostKey.getVaultSecureItem(
          vaultName: 'synthetic-vault',
          pin: pin,
          authToken: token,
          service: 'Synthetic account',
          itemType: 'login',
          itemId: '42',
        ),
        throwsStateError,
      );
      expect(paths, <String>['/vault/ciphertext/vault-items']);
    },
    skip: !kEnableKeylessSavedItemRead,
  );

  test('key loss in an unoffered private session cannot reopen PIN reads',
      () async {
    ZkPinFreeItemReadSession.instance.bind(
      sessionToken: token,
      offered: false,
      privateVaultSession: true,
    );
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"items":[]}', 200);
      }),
    );
    await expectLater(client.listVaultSecureItems(
      vaultName: 'synthetic-vault', pin: pin, authToken: token,
    ), throwsStateError);
    await expectLater(client.getVaultSecureItem(
      vaultName: 'synthetic-vault', pin: pin, authToken: token,
      service: 'Synthetic account', itemType: 'login',
    ), throwsStateError);
    expect(requests, isEmpty);

    // A later unrelated legacy-only session must keep its own route.
    SessionTermination.instance.bindSession('replacement-legacy-session');
    ZkPinFreeItemReadSession.instance.bind(
      sessionToken: 'replacement-legacy-session',
      offered: false,
    );
    expect(ZkPinFreeItemReadSession.instance.privateVaultForToken(token), isFalse);
    await client.listVaultSecureItems(
      vaultName: 'older-vault', pin: pin,
      authToken: 'replacement-legacy-session',
    );
    expect(requests.single.url.path, '/list-secure-items');
  });

  test(
    'legacy-only account retains its existing list and detail requests',
    () async {
      ZkActiveMvk.clear();
      final requests = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          if (request.url.path == '/list-secure-items') {
            return http.Response('{"items":[]}', 200);
          }
          if (request.url.path == '/get-secure-item') {
            return http.Response('{"service":"Synthetic account"}', 200);
          }
          fail('Unexpected route ${request.url.path}');
        }),
      );
      await client.listVaultSecureItems(
        vaultName: 'older-vault',
        pin: pin,
        authToken: token,
      );
      final detail = await client.getVaultSecureItem(
        vaultName: 'older-vault',
        pin: pin,
        authToken: token,
        service: 'Synthetic account',
        itemType: 'login',
      );
      expect(detail['service'], 'Synthetic account');
      expect(requests.map((r) => r.url.path), <String>[
        '/list-secure-items',
        '/get-secure-item',
      ]);
      expect(
        requests.every((r) => (jsonDecode(r.body) as Map)['pin'] == pin),
        isTrue,
      );
    },
  );
}
