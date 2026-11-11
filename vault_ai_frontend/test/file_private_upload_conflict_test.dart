import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_private_versioned_name.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  test('private keep-both names preserve extensions and stay bounded', () {
    expect(privateVersionedFileName('photo.jpg', 2), 'photo (2).jpg');
    expect(privateVersionedFileName('receipt', 3), 'receipt (3)');
    expect(
        privateVersionedFileName('${List.filled(254, 'x').join()}.png', 2)
            .length,
        255);
    expect(() => privateVersionedFileName('photo.jpg', 101),
        throwsFormatException);
  });

  for (final code in <String>['duplicate_found', 'name_conflict']) {
    test('private $code discards invisible stage before user decision',
        () async {
      final mvk = SecretKey(List<int>.filled(32, 37));
      ZkActiveMvk.set(
        mvk: mvk,
        vaultId: 'synthetic-vault',
        vaultHandle: 'synthetic-handle',
      );
      addTearDown(ZkActiveMvk.clear);
      final prepared = await FileV2Writer(
        mvk,
        vaultId: 'synthetic-vault',
      ).prepare(
        fileId: FileV2Writer.newFileId(),
        fileName: 'private-name.txt',
        bytes: Uint8List(0),
      );
      var staged = false;
      var deleted = false;
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          expect(request.body, isNot(contains('private-name.txt')));
          expect(request.body, isNot(contains('"pin"')));
          final path = request.url.path;
          if (request.method == 'GET' && path.endsWith('/manifest')) {
            return staged
                ? http.Response(
                    jsonEncode(<String, dynamic>{
                      ...prepared.toManifestBody(),
                      'lifecycle_state': 'file_v2_written',
                      'verification_state': 'not_verified',
                    }),
                    200)
                : http.Response('{"detail":"file_v2_not_found"}', 404);
          }
          if (request.method == 'POST' && path == '/vault/file-v2/manifest') {
            staged = true;
            return http.Response('{"created":true}', 200);
          }
          if (request.method == 'POST' && path.endsWith('/publish-new')) {
            expect(staged, isTrue);
            return http.Response(
                jsonEncode(<String, Object>{
                  'detail': <String, Object>{
                    'code': code,
                    'existing_file_id': 'existing-file',
                  },
                }),
                409);
          }
          if (request.method == 'DELETE' &&
              path == '/vault/file-v2/${prepared.fileId}') {
            expect(staged, isTrue);
            staged = false;
            deleted = true;
            return http.Response(
                jsonEncode(<String, Object>{
                  'file_id': prepared.fileId,
                  'deleted': true,
                }),
                200);
          }
          fail('Unexpected ${request.method} $path');
        }),
      );
      final upload = client.uploadNewV2File(
        authToken: 'synthetic-session',
        prepared: prepared,
        originalBytes: Uint8List(0),
        mvk: mvk,
      );
      if (code == 'duplicate_found') {
        await expectLater(
            upload, throwsA(isA<DuplicateFoundUploadException>()));
      } else {
        await expectLater(upload, throwsA(isA<NameConflictUploadException>()));
      }
      expect(deleted, isTrue);
      expect(staged, isFalse);
    });
  }

  test('private name conflict retry uses fresh file and versioned name',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 38));
    final writer = FileV2Writer(mvk);
    final bytes = Uint8List.fromList(<int>[1, 2, 3]);
    final old = await writer.prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'photo.jpg',
      bytes: bytes,
    );
    var calls = 0;
    final queue = UploadQueueController(
      maxConcurrency: 1,
      action: (job, data, _) async {
        calls++;
        if (calls == 1) {
          job.preparedNewV2 = old;
          throw const NameConflictDecisionRequired(<String, dynamic>{
            'private_file_v2': true,
            'existing_file_id': 'existing-file',
          });
        }
        expect(job.privateNameVersion, 2);
        expect(job.preparedNewV2, isNull);
        expect(job.duplicateAction, 'keep_both');
        final next = await writer.prepare(
          fileId: FileV2Writer.newFileId(),
          fileName: privateVersionedFileName(job.name, job.privateNameVersion),
          bytes: data,
        );
        expect(next.fileId, isNot(old.fileId));
        final manifest = await FileV2Reader(
          mvk: mvk,
          get: (path) async => <String, dynamic>{
            ...next.toManifestBody(),
            'lifecycle_state': 'client_v2_ready',
            'verification_state': 'client_verified',
          },
        ).readManifest(next.fileId, requireReady: true);
        expect(manifest.fileName, 'photo (2).jpg');
        return UploadResult(fileId: next.fileId);
      },
      onNameConflict: (_, __) async => NameConflictDecision.keepBoth,
    );
    addTearDown(queue.dispose);
    final job = UploadJob(
      id: 'synthetic-name-conflict',
      name: 'photo.jpg',
      kind: 'file',
      size: bytes.length,
      readBytes: () async => bytes,
    );
    queue.enqueue(job);
    await queue.waitForIdle();
    expect(job.status, UploadJobStatus.uploaded);
    expect(calls, 2);
  });

  test('private duplicate keep-both retains verified ciphertext for retry',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 39));
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'same.bin',
      bytes: Uint8List(0),
    );
    var calls = 0;
    final queue = UploadQueueController(
      maxConcurrency: 1,
      action: (job, _, __) async {
        calls++;
        if (calls == 1) {
          job.preparedNewV2 = prepared;
          throw const DuplicateUploadDecisionRequired(<String, dynamic>{
            'private_file_v2': true,
            'existing_file_id': 'existing-file',
          });
        }
        expect(job.preparedNewV2, same(prepared));
        expect(job.duplicateAction, 'keep_both');
        expect(job.privateNameVersion, 0);
        return UploadResult(fileId: prepared.fileId);
      },
      onDuplicate: (_, __) async => DuplicateUploadDecision.keepBoth,
    );
    addTearDown(queue.dispose);
    final job = UploadJob(
      id: 'synthetic-duplicate',
      name: 'same.bin',
      kind: 'file',
      size: 0,
      readBytes: () async => Uint8List(0),
    );
    queue.enqueue(job);
    await queue.waitForIdle();
    expect(job.status, UploadJobStatus.uploaded);
    expect(calls, 2);
  });
}
