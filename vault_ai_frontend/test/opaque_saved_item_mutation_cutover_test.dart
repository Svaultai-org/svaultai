import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
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

  test('unoffered legacy-only bearer retains its old edit and delete routes',
      () async {
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['pin'], pin);
        expect(request.headers['authorization'], 'Bearer $token');
        return http.Response('{"status":"ok"}', 200);
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
    final edited = await client.updateVaultSecureItem(
      vaultName: 'Older vault',
      oldService: 'Synthetic account',
      itemType: 'login',
      pin: pin,
      authToken: token,
      itemId: '42',
    );
    final deleted = await client.deleteVaultSecureItem(
      vaultName: 'Older vault',
      service: 'Synthetic account',
      itemType: 'login',
      pin: pin,
      authToken: token,
      itemId: '42',
    );
    expect(edited['status'], 'ok');
    expect(deleted['status'], 'ok');
    expect(requests.map((request) => request.url.path), <String>[
      '/update-secure-item',
      '/delete-secure-item',
    ]);
  });
}
