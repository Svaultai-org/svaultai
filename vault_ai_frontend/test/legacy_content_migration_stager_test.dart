import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_content_migration_stager.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

final SecretKey _legacyKey = SecretKey(List<int>.filled(32, 31));
final SecretKey _mvk = SecretKey(List<int>.filled(32, 47));

Future<String> _legacyEncrypt(List<int> plain) async {
  final box = await AesGcm.with256bits().encrypt(
    plain,
    secretKey: _legacyKey,
    nonce: List<int>.generate(12, (i) => i + 2),
  );
  return base64.encode(<int>[
    ...box.nonce,
    ...box.cipherText,
    ...box.mac.bytes,
  ]);
}

LegacyCiphertextExportClient _export({
  required List<Map<String, dynamic>> itemRows,
  required List<Map<String, dynamic>> fileRows,
  required Map<int, String> itemCiphertexts,
  required Map<String, String> fileCiphertexts,
  required List<String> calls,
}) {
  var nextSequence = 0;
  var grants = 0;
  return LegacyCiphertextExportClient(
    proofProvider: () async => 'synthetic-opaque-proof',
    post: (path, body) async {
      calls.add(path);
      if (path.endsWith('/start')) {
        grants++;
        nextSequence = 0;
        return <String, dynamic>{
          'export_token': 'synthetic-grant-$grants',
          'next_sequence': 0,
          'pages_remaining': 16,
        };
      }
      expect(body['sequence'], nextSequence);
      nextSequence++;
      final common = <String, dynamic>{
        'next_sequence': nextSequence,
        'pages_remaining': 16 - nextSequence,
      };
      switch (body['mode']) {
        case 'list_items':
          return <String, dynamic>{
            ...common,
            'records': itemRows,
            'has_more': false,
          };
        case 'list_files':
          return <String, dynamic>{
            ...common,
            'records': fileRows,
            'has_more': false,
          };
        case 'read_item':
          final text = itemCiphertexts[body['item_id']];
          expect(text, isNotNull);
          return <String, dynamic>{
            ...common,
            'item_id': body['item_id'],
            'offset': 0,
            'ciphertext_chunk': text,
            'total_chars': text!.length,
            'next_offset': text.length,
            'done': true,
          };
        case 'read_file':
          final text = fileCiphertexts[body['file_id']];
          expect(text, isNotNull);
          return <String, dynamic>{
            ...common,
            'file_id': body['file_id'],
            'offset': 0,
            'ciphertext_chunk': text,
            'total_chars': text!.length,
            'next_offset': text.length,
            'done': true,
          };
      }
      fail('Unexpected export mode');
    },
  );
}

void main() {
  test('default-off staging performs no proof or request', () async {
    var called = false;
    final stager = LegacyContentMigrationStager(
      export: LegacyCiphertextExportClient(
        proofProvider: () async {
          called = true;
          return 'synthetic-proof';
        },
        post: (_, __) async {
          called = true;
          return <String, dynamic>{};
        },
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      ),
      request: (_, __, [___]) async {
        called = true;
        return const MigrationReply(200, <String, dynamic>{});
      },
    );
    final result = await stager.stageAndVerify();
    expect(result.itemsVerified, 0);
    expect(result.filesVerified, 0);
    expect(called, isFalse);
  });

  test('stages item, reads it back, and resumes without a second write',
      () async {
    final legacy = await _legacyEncrypt(utf8.encode(jsonEncode(
      <String, Object>{'username': 'synthetic-user', 'note': 'synthetic-note'},
    )));
    final calls = <String>[];
    Map<String, dynamic>? stageBody;
    var stageWrites = 0;
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedType = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('login')),
    );
    final encryptedService = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('synthetic.example')),
    );
    final stager = LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'item_id': 9,
            'item_type': null,
            'service': null,
            'item_type_ciphertext': encryptedType,
            'service_ciphertext': encryptedService,
            'ciphertext_chars': legacy.length,
          },
        ],
        fileRows: const <Map<String, dynamic>>[],
        itemCiphertexts: <int, String>{9: legacy},
        fileCiphertexts: const <String, String>{},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (path.endsWith('/item-staged/9')) {
          return stageBody == null
              ? const MigrationReply(
                  409, <String, dynamic>{'detail': 'item_not_staged'})
              : MigrationReply(200, <String, dynamic>{
                  'item_id': 9,
                  ...stageBody!,
                  'readback_receipt': 'synthetic-receipt',
                });
        }
        expect(path, '/vault/legacy-ciphertext/migrate/item-stage');
        expect(method, 'POST');
        expect(body!.containsKey('pin'), isFalse);
        expect(jsonEncode(body), isNot(contains('synthetic-note')));
        stageBody = body;
        stageWrites++;
        return const MigrationReply(200, <String, dynamic>{
          'item_id': 9,
          'staged': true,
          'created': true,
        });
      },
    );
    final first = await stager.stageAndVerify();
    final second = await stager.stageAndVerify();
    expect(first.itemsVerified, 1);
    expect(second.itemsVerified, 1);
    expect(stageWrites, 1);
    expect(calls.any((c) => c.contains('retire')), isFalse);
  });

  test('stages file chunks, verifies fetched bytes, and never retires',
      () async {
    final bytes = List<int>.generate(300000, (i) => (i * 13) & 255);
    final legacy = await _legacyEncrypt(bytes);
    final calls = <String>[];
    Map<String, dynamic>? manifest;
    final chunks = <int, String>{};
    var interruptSecondChunkOnce = true;
    final stager = LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-file',
            'file_size': bytes.length,
            'content_type': 'application/octet-stream',
            'ciphertext_chars': legacy.length,
            'file_name_ciphertext': 'synthetic-name-ct',
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{'synthetic-file': legacy},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (path.endsWith('/file-staged/synthetic-file')) {
          if (manifest == null) {
            return const MigrationReply(
                409, <String, dynamic>{'detail': 'file_v2_not_staged'});
          }
          if (chunks.length != manifest!['chunk_count']) {
            return const MigrationReply(
                409, <String, dynamic>{'detail': 'file_v2_chunks_incomplete'});
          }
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-file',
            'total_bytes': bytes.length,
            'chunk_count': manifest!['chunk_count'],
            'manifest_ciphertext': manifest!['manifest_ciphertext'],
            'readback_receipt': 'synthetic-receipt',
          });
        }
        if (path.endsWith('/manifest') && method == 'GET') {
          return manifest == null
              ? const MigrationReply(
                  404, <String, dynamic>{'detail': 'file_v2_not_found'})
              : MigrationReply(200, <String, dynamic>{...manifest!});
        }
        if (path == '/vault/file-v2/manifest' && method == 'POST') {
          expect(body!.containsKey('pin'), isFalse);
          expect(body['migrating_legacy'], isTrue);
          manifest = body;
          return const MigrationReply(
              200, <String, dynamic>{'file_id': 'synthetic-file'});
        }
        if (path.contains('/chunk/') && method == 'GET') {
          final index = int.parse(path.split('/').last);
          final chunk = chunks[index];
          return chunk == null
              ? const MigrationReply(
                  404, <String, dynamic>{'detail': 'file_v2_chunk_not_found'})
              : MigrationReply(200, <String, dynamic>{
                  'file_id': 'synthetic-file',
                  'chunk_index': index,
                  'ciphertext': chunk,
                });
        }
        if (path == '/vault/file-v2/chunk' && method == 'PUT') {
          expect(body!.containsKey('pin'), isFalse);
          if (body['chunk_index'] == 1 && interruptSecondChunkOnce) {
            interruptSecondChunkOnce = false;
            throw StateError('Synthetic interrupted upload');
          }
          chunks[body!['chunk_index'] as int] = body['ciphertext'] as String;
          return const MigrationReply(
              200, <String, dynamic>{'file_id': 'synthetic-file'});
        }
        fail('Unexpected file staging request');
      },
    );
    await expectLater(stager.stageAndVerify(), throwsA(isA<StateError>()));
    expect(chunks.length, 1);
    final second = await stager.stageAndVerify();
    expect(second.filesVerified, 1);
    expect(chunks.length, 2);
    expect(calls.where((c) => c == 'POST /vault/file-v2/manifest').length, 1);
    final writes = calls.where((c) => c == 'PUT /vault/file-v2/chunk').length;
    final third = await stager.stageAndVerify();
    expect(third.filesVerified, 1);
    expect(calls.where((c) => c == 'PUT /vault/file-v2/chunk').length, writes);
    expect(calls.any((c) => c.contains('retire')), isFalse);
  });
}
