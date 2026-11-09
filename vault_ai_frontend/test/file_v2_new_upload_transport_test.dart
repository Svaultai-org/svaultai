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
  test('independent V2 writes can publish the same name twice', () async {
    // This documents the remaining duplicate/name-conflict parity gap. The
    // server sees only randomized IDs and ciphertext; signed create stays off
    // until a private duplicate decision can be made before publication.
    final mvk = SecretKey(List<int>.filled(32, 91));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final writer = FileV2Writer(mvk);
    final first = await writer.prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'same-name.txt',
      bytes: Uint8List(0),
    );
    final second = await writer.prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'same-name.txt',
      bytes: Uint8List(0),
    );
    final manifests = <String, Map<String, dynamic>>{};
    final published = <String>{};
    final writes = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        final path = request.url.path;
        if (request.method != 'GET') writes.add(request);
        if (request.method == 'GET' && path.endsWith('/manifest')) {
          final id = path.split('/')[3];
          final stored = manifests[id];
          return stored == null
              ? http.Response('{"detail":"not_found"}', 404)
              : http.Response(jsonEncode(<String, dynamic>{
                  ...stored,
                  'lifecycle_state': published.contains(id)
                      ? 'client_v2_ready' : 'file_v2_written',
                  'verification_state': published.contains(id)
                      ? 'client_verified' : 'unverified',
                }), 200);
        }
        if (request.method == 'POST' && path == '/vault/file-v2/manifest') {
          final body = Map<String, dynamic>.from(jsonDecode(request.body) as Map);
          manifests[body['file_id'] as String] = body;
          return http.Response('{"created":true}', 200);
        }
        if (request.method == 'POST' && path.endsWith('/publish-new')) {
          final id = path.split('/')[3];
          published.add(id);
          return http.Response(jsonEncode(<String, Object>{
            'file_id': id,
            'status': 'published',
          }), 200);
        }
        fail('Unexpected private write ${request.method} $path');
      }),
    );
    for (final prepared in <PreparedNewFileV2>[first, second]) {
      await client.uploadNewV2File(
        authToken: 'synthetic-session',
        prepared: prepared,
        originalBytes: Uint8List(0),
        mvk: mvk,
      );
    }
    expect(first.fileId, isNot(second.fileId));
    expect(published, <String>{first.fileId, second.fileId});
    expect(writes.where((request) => request.url.path.endsWith('/publish-new')),
        hasLength(2));
    for (final request in writes) {
      expect(request.body, isNot(contains('same-name.txt')));
      expect(request.body, isNot(contains('"pin"')));
    }
  });

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
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final bytes = Uint8List.fromList(<int>[1]);
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'synthetic.bin',
      bytes: bytes,
    );
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response('{"detail":"file_v2_not_found"}', 404);
        }
        expect(request.url.path, '/vault/file-v2/manifest');
        return http.Response(
            jsonEncode(<String, dynamic>{
              'detail': <String, dynamic>{
                'code': 'vault_storage_limit_exceeded',
                'used_bytes': 10,
                'limit_bytes': 10,
              },
            }),
            413);
      }),
    );
    await expectLater(
        client.uploadNewV2File(
          authToken: 'synthetic-session',
          prepared: prepared,
          originalBytes: bytes,
          mvk: mvk,
        ),
        throwsA(isA<StorageLimitExceededException>()));
  });

  test('deferred encrypted chunks resume from verified server bytes', () async {
    final mvk = SecretKey(List<int>.filled(32, 74));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final source = Uint8List.fromList(utf8.encode('larger private source'));
    final prepared = await FileV2Writer(mvk, eagerLimitBytes: 1).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'private.bin',
      relativePath: 'Private/private.bin',
      bytes: source,
      chunkSize: 7,
    );
    expect(prepared.chunkCiphertexts, isEmpty);
    expect(prepared.chunkCount, 3);
    final chunks = <int, String>{};
    var manifestStored = false;
    var published = false;
    var firstChunkResponseLost = false;
    var publishCalls = 0;
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        final path = request.url.path;
        expect(request.body, isNot(contains('larger private source')));
        expect(request.body, isNot(contains('Private')));
        expect(request.body, isNot(contains('private.bin')));
        expect(request.body, isNot(contains('"pin"')));
        if (path.endsWith('/manifest') && request.method == 'GET') {
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
              : http.Response('{"detail":"not_found"}', 404);
        }
        if (path == '/vault/file-v2/manifest') {
          manifestStored = true;
          expect(jsonDecode(request.body)['chunk_count'], 3);
          return http.Response('{"created":true}', 200);
        }
        if (path.contains('/chunk/') && request.method == 'GET') {
          final index = int.parse(path.split('/').last);
          return chunks.containsKey(index)
              ? http.Response(
                  jsonEncode(<String, dynamic>{
                    'file_id': prepared.fileId,
                    'chunk_index': index,
                    'ciphertext': chunks[index],
                  }),
                  200)
              : http.Response('{"detail":"not_found"}', 404);
        }
        if (path == '/vault/file-v2/chunk') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          final index = body['chunk_index'] as int;
          chunks[index] = body['ciphertext'] as String;
          if (index == 0 && !firstChunkResponseLost) {
            firstChunkResponseLost = true;
            throw StateError('Synthetic lost response after chunk stored');
          }
          return http.Response('{"stored":true}', 200);
        }
        if (path.endsWith('/publish-new')) {
          publishCalls++;
          published = true;
          return http.Response(
              jsonEncode(<String, dynamic>{
                'file_id': prepared.fileId,
                'status': 'published',
              }),
              200);
        }
        fail('Unexpected private file request: ${request.method} $path');
      }),
    );
    await expectLater(
        client.uploadNewV2File(
          authToken: 'synthetic-session',
          prepared: prepared,
          originalBytes: source,
          mvk: mvk,
        ),
        throwsStateError);
    expect(chunks.keys, <int>{0});
    final originalFirstChunk = chunks[0]!;
    chunks[0] =
        '${originalFirstChunk[0] == 'A' ? 'B' : 'A'}${originalFirstChunk.substring(1)}';
    await expectLater(
      client.uploadNewV2File(
        authToken: 'synthetic-session',
        prepared: prepared,
        originalBytes: source,
        mvk: mvk,
      ),
      throwsStateError,
    );
    expect(publishCalls, 0);
    chunks[0] = originalFirstChunk;
    await client.uploadNewV2File(
      authToken: 'synthetic-session',
      prepared: prepared,
      originalBytes: source,
      mvk: mvk,
    );
    expect(chunks.keys, <int>{0, 1, 2});
    expect(publishCalls, 1);
    expect(requests.where((request) => request.method == 'PUT'), hasLength(3));
    expect(
        requests.any((request) => request.url.path == '/upload-file'), isFalse);
  });
}
