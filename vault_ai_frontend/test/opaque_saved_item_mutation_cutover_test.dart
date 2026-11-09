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
  const pin = 'synthetic-pin-marker';
  final mvk = SecretKey(List<int>.filled(32, 51));

  void bindPrivate({bool offered = false}) {
    ZkPinFreeItemReadSession.instance.bind(
      sessionToken: token,
      offered: offered,
      privateVaultSession: true,
      privateVaultId: 'synthetic-vault',
      privateVaultHandle: 'synthetic-handle',
    );
  }

  setUp(() {
    SessionTermination.instance.resetForTests();
    SessionTermination.instance.bindSession(token);
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
    setApiClientDeviceId('');
  });

  Future<void> expectBothMutationsBlocked(VaultAIClient client,
      {String authToken = token}) async {
    await expectLater(
      client.updateVaultSecureItem(
        vaultName: 'Synthetic vault',
        oldService: 'Synthetic account',
        itemType: 'login',
        pin: pin,
        authToken: authToken,
        itemId: '42',
        fields: const <String, dynamic>{'username': 'new-user'},
      ),
      throwsStateError,
    );
    await expectLater(
      client.deleteVaultSecureItem(
        vaultName: 'Synthetic vault',
        service: 'Synthetic account',
        itemType: 'login',
        pin: pin,
        authToken: authToken,
        itemId: '42',
      ),
      throwsStateError,
    );
  }

  test('lost OPAQUE key cannot enter either raw-PIN mutation route', () async {
    bindPrivate();
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('A lost-key mutation reached ${request.url.path}');
      }),
    );
    await expectBothMutationsBlocked(client);
    await expectLater(
      client.tryZkVaultItemCiphertextUpsert(
        baseUrl: 'https://synthetic.example',
        authToken: token,
        itemType: 'login',
        service: 'Synthetic account',
        payload: const <String, dynamic>{},
      ),
      throwsStateError,
    );
    expect(requests, isEmpty);
  }, skip: !kEnableKeylessSavedItemRead);

  test('key loss during inventory cannot reach an edit or delete route',
      () async {
    bindPrivate();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.body, isNot(contains(pin)));
        expect(request.method, 'GET');
        expect(request.url.path, '/vault/ciphertext/vault-items');
        ZkActiveMvk.clear();
        return http.Response('[]', 200);
      }),
    );
    await expectLater(
      client.updateVaultSecureItem(
        vaultName: 'Synthetic vault',
        oldService: 'Synthetic account',
        itemType: 'login',
        pin: pin,
        authToken: token,
        createOnly: true,
      ),
      throwsStateError,
    );
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    await expectLater(
      client.deleteVaultSecureItem(
        vaultName: 'Synthetic vault',
        service: 'Synthetic account',
        itemType: 'login',
        pin: pin,
        authToken: token,
        itemId: '42',
      ),
      throwsStateError,
    );
    expect(requests, hasLength(2));
    expect(requests.every((request) => request.method == 'GET'), isTrue);
  }, skip: !kEnableKeylessSavedItemRead);

  test('a different vault key cannot authorize either mutation', () async {
    bindPrivate();
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'another-vault',
      vaultHandle: 'another-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('Wrong-vault mutation reached ${request.url.path}');
      }),
    );
    await expectBothMutationsBlocked(client);
    expect(requests, isEmpty);
  }, skip: !kEnableKeylessSavedItemRead);

  test('a locked read offer cannot reuse a lingering vault key for mutation',
      () async {
    bindPrivate(offered: true);
    ZkPinFreeItemReadSession.instance.lock();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('Locked mutation reached ${request.url.path}');
      }),
    );
    await expectBothMutationsBlocked(client);
    expect(requests, isEmpty);
  }, skip: !kEnableKeylessSavedItemRead);

  test('retagging the same key during write inventory blocks the POST',
      () async {
    bindPrivate();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.method, 'GET');
        expect(request.url.path, '/vault/ciphertext/vault-items');
        ZkActiveMvk.set(
          mvk: mvk,
          vaultId: 'another-vault',
          vaultHandle: 'another-handle',
        );
        return http.Response('[]', 200);
      }),
    );
    await expectLater(
      client.tryZkVaultItemCiphertextUpsert(
        baseUrl: 'https://synthetic.example',
        authToken: token,
        existingItemId: 42,
        itemType: 'login',
        service: 'Synthetic account',
        payload: const <String, dynamic>{
          'fields': <String, String>{'username': 'new-user'},
        },
      ),
      throwsStateError,
    );
    expect(requests.map((request) => request.method), <String>['GET']);
  }, skip: !(kEnableKeylessSavedItemRead && kEnableKeylessSavedItemWrite));

  test('signed mutation offer without its bound private session fails closed',
      () async {
    final offered = base64UrlEncode(<int>[
      4,
      8,
      0,
      ...List<int>.filled(48, 7),
    ]);
    expect(signedSavedItemMutationOfferedForToken(offered), isTrue);
    SessionTermination.instance.bindSession(offered);
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('Signed mutation reached ${request.url.path}');
      }),
    );
    await expectBothMutationsBlocked(client, authToken: offered);
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    await expectBothMutationsBlocked(client, authToken: offered);
    expect(requests, isEmpty);
  }, skip: !kEnableKeylessSavedItemRead);

  test('signed legacy deletion uses its proof-bound helper without a PIN body',
      () async {
    final offered = base64UrlEncode(<int>[
      4, 8, 1, ...List<int>.filled(48, 7),
    ]);
    SessionTermination.instance.bindSession(offered);
    ZkPinFreeItemReadSession.instance.bind(
      sessionToken: offered,
      offered: true,
      privateVaultSession: true,
      privateVaultId: 'synthetic-vault',
      privateVaultHandle: 'synthetic-handle',
    );
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async =>
        b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
    final requests = <http.Request>[];
    var deleted = false;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.method, 'GET');
        expect(request.body, isNot(contains(pin)));
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/vault/items/metadata') {
          return http.Response(jsonEncode(<String, dynamic>{
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
          }), 200);
        }
        fail('Unexpected route ${request.url.path}');
      }),
      legacyZkItemDeleter: ({required itemId, required itemType,
          required service}) async {
        expect(itemId, 42);
        expect(itemType, 'login');
        expect(service, 'Synthetic account');
        deleted = true;
      },
    );
    final result = await client.deleteVaultSecureItem(
      vaultName: 'Synthetic vault',
      service: 'Synthetic account',
      itemType: 'login',
      pin: pin,
      authToken: offered,
      itemId: '42',
    );
    expect(deleted, isTrue);
    expect(result, <String, dynamic>{'status': 'deleted', 'item_id': 42});
    expect(requests.map((request) => request.url.path), <String>[
      '/vault/ciphertext/vault-items',
      '/vault/items/metadata',
    ]);
  });

  test('missing OPAQUE key cannot revive old edit and delete routes',
      () async {
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('Missing-key mutation reached ${request.url.path}');
      }),
    );
    expect(
        await client.tryZkVaultItemCiphertextUpsert(
          baseUrl: 'https://synthetic.example',
          authToken: token,
          itemType: 'login',
          service: 'Synthetic account',
          payload: const <String, dynamic>{},
        ),
        isNull);
    await expectLater(client.updateVaultSecureItem(
      vaultName: 'Older vault',
      oldService: 'Synthetic account',
      itemType: 'login',
      pin: pin,
      authToken: token,
      itemId: '42',
    ), throwsStateError);
    await expectLater(client.deleteVaultSecureItem(
      vaultName: 'Older vault',
      service: 'Synthetic account',
      itemType: 'login',
      pin: pin,
      authToken: token,
      itemId: '42',
    ), throwsStateError);
    expect(requests, isEmpty);
  });
}
