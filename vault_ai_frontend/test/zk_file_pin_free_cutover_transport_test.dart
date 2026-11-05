import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(ZkActiveMvk.clear);
  tearDown(ZkActiveMvk.clear);

  test(
    'cutover rejects every legacy PIN file request before network',
    () async {
      final mvk = SecretKey(List<int>.filled(32, 54));
      ZkActiveMvk.set(
        mvk: mvk,
        vaultId: 'synthetic-zk-vault',
        vaultHandle: 'synthetic-zk-handle',
      );
      final requests = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          requests.add(request);
          return http.Response('{}', 200);
        }),
      );
      final calls = <Future<Object?> Function()>[
        () => client.listVaultFiles(
          vaultName: '',
          pin: '123456',
          authToken: 'synthetic-session',
        ),
        () => client.downloadVaultFile(
          vaultName: '',
          fileId: 'synthetic-file',
          pin: '123456',
          authToken: 'synthetic-session',
        ),
        () => client.getDownloadManifest(
          vaultName: '',
          fileId: 'synthetic-file',
          pin: '123456',
          authToken: 'synthetic-session',
        ),
        () => client.initChunkedUpload(
          vaultName: '',
          pin: '123456',
          authToken: 'synthetic-session',
          filename: 'synthetic.bin',
          contentType: 'application/octet-stream',
          totalBytes: 1,
          chunkSize: 1,
        ),
        () => client.finalizeChunkedUpload(
          vaultName: '',
          pin: '123456',
          authToken: 'synthetic-session',
          fileId: 'synthetic-file',
        ),
        () => client.abortChunkedUpload(
          vaultName: '',
          pin: '123456',
          authToken: 'synthetic-session',
          fileId: 'synthetic-file',
        ),
        () => client.uploadVaultFile(
          vaultName: '',
          pin: '123456',
          authToken: 'synthetic-session',
          filename: 'synthetic.bin',
          fileBytes: Uint8List.fromList([1]),
        ),
      ];
      for (final call in calls) {
        await expectLater(call(), throwsStateError);
      }
      expect(requests, isEmpty);
    },
    skip: !kRequirePinFreeZkFiles,
  );

  test('legacy-only vault keeps its current file request shape', () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"files":[]}', 200);
      }),
    );
    final result = await client.listVaultFiles(
      vaultName: 'synthetic-legacy-vault',
      pin: '123456',
      authToken: 'synthetic-session',
    );
    expect(result['files'], isEmpty);
    expect(requests, hasLength(1));
    expect(requests.single.url.path, '/list-files');
    expect(jsonDecode(requests.single.body), <String, dynamic>{
      'vault_name': '',
      'pin': '123456',
    });
  });

  test('ZK V2 inventory sends only a trusted session GET', () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 54)),
      vaultId: 'synthetic-zk-vault',
      vaultHandle: 'synthetic-zk-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response(
          '{"records":[],"has_more":false,"next_after_file_id":""}',
          200,
        );
      }),
    );
    final result = await client.listZkFileMetadata(
      authToken: 'synthetic-session',
    );
    expect(result['files'], isEmpty);
    expect(requests, hasLength(1));
    expect(requests.single.method, 'GET');
    expect(requests.single.url.path, '/vault/files/metadata');
    expect(requests.single.body, isEmpty);
    expect(
      requests.single.headers['authorization'],
      'Bearer synthetic-session',
    );
  });
}
