import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_private_conflict_backfill.dart';
import 'package:vault_ai_frontend/services/file_private_conflict_tokens.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  const fileId = 'v2-AAAAAAAAAAAAAAAAAAAAAAAAAAA';
  const vaultId = '123e4567-e89b-12d3-a456-426614174000';
  const bearer = 'synthetic-bearer';
  final mvk = SecretKey(List<int>.filled(32, 63));
  final clear = Uint8List.fromList(utf8.encode('synthetic private bytes'));

  Future<PreparedNewFileV2> prepared() => FileV2Writer(mvk).prepare(
        fileId: fileId,
        fileName: 'Private.jpg',
        savedName: 'Beach Picture',
        bytes: clear,
        chunkSize: 8,
      );

  for (final changed in <bool>[false, true]) {
    test(
        'ready index ${changed ? 'rejects changed source' : 'streams blind tags'}',
        () async {
      final file = await prepared();
      final revisionA = List<String>.filled(43, 'A').join();
      final revisionB = List<String>.filled(43, 'B').join();
      var sourceReads = 0;
      final posts = <Map<String, dynamic>>[];
      final backfill = FilePrivateConflictBackfill(
        enabled: true,
        bearer: bearer,
        vaultId: vaultId,
        sessionEpoch: 7,
        mvk: mvk,
        currentBearer: () => bearer,
        currentVaultId: () => vaultId,
        currentSessionEpoch: () => 7,
        currentMvk: () => mvk,
        proofProvider: () async => 'opaque-action-proof',
        get: (token, path) async {
          expect(token, bearer);
          if (path.endsWith('/ready-source/$fileId')) {
            sourceReads++;
            return <String, dynamic>{
              'file_id': fileId,
              'source_revision':
                  changed && sourceReads == 2 ? revisionB : revisionA,
              'file_size': clear.length,
              'name_version': 0,
            };
          }
          if (path.endsWith('/manifest')) {
            return <String, dynamic>{
              ...file.toManifestBody(),
              'lifecycle_state': 'legacy_migration_retired',
              'verification_state': 'client_verified',
              'name_version': 0,
              'saved_name_override_ciphertext': null,
            };
          }
          final match = RegExp(r'/chunk/(\d+)$').firstMatch(path);
          if (match != null) {
            return <String, dynamic>{
              'file_id': fileId,
              'chunk_index': int.parse(match.group(1)!),
              'ciphertext': file.chunkCiphertexts[int.parse(match.group(1)!)],
            };
          }
          throw StateError('Unexpected GET $path');
        },
        post: (token, path, body) async {
          expect(token, bearer);
          expect(path, '/vault/file-conflict/index-ready');
          posts.add(body);
          return <String, dynamic>{
            'file_id': fileId,
            'source_revision': revisionA,
            'indexed': true,
          };
        },
      );
      if (changed) {
        await expectLater(
            backfill.indexReadyV2File(fileId), throwsFormatException);
        expect(posts, isEmpty);
      } else {
        await backfill.indexReadyV2File(fileId);
        expect(posts, hasLength(1));
        final expected = await FilePrivateConflictTokenMaker(
          mvk: mvk,
          vaultId: vaultId,
        ).make(
          wholeFileSha256:
              Uint8List.fromList(crypto.sha256.convert(clear).bytes),
          fileSize: clear.length,
          fileName: 'Private.jpg',
          savedName: 'Beach Picture',
        );
        expect(
            posts.single['content_token'], b64urlEncode(expected.contentToken));
        expect(posts.single['name_tokens'],
            expected.nameTokens.map(b64urlEncode).toList());
        expect(posts.single['source_revision'], revisionA);
        expect(jsonEncode(posts.single), isNot(contains('Private.jpg')));
        expect(jsonEncode(posts.single), isNot(contains('Beach Picture')));
        expect(jsonEncode(posts.single), isNot(contains('synthetic private')));
        expect(jsonEncode(posts.single), isNot(contains('123456')));
      }
      expect(sourceReads, 2);
    });
  }
}
