import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_content_migration_stager.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

final SecretKey _legacyKey = SecretKey(List<int>.filled(32, 31));
final SecretKey _mvk = SecretKey(List<int>.filled(32, 47));
final String _snapshotA = List<String>.filled(43, 'A').join();
final String _snapshotB = List<String>.filled(43, 'B').join();

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
  Map<int, String>? itemSnapshots,
  Map<String, String>? fileSnapshots,
  Map<int, Map<String, dynamic>>? itemSourceMetadata,
  Map<String, Map<String, dynamic>>? fileSourceMetadata,
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
          final itemId = body['item_id'] as int;
          final listed = itemRows.firstWhere((row) => row['item_id'] == itemId);
          expect(text, isNotNull);
          return <String, dynamic>{
            ...common,
            'item_id': itemId,
            'offset': 0,
            'ciphertext_chunk': text,
            'total_chars': text!.length,
            'next_offset': text.length,
            'done': true,
            'source_snapshot': itemSnapshots?[itemId] ?? _snapshotA,
            'source_metadata': itemSourceMetadata?[itemId] ??
                <String, dynamic>{
                  for (final key in const <String>[
                    'item_type', 'service',
                    'item_type_ciphertext', 'service_ciphertext',
                  ]) key: listed[key],
                },
          };
        case 'read_file':
          final text = fileCiphertexts[body['file_id']];
          final fileId = body['file_id'] as String;
          final listed = fileRows.firstWhere((row) => row['file_id'] == fileId);
          expect(text, isNotNull);
          return <String, dynamic>{
            ...common,
            'file_id': fileId,
            'offset': 0,
            'ciphertext_chunk': text,
            'total_chars': text!.length,
            'next_offset': text.length,
            'done': true,
            'source_snapshot': fileSnapshots?[fileId] ?? _snapshotA,
            'source_metadata': fileSourceMetadata?[fileId] ??
                <String, dynamic>{
                  for (final key in const <String>[
                    'file_size', 'file_name', 'saved_name',
                    'content_type', 'detected_type', 'detected_service',
                    'asset_type', 'file_name_ciphertext',
                    'saved_name_ciphertext', 'content_type_ciphertext',
                    'detected_type_ciphertext',
                    'detected_service_ciphertext', 'asset_type_ciphertext',
                  ]) key: listed[key],
                },
          };
      }
      fail('Unexpected export mode');
    },
  );
}

void main() {
  test('migration transport binds bearer to the trusted device', () {
    final headers = legacyContentMigrationHeaders(
      sessionToken: 'synthetic-session',
      deviceId: 'synthetic-device',
    );
    expect(headers, <String, String>{
      'Authorization': 'Bearer synthetic-session',
      'X-Device-Id': 'synthetic-device',
      'Content-Type': 'application/json',
    });
    expect(headers.values.join(' '), isNot(contains('synthetic-pin')));
    expect(
      () => legacyContentMigrationHeaders(
        sessionToken: 'synthetic-session',
        deviceId: null,
      ),
      throwsStateError,
    );
  });

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
    final itemSnapshots = <int, String>{9: _snapshotA};
    final itemMetadata = <int, Map<String, dynamic>>{
      9: <String, dynamic>{
        'item_type': null,
        'service': null,
        'item_type_ciphertext': encryptedType,
        'service_ciphertext': encryptedService,
      },
    };
    final stager = LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'item_id': 9,
            'item_type': 'stale-listing-type',
            'service': 'stale-listing-service',
            'item_type_ciphertext': encryptedType,
            'service_ciphertext': encryptedService,
            'ciphertext_chars': legacy.length,
          },
        ],
        fileRows: const <Map<String, dynamic>>[],
        itemCiphertexts: <int, String>{9: legacy},
        fileCiphertexts: const <String, String>{},
        calls: calls,
        itemSnapshots: itemSnapshots,
        itemSourceMetadata: itemMetadata,
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
                  'source_snapshot': itemSnapshots[9],
                  'readback_receipt': 'synthetic-receipt',
                });
        }
        expect(path, '/vault/legacy-ciphertext/migrate/item-stage');
        expect(method, 'POST');
        expect(body!.containsKey('pin'), isFalse);
        expect(body['source_snapshot'], itemSnapshots[9]);
        expect(jsonEncode(body), isNot(contains('synthetic-note')));
        expect(jsonEncode(body), isNot(contains('synthetic.example')));
        stageBody = body;
        itemSnapshots[9] = _snapshotB;
        itemMetadata[9] = <String, dynamic>{
          'item_type': null,
          'service': null,
          'item_type_ciphertext': body['item_type_ciphertext'],
          'service_ciphertext': body['service_ciphertext'],
        };
        stageWrites++;
        return MigrationReply(200, <String, dynamic>{
          'item_id': 9,
          'staged': true,
          'created': true,
          'source_snapshot': itemSnapshots[9],
        });
      },
    );
    final first = await stager.stageAndVerify();
    final second = await stager.stageAndVerify();
    expect(first.itemsVerified, 1);
    expect(second.itemsVerified, 1);
    expect(stageWrites, 1);
    expect(calls.any((c) => c.contains('retire')), isFalse);
    expect(utf8.decode(await aesGcmUnwrap(metadataKey,
        b64urlDecode(stageBody!['item_type_ciphertext'] as String))), 'login');
    expect(utf8.decode(await aesGcmUnwrap(metadataKey,
        b64urlDecode(stageBody!['service_ciphertext'] as String))),
        'synthetic.example');
  });

  test('stages file chunks, verifies fetched bytes, and never retires',
      () async {
    final bytes = List<int>.generate(300000, (i) => (i * 13) & 255);
    final legacy = await _legacyEncrypt(bytes);
    final calls = <String>[];
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedName = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('synthetic-file.bin')),
    );
    final oldSavedName = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('Old saved name')),
    );
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
            'file_name_ciphertext': encryptedName,
            'saved_name_ciphertext': oldSavedName,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{'synthetic-file': legacy},
        calls: calls,
        fileSourceMetadata: <String, Map<String, dynamic>>{
          'synthetic-file': <String, dynamic>{
            'file_size': bytes.length,
            'file_name': null,
            'saved_name': 'Latest saved name',
            'content_type': 'application/octet-stream',
            'detected_type': null,
            'detected_service': null,
            'asset_type': null,
            'file_name_ciphertext': encryptedName,
            'saved_name_ciphertext': oldSavedName,
            'content_type_ciphertext': null,
            'detected_type_ciphertext': null,
            'detected_service_ciphertext': null,
            'asset_type_ciphertext': null,
          },
        },
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
            'source_snapshot': _snapshotA,
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
          expect(body['source_snapshot'], _snapshotA);
          expect(jsonEncode(body), isNot(contains('Latest saved name')));
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
          chunks[body['chunk_index'] as int] = body['ciphertext'] as String;
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
    final manifestPlain = jsonDecode(utf8.decode(await aesGcmUnwrap(
      metadataKey,
      b64urlDecode(manifest!['manifest_ciphertext'] as String),
    ))) as Map<String, dynamic>;
    final labels = manifestPlain['encrypted_metadata'] as Map<String, dynamic>;
    expect(utf8.decode(await aesGcmUnwrap(
      metadataKey, b64urlDecode(labels['saved_name_ciphertext'] as String),
    )), 'Latest saved name');
  });

  test('stale source rejection aborts without deleting legacy item', () async {
    final legacy = await _legacyEncrypt(utf8.encode(jsonEncode(
      <String, Object>{'note': 'synthetic protected value'},
    )));
    final calls = <String>[];
    var stageWrites = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'item_id': 5,
            'ciphertext_chars': legacy.length,
          },
        ],
        fileRows: const <Map<String, dynamic>>[],
        itemCiphertexts: <int, String>{5: legacy},
        fileCiphertexts: const <String, String>{},
        itemSourceMetadata: <int, Map<String, dynamic>>{
          5: <String, dynamic>{
            'item_type': 'note',
            'service': 'current title',
            'item_type_ciphertext': null,
            'service_ciphertext': null,
          },
        },
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(legacyKey: _legacyKey, mvk: _mvk),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET') {
          return const MigrationReply(
            409, <String, dynamic>{'detail': 'item_not_staged'},
          );
        }
        expect(path, '/vault/legacy-ciphertext/migrate/item-stage');
        expect(body?['source_snapshot'], _snapshotA);
        expect(body?.containsKey('pin'), isFalse);
        stageWrites++;
        return const MigrationReply(
          409, <String, dynamic>{'detail': 'legacy_source_changed'},
        );
      },
    );
    await expectLater(stager.stageAndVerify(), throwsStateError);
    expect(stageWrites, 1);
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
    expect(legacy, isNotEmpty);
  });
}
