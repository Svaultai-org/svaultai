import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const _readyFile = <String, dynamic>{
  'file_id': 'synthetic-ready-file',
  'file_size': 7,
  'lifecycle_state': 'client_v2_ready',
  'verification_state': 'client_verified',
};
const _olderFile = <String, dynamic>{
  'file_id': 'synthetic-older-file',
  'file_size': 3,
  'has_inline_ciphertext': true,
};

http.Response _metadata(List<Map<String, dynamic>> records) => http.Response(
      jsonEncode(<String, dynamic>{
        'records': records,
        'has_more': false,
      }),
      200,
    );

void main() {
  setUp(() {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 41)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(ZkActiveMvk.clear);

  test('concurrent V2 delete refreshes metadata and keeps older file',
      () async {
    var metadataReads = 0;
    var v2Reads = 0;
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        if (request.url.path == '/vault/files/metadata') {
          metadataReads++;
          return _metadata(metadataReads == 1
              ? <Map<String, dynamic>>[_readyFile, _olderFile]
              : <Map<String, dynamic>>[_olderFile]);
        }
        if (request.url.path == '/vault/file-v2') {
          v2Reads++;
          return http.Response('{"files":[]}', 200);
        }
        fail('Unexpected route: ${request.url.path}');
      }),
    );

    final result = await client.listZkVaultFilesWithRetiredV2(
      authToken: 'synthetic-session',
      requireLegacyComplete: true,
    );
    final files = result['files'] as List;
    expect(files, hasLength(1));
    expect((files.single as Map)['id'], 'synthetic-older-file');
    expect(metadataReads, 2);
    expect(v2Reads, 1);
    expect(paths, <String>[
      '/vault/files/metadata',
      '/vault/file-v2',
      '/vault/files/metadata',
    ]);
  });

  test('persistent missing ready copy fails without hiding it', () async {
    var metadataReads = 0;
    var v2Reads = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        if (request.url.path == '/vault/files/metadata') {
          metadataReads++;
          return _metadata(<Map<String, dynamic>>[_readyFile, _olderFile]);
        }
        if (request.url.path == '/vault/file-v2') {
          v2Reads++;
          return http.Response('{"files":[]}', 200);
        }
        fail('Unexpected route: ${request.url.path}');
      }),
    );

    await expectLater(
      client.listZkVaultFilesWithRetiredV2(
        authToken: 'synthetic-session',
      ),
      throwsA(isA<FormatException>().having(
        (error) => error.message,
        'message',
        'Private file inventory changed',
      )),
    );
    expect(metadataReads, 2);
    expect(v2Reads, 2);
  });

  test('manifest deleted after V2 list gets one fresh inventory', () async {
    var metadataReads = 0;
    var manifestReads = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        if (request.url.path == '/vault/files/metadata') {
          metadataReads++;
          return _metadata(metadataReads == 1
              ? <Map<String, dynamic>>[_readyFile, _olderFile]
              : <Map<String, dynamic>>[_olderFile]);
        }
        if (request.url.path == '/vault/file-v2') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'files': <Map<String, dynamic>>[_readyFile],
              }),
              200);
        }
        if (request.url.path ==
            '/vault/file-v2/synthetic-ready-file/manifest') {
          manifestReads++;
          return http.Response('{"detail":"file_v2_not_found"}', 404);
        }
        fail('Unexpected route: ${request.url.path}');
      }),
    );

    final result = await client.listZkVaultFilesWithRetiredV2(
      authToken: 'synthetic-session',
    );
    expect((result['files'] as List).single['id'], 'synthetic-older-file');
    expect(metadataReads, 2);
    expect(manifestReads, 1);
  });

  test('V2 server failure does not fall back to an incomplete file list',
      () async {
    var metadataReads = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.method, 'GET');
        if (request.url.path == '/vault/files/metadata') {
          metadataReads++;
          return _metadata(<Map<String, dynamic>>[_readyFile, _olderFile]);
        }
        if (request.url.path == '/vault/file-v2') {
          return http.Response('{"detail":"unavailable"}', 500);
        }
        fail('Unexpected route: ${request.url.path}');
      }),
    );

    await expectLater(
      client.listZkVaultFilesWithRetiredV2(
        authToken: 'synthetic-session',
      ),
      throwsA(isA<FileV2ReadException>().having(
        (error) => error.statusCode,
        'statusCode',
        500,
      )),
    );
    expect(metadataReads, 1);
  });
}
