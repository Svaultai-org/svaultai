import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  const pin = 'synthetic-pin-marker';
  const token = 'synthetic-session';

  setUp(() {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 37)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(ZkActiveMvk.clear);

  test(
    'ZK index omits PIN and keeps hidden wallet records out',
    () async {
      final key = await VaultKeyHierarchy(ZkActiveMvk.current()!).metadataKey();
      Future<String> wrap(String value) async =>
          b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
      final requests = <http.Request>[];
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
              jsonEncode({
                'records': [
                  {
                    'item_id': 1,
                    'item_type': 'login',
                    'service': 'Saved login',
                    'is_legacy': true,
                  },
                  {
                    'item_id': 2,
                    'item_type': 'crypto_wallet_account',
                    'service': 'Internal wallet',
                    'is_legacy': true,
                  },
                  {
                    'item_id': 3,
                    'item_type_ciphertext': await wrap('crypto_wallet_account'),
                    'service_ciphertext': await wrap(
                      'Encrypted internal wallet',
                    ),
                    'is_legacy': true,
                  },
                  {
                    'item_id': 4,
                    'item_type_ciphertext': await wrap('crypto_note'),
                    'service_ciphertext': await wrap('Visible crypto note'),
                    'is_legacy': true,
                  },
                ],
                'has_more': false,
                'next_after_item_id': 4,
              }),
              200,
            );
          }
          fail('Unexpected route ${request.url.path}');
        }),
      );
      final listed = await client.listVaultSecureItems(
        vaultName: 'Synthetic',
        pin: pin,
        authToken: token,
      );
      final rows = (listed['items'] as List).whereType<Map>().toList();
      expect(rows.map((row) => row['id']), [1, 4]);
      expect(rows.map((row) => row['service']), [
        'Saved login',
        'Visible crypto note',
      ]);
      expect(requests.map((request) => request.url.path), [
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
      ]);
      expect(requests.every((request) => request.method == 'GET'), isTrue);
    },
    skip: !kEnableZkPinFreeSavedItemIndex,
  );

  test(
    'missing ZK inventory fails closed without a PIN fallback',
    () async {
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
          vaultName: 'Synthetic',
          pin: pin,
          authToken: token,
        ),
        throwsException,
      );
      expect(paths, contains('/vault/items/metadata'));
      expect(paths, isNot(contains('/list-secure-items')));
    },
    skip: !kEnableZkPinFreeSavedItemIndex,
  );

  test(
    'generated draft detects a legacy duplicate without a PIN list',
    () async {
      final requests = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          expect(request.body, isNot(contains(pin)));
          if (request.url.path == '/vault/ciphertext/vault-items') {
            return http.Response('[]', 200);
          }
          if (request.url.path == '/vault/items/metadata') {
            return http.Response(
                jsonEncode({
                  'records': [
                    {
                      'item_id': 7,
                      'item_type': 'login',
                      'service': 'Saved login',
                      'is_legacy': true,
                    },
                  ],
                  'has_more': false,
                  'next_after_item_id': 7,
                }),
                200);
          }
          fail('Unexpected write ${request.url.path}');
        }),
      );
      await expectLater(
        client.saveGeneratedLoginDraftCiphertext(
          authToken: token,
          pin: pin,
          draftId: 'synthetic-draft',
          service: 'Saved login',
          fields: {'username': 'synthetic-user'},
        ),
        throwsA(isA<SavedItemConflictException>()),
      );
      expect(requests.every((request) => request.method == 'GET'), isTrue);
      expect(requests.map((request) => request.url.path), [
        '/vault/ciphertext/vault-items',
        '/vault/items/metadata',
      ]);
    },
    skip: !kEnableZkPinFreeSavedItemIndex,
  );

  test(
    'legacy-only vault retains its existing PIN list route',
    () async {
      ZkActiveMvk.clear();
      final requests = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          return http.Response('{"items":[]}', 200);
        }),
      );
      await client.listVaultSecureItems(
        vaultName: 'Synthetic',
        pin: pin,
        authToken: token,
      );
      expect(requests.single.url.path, '/list-secure-items');
      expect((jsonDecode(requests.single.body) as Map)['pin'], pin);
    },
    skip: !kEnableZkPinFreeSavedItemIndex,
  );
}
