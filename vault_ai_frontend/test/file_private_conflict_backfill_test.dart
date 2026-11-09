import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_private_conflict_backfill.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/legacy_content_migration_stager.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 45));
  const vaultId = '123e4567-e89b-12d3-a456-426614174000';
  const bearer = 'synthetic-bearer';
  const fileId = 'v2-AAAAAAAAAAAAAAAAAAAAAAAAAAA';
  const snapshot = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
  final evidence = LegacyStageReadbackEvidence(
    isFile: true,
    recordId: fileId,
    sourceSnapshot: snapshot,
    readbackReceipt: 'fr1.9999999999.${List<String>.filled(43, 'B').join()}.${List<String>.filled(43, 'C').join()}',
    receiptExpiresAt: DateTime.now().toUtc().add(const Duration(minutes: 5)),
  );
  final bytes = Uint8List.fromList(utf8.encode('synthetic private file'));

  Future<({PreparedNewFileV2 prepared, Map<String, dynamic> manifest})>
      preparedFile() async {
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: fileId,
      fileName: 'Private Photo.JPG',
      savedName: 'Beach Portrait',
      bytes: bytes,
      chunkSize: 1024,
    );
    return (
      prepared: prepared,
      manifest: <String, dynamic>{
        ...prepared.toManifestBody(),
        'lifecycle_state': 'file_v2_written',
        'verification_state': 'not_verified',
      },
    );
  }

  test('owner sends only blinded tokens after same-session readback', () async {
    final file = await preparedFile();
    final posts = <Map<String, dynamic>>[];
    final app = FilePrivateConflictBackfill(
      enabled: true,
      bearer: bearer,
      vaultId: vaultId,
      sessionEpoch: 5,
      mvk: mvk,
      currentBearer: () => bearer,
      currentVaultId: () => vaultId,
      currentSessionEpoch: () => 5,
      currentMvk: () => mvk,
      proofProvider: () async => 'opaque-action-proof',
      get: (token, path) async {
        expect(token, bearer);
        if (path.endsWith('/file-staged/$fileId')) {
          return <String, dynamic>{
            'file_id': fileId,
            'source_snapshot': snapshot,
            'total_bytes': bytes.length,
            'chunk_count': 1,
            'readback_receipt': evidence.readbackReceipt,
            'v2_ciphertext_sha256': List<String>.filled(64, 'f').join(),
          };
        }
        if (path.endsWith('/manifest')) return file.manifest;
        if (path.endsWith('/chunk/0')) {
          return <String, dynamic>{
            'file_id': fileId, 'chunk_index': 0,
            'ciphertext': file.prepared.chunkCiphertexts.single,
          };
        }
        throw StateError('unexpected GET');
      },
      post: (token, path, body) async {
        expect(token, bearer);
        posts.add(<String, dynamic>{'path': path, ...body});
        if (path.endsWith('/index-complete')) {
          return <String, dynamic>{
            'indexed': true,
            'inventory_generation': 2,
            'private_upload_enabled': false,
          };
        }
        return <String, dynamic>{
          'file_id': fileId, 'source_snapshot': snapshot, 'indexed': true,
        };
      },
    );
    await app.indexVerifiedLegacyFile(evidence);
    expect(await app.finishIndex(), 2);
    expect(posts.length, 2);
    final body = posts.first;
    expect(body['path'], '/vault/file-conflict/index-legacy');
    expect(body['content_token'], isA<String>());
    expect((body['content_token'] as String).length, 43);
    expect(body['name_tokens'], isA<List<String>>());
    expect((body['name_tokens'] as List).length, 2);
    expect(body.toString(), isNot(contains('Private Photo')));
    expect(body.toString(), isNot(contains('Beach Portrait')));
    expect(body.toString(), isNot(contains('synthetic private file')));
    expect(body.toString(), isNot(contains('123456')));
  });

  test('session or vault key change prevents submission', () async {
    final file = await preparedFile();
    var activeMvk = mvk;
    var posts = 0;
    final app = FilePrivateConflictBackfill(
      enabled: true,
      bearer: bearer,
      vaultId: vaultId,
      sessionEpoch: 5,
      mvk: mvk,
      currentBearer: () => bearer,
      currentVaultId: () => vaultId,
      currentSessionEpoch: () => 5,
      currentMvk: () => activeMvk,
      proofProvider: () async {
        activeMvk = SecretKey(List<int>.filled(32, 46));
        return 'opaque-action-proof';
      },
      get: (token, path) async {
        if (path.endsWith('/file-staged/$fileId')) {
          return <String, dynamic>{
            'file_id': fileId,
            'source_snapshot': snapshot,
            'total_bytes': bytes.length,
            'chunk_count': 1,
            'readback_receipt': evidence.readbackReceipt,
            'v2_ciphertext_sha256': List<String>.filled(64, 'f').join(),
          };
        }
        if (path.endsWith('/manifest')) return file.manifest;
        if (path.endsWith('/chunk/0')) {
          return <String, dynamic>{
            'file_id': fileId, 'chunk_index': 0,
            'ciphertext': file.prepared.chunkCiphertexts.single,
          };
        }
        throw StateError('unexpected GET');
      },
      post: (token, path, body) async {
        posts++;
        return <String, dynamic>{};
      },
    );
    await expectLater(app.indexVerifiedLegacyFile(evidence), throwsStateError);
    expect(posts, 0);
  });

  test('backfill remains disabled by default', () async {
    final app = FilePrivateConflictBackfill(
      bearer: bearer,
      vaultId: vaultId,
      sessionEpoch: 5,
      mvk: mvk,
      currentBearer: () => bearer,
      currentVaultId: () => vaultId,
      currentSessionEpoch: () => 5,
      currentMvk: () => mvk,
      proofProvider: () async => throw StateError('proof requested'),
      get: (token, path) async => throw StateError('GET requested'),
      post: (token, path, body) async =>
          throw StateError('POST requested'),
    );
    await expectLater(app.indexVerifiedLegacyFile(evidence), throwsStateError);
  });
}
