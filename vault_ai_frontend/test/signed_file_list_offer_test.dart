import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/private_content_pin_guard.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';

void main() {
  String signedListToken() => base64Url
      .encode(<int>[3, 2, ...List<int>.filled(48, 7)])
      .replaceAll('=', '');

  String signedListAndDownloadToken() => base64Url
      .encode(<int>[3, 6, ...List<int>.filled(48, 7)])
      .replaceAll('=', '');

  setUp(() {
    SessionTermination.instance.resetForTests();
    ZkPinFreeFileSession.instance.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkPinFreeFileSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
  });

  test('signed file offers reject old related request before HTTP', () async {
    final token = signedListAndDownloadToken();
    SessionTermination.instance.bindSession(token);
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.fetchRelatedFiles(
        fileId: 'older-file',
        pin: 'synthetic-raw-pin',
        authToken: token,
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    expect(sent, isEmpty);
  });

  test(
    'signed offer lists encrypted metadata without a local offer marker',
    () async {
      final token = signedListToken();
      SessionTermination.instance.bindSession(token);
      expect(ZkPinFreeFileSession.instance.listOfferedForToken(token), isFalse);
      final mvk = SecretKey(List<int>.filled(32, 47));
      ZkActiveMvk.set(
        mvk: mvk,
        vaultId: 'synthetic-vault',
        vaultHandle: 'synthetic-handle',
      );
      final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
      final name = b64urlEncode(
        await aesGcmWrap(metadataKey, utf8.encode('private-file.txt')),
      );
      final requests = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          expect(request.method, 'GET');
          expect(request.url.path, '/vault/files/metadata');
          expect(
            request.url.queryParameters['require_legacy_complete'],
            'true',
          );
          expect(request.headers['authorization'], 'Bearer $token');
          expect(request.body, isEmpty);
          return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': 'synthetic-file',
                  'file_name_ciphertext': name,
                  'file_size': 3,
                  'storage_mode': 'inline',
                  'upload_status': 'complete',
                  'created_at': '2026-11-08T10:00:00Z',
                },
              ],
              'has_more': false,
            }),
            200,
          );
        }),
      );

      final result = await client.listVaultFiles(
        vaultName: 'raw-vault-name-marker',
        pin: 'raw-pin-marker',
        authToken: token,
      );
      final file = (result['files'] as List).single as Map<String, dynamic>;
      expect(file['file_name'], 'private-file.txt');
      expect(requests, hasLength(1));
      expect(
        requests.single.url.toString(),
        isNot(contains('raw-vault-name-marker')),
      );
      expect(requests.single.url.toString(), isNot(contains('raw-pin-marker')));
    },
  );

  test('signed offer fails closed without a key or metadata route', () async {
    final token = signedListToken();
    SessionTermination.instance.bindSession(token);
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.url.path, '/vault/files/metadata');
        expect(request.body, isEmpty);
        return http.Response('{}', 404);
      }),
    );
    Future<Map<String, dynamic>> list() => client.listVaultFiles(
      vaultName: 'raw-vault-name-marker',
      pin: 'raw-pin-marker',
      authToken: token,
    );

    await expectLater(list(), throwsStateError);
    expect(requests, isEmpty);
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 47)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    await expectLater(list(), throwsStateError);
    expect(requests, hasLength(1));
    expect(requests.single.url.path, '/vault/files/metadata');
  });
}
