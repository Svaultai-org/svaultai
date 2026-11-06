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
  setUp(() {
    SessionTermination.instance.resetForTests();
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
  });

  test(
    'authenticated OPAQUE offer chooses PIN-free legacy list and detail',
    () async {
      SessionTermination.instance.bindSession('opaque-session');
      ZkPinFreeItemReadSession.instance.bind(
        sessionToken: 'opaque-session',
        offered: true,
      );
      final mvk = SecretKey(List<int>.filled(32, 39));
      ZkActiveMvk.set(
        mvk: mvk,
        vaultId: 'synthetic-vault',
        vaultHandle: 'synthetic-handle',
      );
      final key = await VaultKeyHierarchy(mvk).metadataKey();
      Future<String> wrap(String value) async =>
          b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
      final seen = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          seen.add(request);
          expect(request.headers['authorization'], 'Bearer opaque-session');
          expect(request.body, isNot(contains('raw-pin-marker')));
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
        pin: 'raw-pin-marker',
        authToken: 'opaque-session',
      );
      expect((listed['items'] as List).single['service'], 'Synthetic account');
      final detail = await client.getVaultSecureItem(
        vaultName: 'synthetic-vault',
        service: 'Synthetic account',
        itemType: 'login',
        itemId: '42',
        pin: 'raw-pin-marker',
        authToken: 'opaque-session',
      );
      expect(detail['fields'], <String, String>{'username': 'synthetic-user'});
      expect(seen.every((request) => request.method == 'GET'), isTrue);
    },
  );

  test(
    'a locked or stale offered session cannot retry a raw PIN route',
    () async {
      SessionTermination.instance.bindSession('opaque-session');
      ZkPinFreeItemReadSession.instance.bind(
        sessionToken: 'opaque-session',
        offered: true,
      );
      ZkPinFreeItemReadSession.instance.lock();
      var requests = 0;
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests++;
          return http.Response('{}', 200);
        }),
      );
      await expectLater(
        client.listVaultSecureItems(
          vaultName: 'synthetic-vault',
          pin: 'raw-pin-marker',
          authToken: 'opaque-session',
        ),
        throwsStateError,
      );
      await expectLater(
        client.getVaultSecureItem(
          vaultName: 'synthetic-vault',
          service: 'Synthetic account',
          itemType: 'login',
          pin: 'raw-pin-marker',
          authToken: 'opaque-session',
        ),
        throwsStateError,
      );
      expect(requests, 0);
      SessionTermination.instance.bindSession('replacement-session');
      expect(ZkPinFreeItemReadSession.instance.activeForToken('opaque-session'), isFalse);
      await expectLater(
        client.listVaultSecureItems(
          vaultName: 'synthetic-vault', pin: 'raw-pin-marker',
          authToken: 'opaque-session',
        ),
        throwsA(isA<StaleSessionResponseException>()),
      );
      expect(requests, 0);
      ZkPinFreeItemReadSession.instance.clear();
      final legacy = await client.listVaultSecureItems(
        vaultName: 'older-vault',
        pin: 'older-pin',
        authToken: 'replacement-session',
      );
      expect(legacy, isA<Map<String, dynamic>>());
      expect(requests, 1);
    },
  );

  test('server flag drift and key loss never retry a raw PIN route', () async {
    SessionTermination.instance.bindSession('opaque-session');
    ZkPinFreeItemReadSession.instance.bind(
      sessionToken: 'opaque-session',
      offered: true,
    );
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 39)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final paths = <String>[];
    final drifted = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.body, isNot(contains('raw-pin-marker')));
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/vault/items/metadata') {
          return http.Response('{}', 404);
        }
        fail('Raw-PIN fallback reached ${request.url.path}');
      }),
    );
    await expectLater(
        drifted.listVaultSecureItems(
          vaultName: 'synthetic-vault',
          pin: 'raw-pin-marker',
          authToken: 'opaque-session',
        ),
        throwsException);
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
        lostKey.listVaultSecureItems(
          vaultName: 'synthetic-vault',
          pin: 'raw-pin-marker',
          authToken: 'opaque-session',
        ),
        throwsStateError);
    expect(paths, <String>['/vault/ciphertext/vault-items']);
  });
}
