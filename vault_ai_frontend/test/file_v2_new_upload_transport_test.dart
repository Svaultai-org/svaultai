import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  test('automatic queue retry retains one prepared encrypted file ID',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 67));
    final writer = FileV2Writer(mvk);
    final bytes = Uint8List.fromList(<int>[7, 8, 9]);
    String? firstId;
    final queue = UploadQueueController(
      maxConcurrency: 1,
      maxBackoff: Duration.zero,
      action: (job, data, progress) async {
        final prepared = job.preparedNewV2 ??= await writer.prepare(
          fileId: FileV2Writer.newFileId(),
          fileName: job.name,
          bytes: data,
        );
        firstId ??= prepared.fileId;
        expect(prepared.fileId, firstId);
        if (job.attempts == 1) {
          throw const TransientUploadException('synthetic interrupted request');
        }
        return UploadResult(fileId: prepared.fileId);
      },
    );
    addTearDown(queue.dispose);
    final job = UploadJob(
      id: 'synthetic-job',
      name: 'synthetic.bin',
      kind: 'file',
      size: bytes.length,
      readBytes: () async => bytes,
    );
    queue.enqueue(job);
    await queue.waitForIdle();
    expect(job.attempts, 2);
    expect(job.status, UploadJobStatus.uploaded);
    expect(job.uploadedFileId, firstId);
  });

  test('retry reuses one encrypted file and publishes only after readback',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 51));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
    addTearDown(ZkActiveMvk.clear);
    final plain = Uint8List.fromList(utf8.encode('synthetic-private-bytes'));
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'synthetic-private.txt',
      savedName: 'synthetic-title.txt',
      contentType: 'text/plain',
      bytes: plain,
      chunkSize: 8,
    );
    final writes = <http.Request>[];
    final chunks = <int, String>{};
    var manifestStored = false;
    var published = false;
    var publishCalls = 0;
    final mock = MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer synthetic-session');
      expect(request.headers['x-device-id'], 'synthetic-device');
      expect(request.headers['x-svaultai-file-v2-reader'],
          kFileV2ReaderCapability ? '1' : isNull);
      expect(request.body, isNot(contains('synthetic-private.txt')));
      expect(request.body, isNot(contains('synthetic-title.txt')));
      expect(request.body, isNot(contains('synthetic-private-bytes')));
      expect(request.body, isNot(contains('"pin"')));
      if (request.method != 'GET') writes.add(request);
      final path = request.url.path;
      if (path == '/vault/file-v2/${prepared.fileId}/manifest' &&
          request.method == 'GET') {
        return manifestStored
            ? http.Response(
                jsonEncode(<String, dynamic>{
                  ...prepared.toManifestBody(),
                  'lifecycle_state':
                      published ? 'client_v2_ready' : 'file_v2_written',
                  'verification_state':
                      published ? 'client_verified' : 'unverified',
                }),
                200)
            : http.Response('{"detail":"file_v2_not_found"}', 404);
      }
      if (path == '/vault/file-v2/manifest') {
        expect(request.method, 'POST');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['migrating_legacy'], isFalse);
        expect(body['manifest_ciphertext'], prepared.manifestCiphertext);
        manifestStored = true;
        return http.Response('{"created":true}', 200);
      }
      if (path.startsWith('/vault/file-v2/${prepared.fileId}/chunk/')) {
        final index = int.parse(path.split('/').last);
        return chunks.containsKey(index)
            ? http.Response(
                jsonEncode(<String, dynamic>{
                  'file_id': prepared.fileId,
                  'chunk_index': index,
                  'ciphertext': chunks[index],
                }),
                200)
            : http.Response('{"detail":"file_v2_chunk_not_found"}', 404);
      }
      if (path == '/vault/file-v2/chunk') {
        expect(request.method, 'PUT');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final index = body['chunk_index'] as int;
        chunks[index] = body['ciphertext'] as String;
        return http.Response('{"stored":true}', 200);
      }
      if (path == '/vault/file-v2/${prepared.fileId}/publish-new') {
        expect(jsonDecode(request.body), <String, dynamic>{'confirm': true});
        publishCalls++;
        published = true;
        if (publishCalls == 1) {
          throw StateError('synthetic lost publish response');
        }
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': prepared.fileId,
              'status': 'already_published',
            }),
            200);
      }
      if (path == '/vault/file-v2') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'files': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': prepared.fileId,
                  'lifecycle_state': 'client_v2_ready',
                  'verification_state': 'client_verified',
                },
              ],
            }),
            200);
      }
      if (path == '/vault/files/metadata') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': prepared.fileId,
                  'file_size': plain.length,
                  'lifecycle_state': 'client_v2_ready',
                  'verification_state': 'client_verified',
                },
              ],
              'has_more': false,
              'next_after_file_id': prepared.fileId,
            }),
            200);
      }
      if (path == '/vault/file-v2/${prepared.fileId}/delete-new') {
        expect(jsonDecode(request.body), <String, dynamic>{
          'confirm': true,
          'zk_proof_token': 'synthetic-one-use-proof',
        });
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': prepared.fileId,
              'deleted': true,
            }),
            200);
      }
      fail('Unexpected route $path');
    });
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: mock,
    );
    await expectLater(
        client.uploadNewV2File(
          authToken: 'synthetic-session',
          prepared: prepared,
          originalBytes: plain,
          mvk: mvk,
        ),
        throwsStateError);
    final retried = await client.uploadNewV2File(
      authToken: 'synthetic-session',
      prepared: prepared,
      originalBytes: plain,
      mvk: mvk,
    );
    expect(retried['status'], 'already_published');
    expect(writes.where((r) => r.url.path == '/vault/file-v2/manifest'),
        hasLength(1));
    expect(writes.where((r) => r.url.path == '/vault/file-v2/chunk'),
        hasLength(prepared.chunkCiphertexts.length));
    expect(publishCalls, 2);
    final listed = await client.listZkVaultFilesWithRetiredV2(
      authToken: 'synthetic-session',
    );
    final row = (listed['files'] as List).single as Map;
    expect(row['file_name'], 'synthetic-private.txt');
    expect(row['saved_name'], 'synthetic-title.txt');
    expect(row['v2_ready'], isTrue);
    expect(
        await client.isAvailableV2File(
          authToken: 'synthetic-session',
          fileId: prepared.fileId,
        ),
        isTrue);
    final downloaded = await client.downloadAvailableV2File(
      authToken: 'synthetic-session',
      fileId: prepared.fileId,
    );
    expect(downloaded.bytes, plain);
    await client.deleteNewV2File(
      authToken: 'synthetic-session',
      fileId: prepared.fileId,
      zkProofToken: 'synthetic-one-use-proof',
    );
    expect(writes.any((r) => r.url.path == '/download-file'), isFalse);
    expect(writes.any((r) => r.url.path == '/upload-file'), isFalse);
  });

  test('corrupt client readback blocks publish without a legacy fallback',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 59));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final plain = Uint8List.fromList(<int>[1, 2, 3]);
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'synthetic.bin',
      bytes: plain,
    );
    var publishCalls = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        final path = request.url.path;
        if (path.endsWith('/manifest') && request.method == 'GET') {
          return http.Response('{"detail":"file_v2_not_found"}', 404);
        }
        if (path == '/vault/file-v2/manifest') {
          return http.Response('{"created":true}', 200);
        }
        if (path.endsWith('/chunk/0')) {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'file_id': prepared.fileId,
                'chunk_index': 0,
                'ciphertext': 'invalid',
              }),
              200);
        }
        if (path.endsWith('/publish-new')) publishCalls++;
        fail('Unexpected route $path');
      }),
    );
    await expectLater(
        client.uploadNewV2File(
          authToken: 'synthetic-session',
          prepared: prepared,
          originalBytes: plain,
          mvk: mvk,
        ),
        throwsFormatException);
    expect(publishCalls, 0);
  });

  test('MVK loss during upload stops before any legacy request', () async {
    final mvk = SecretKey(List<int>.filled(32, 61));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final bytes = Uint8List.fromList(<int>[4, 5, 6]);
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'synthetic.bin',
      bytes: bytes,
    );
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        ZkActiveMvk.clear();
        return http.Response('{"detail":"file_v2_not_found"}', 404);
      }),
    );
    await expectLater(
        client.uploadNewV2File(
          authToken: 'synthetic-session',
          prepared: prepared,
          originalBytes: bytes,
          mvk: mvk,
        ),
        throwsStateError);
    expect(paths, <String>[
      '/vault/file-v2/${prepared.fileId}/manifest',
    ]);
  });

  test('quota rejection retains a typed storage limit for the upload queue',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 73));
    ZkActiveMvk.set(
      mvk: mvk, vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final bytes = Uint8List.fromList(<int>[1]);
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'synthetic.bin', bytes: bytes,
    );
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response('{"detail":"file_v2_not_found"}', 404);
        }
        expect(request.url.path, '/vault/file-v2/manifest');
        return http.Response(jsonEncode(<String, dynamic>{
          'detail': <String, dynamic>{
            'code': 'vault_storage_limit_exceeded',
            'used_bytes': 10,
            'limit_bytes': 10,
          },
        }), 413);
      }),
    );
    await expectLater(client.uploadNewV2File(
      authToken: 'synthetic-session', prepared: prepared,
      originalBytes: bytes, mvk: mvk,
    ), throwsA(isA<StorageLimitExceededException>()));
  });
}
