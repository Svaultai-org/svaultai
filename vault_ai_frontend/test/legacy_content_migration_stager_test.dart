import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
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
  Map<String, Map<String, String?>>? fileExtras,
  LegacyProofProvider? proofProvider,
  List<String>? fileReadOrder,
  List<String>? exportModes,
}) {
  var nextSequence = 0;
  var grants = 0;
  return LegacyCiphertextExportClient(
    proofProvider: proofProvider ?? () async => 'synthetic-opaque-proof',
    post: (path, body) async {
      calls.add(path);
      if (path.endsWith('/start')) {
        grants++;
        nextSequence = 0;
        return <String, dynamic>{
          'export_token': 'synthetic-grant-$grants',
          'next_sequence': 0,
          'pages_remaining': 16,
          'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes,
          'expires_at': '2099-01-01T00:00:00Z',
        };
      }
      expect(body['sequence'], nextSequence);
      nextSequence++;
      final common = <String, dynamic>{
        'next_sequence': nextSequence,
        'pages_remaining': 16 - nextSequence,
        'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes -
            nextSequence * 1024,
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
          fileReadOrder?.add(fileId);
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
        case 'read_file_extra':
        case 'read_file_extra_v3':
          final fileId = body['file_id'] as String;
          exportModes?.add(body['mode'] as String);
          return <String, dynamic>{
            ...common,
            'file_id': fileId,
            'source_snapshot': fileSnapshots?[fileId] ?? _snapshotA,
            'legacy_extra': fileExtras?[fileId],
            if (body['mode'] == 'read_file_extra_v3')
              'legacy_extra_version': 3,
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

  test('remaining unstaged files are tried before previously staged sidecars',
      () async {
    final ciphertext = await _legacyEncrypt(<int>[7]);
    final calls = <String>[];
    final fileReadOrder = <String>[];
    final manifestLookups = <String>[];
    var inFlightLookups = 0;
    var maxInFlightLookups = 0;
    final result = await LegacyContentMigrationStager(
      enabled: true,
      prioritizeUnstagedFiles: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-existing',
            'ciphertext_chars': ciphertext.length,
            'file_size': 1,
          },
          <String, dynamic>{
            'file_id': 'synthetic-new',
            'ciphertext_chars': ciphertext.length,
            'file_size': 1,
          },
          <String, dynamic>{
            'file_id': 'synthetic-new-two',
            'ciphertext_chars': ciphertext.length,
            'file_size': 1,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{
          'synthetic-existing': ciphertext,
          'synthetic-new': ciphertext,
          'synthetic-new-two': ciphertext,
        },
        calls: calls,
        fileReadOrder: fileReadOrder,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        expect(method, 'GET');
        expect(path, endsWith('/manifest'));
        manifestLookups.add(path);
        inFlightLookups++;
        if (inFlightLookups > maxInFlightLookups) {
          maxInFlightLookups = inFlightLookups;
        }
        // The second response completes first, but file processing must keep
        // the original order within the unstaged and existing groups.
        await Future<void>.delayed(Duration(
          milliseconds: path.contains('/synthetic-existing/') ? 10 : 1,
        ));
        inFlightLookups--;
        if (path.contains('/synthetic-new/')) {
          return const MigrationReply(404, {'detail': 'file_v2_not_found'});
        }
        if (path.contains('/synthetic-new-two/')) {
          return const MigrationReply(404, {'detail': 'file_v2_not_found'});
        }
        return const MigrationReply(200, {'manifest_ciphertext': 'synthetic'});
      },
    ).stageAndVerify();
    expect(manifestLookups, hasLength(3));
    expect(maxInFlightLookups, 2);
    expect(fileReadOrder, <String>[
      'synthetic-new', 'synthetic-new-two', 'synthetic-existing',
    ]);
    // All synthetic sources deliberately lack a name, so none is counted
    // as verified and no legacy source is retired.
    expect(result.filesVerified, 0);
    expect(result.filesDeferredForUnreadableSource, 3);
  });

  test('unexpected manifest preflight failure stops before source export',
      () async {
    final calls = <String>[];
    final fileReadOrder = <String>[];
    final stager = LegacyContentMigrationStager(
      enabled: true,
      prioritizeUnstagedFiles: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{'file_id': 'synthetic-file', 'ciphertext_chars': 40},
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: const <String, String>{},
        calls: calls,
        fileReadOrder: fileReadOrder,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          const MigrationReply(403, {'detail': 'device_untrusted'}),
    );
    await expectLater(stager.stageAndVerify(), throwsStateError);
    expect(fileReadOrder, isEmpty);
  });

  test('oversize records are explicitly deferred before content export',
      () async {
    final calls = <String>[];
    final result = await LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[
          {'item_id': 9,
           'ciphertext_chars':
               LegacyContentMigrationStager.maxAutomaticCiphertextChars + 1},
        ],
        fileRows: <Map<String, dynamic>>[
          {'file_id': 'synthetic-large-file',
           'ciphertext_chars':
               LegacyContentMigrationStager.maxAutomaticCiphertextChars + 1},
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: const <String, String>{},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          throw StateError('oversize record reached a stage route'),
    ).stageAndVerify();
    expect(result.itemsVerified, 0);
    expect(result.filesVerified, 0);
    expect(result.itemsDeferredForSize, 1);
    expect(result.filesDeferredForSize, 1);
    expect(calls.where((path) => path.endsWith('/page')), hasLength(2));
  });

  test('owner file ceiling admits 8 to 64 MiB and defers larger sources',
      () async {
    final calls = <String>[];
    final reads = <String>[];
    final overAutomatic =
        LegacyContentMigrationStager.maxAutomaticCiphertextChars + 1;
    final overBackend =
        LegacyContentMigrationStager.maxOwnerInitiatedFileCiphertextChars + 1;
    final owner = LegacyContentMigrationStager(
      enabled: true,
      maxFileCiphertextChars:
          LegacyContentMigrationStager.maxOwnerInitiatedFileCiphertextChars,
      export: _export(
        itemRows: const [],
        fileRows: <Map<String, dynamic>>[{
          'file_id': 'owner-large', 'ciphertext_chars': overAutomatic,
        }],
        itemCiphertexts: const {},
        fileCiphertexts: const {},
        calls: calls,
        fileReadOrder: reads,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          throw StateError('No V2 route is needed before source read'),
    );
    await expectLater(owner.stageAndVerify(), throwsA(anything));
    expect(reads, ['owner-large']);

    final oversized = await LegacyContentMigrationStager(
      enabled: true,
      maxFileCiphertextChars:
          LegacyContentMigrationStager.maxOwnerInitiatedFileCiphertextChars,
      export: _export(
        itemRows: const [],
        fileRows: <Map<String, dynamic>>[{
          'file_id': 'above-backend', 'ciphertext_chars': overBackend,
        }],
        itemCiphertexts: const {},
        fileCiphertexts: const {},
        calls: <String>[],
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          throw StateError('Oversize source must stay untouched'),
    ).stageAndVerify();
    expect(oversized.filesDeferredForSize, 1);
  });

  test('local codec verifies a synthetic 9 MiB owner file', () async {
    final plain = List<int>.filled(9 * 1024 * 1024, 7);
    final legacy = await _legacyEncrypt(plain);
    expect(legacy.length,
        greaterThan(LegacyContentMigrationStager.maxAutomaticCiphertextChars));
    expect(legacy.length,
        lessThan(LegacyContentMigrationStager.maxOwnerInitiatedFileCiphertextChars));
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final metadata = <String, String?>{
      'file_name_ciphertext': b64urlEncode(await aesGcmWrap(
          metadataKey, utf8.encode('synthetic-large.bin'))),
    };
    final staged = await codec.stageFile(
      fileId: 'synthetic-large',
      legacyCiphertext: legacy,
      declaredFileSize: plain.length,
      contentType: 'application/octet-stream',
      encryptedMetadata: metadata,
    );
    expect(await codec.verifyStagedFile(
      fileId: 'synthetic-large',
      legacyCiphertext: legacy,
      declaredFileSize: plain.length,
      contentType: 'application/octet-stream',
      encryptedMetadata: metadata,
      chunkSize: staged.chunkSize,
      chunkCount: staged.chunkCiphertexts.length,
      manifestCiphertext: staged.manifestCiphertext,
      chunkCiphertexts: staged.chunkCiphertexts,
    ), isTrue);
  });

  test('oversize legacy text is deferred before owner content export',
      () async {
    final calls = <String>[];
    final result = await LegacyContentMigrationStager(
      enabled: true,
      extraFileMetadataEnabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: const <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-oversize-extra',
            'ciphertext_chars': 40,
            'extra_text_bytes': 64 * 1024 + 1,
            'extra_path_bytes': 0,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: const <String, String>{},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          throw StateError('oversize extra reached staging'),
    ).stageAndVerify();
    expect(result.filesVerified, 0);
    expect(result.filesDeferredForSize, 1);
    expect(calls.where((path) => path.endsWith('/page')), hasLength(2));
  });

  test('owner V3 path preserves a 201 KiB legacy text field', () async {
    final text = List<String>.filled(201 * 1024, 'x').join();
    final encrypted = await _legacyEncrypt(<int>[1, 2, 3]);
    final modes = <String>[];
    final stager = LegacyContentMigrationStager(
      enabled: true,
      extraFileMetadataEnabled: true,
      extraFileMetadataV3Enabled: true,
      export: _export(
        itemRows: const [],
        fileRows: <Map<String, dynamic>>[{
          'file_id': 'synthetic-v3',
          'ciphertext_chars': encrypted.length,
          'extra_text_bytes': utf8.encode(text).length,
          'extra_path_bytes': 0,
        }],
        itemCiphertexts: const {},
        fileCiphertexts: {'synthetic-v3': encrypted},
        calls: <String>[],
        exportModes: modes,
        fileSourceMetadata: <String, Map<String, dynamic>>{
          'synthetic-v3': {
            'file_size': 3,
            'file_name': 'synthetic-v3.bin',
            'content_type': 'application/octet-stream',
            'has_legacy_extra_data': true,
          },
        },
        fileExtras: <String, Map<String, String?>>{
          'synthetic-v3': {
            'relative_path': null, 'extracted_text': text,
          },
        },
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async =>
          throw StateError('V3 export and local staging reached'),
    );
    await expectLater(stager.stageAndVerify(), throwsStateError);
    expect(modes, ['read_file_extra_v3']);
  });

  test('V3 manifest readback decrypts exact large extracted text', () async {
    final text = List<String>.filled(201 * 1024, 'v').join();
    final legacy = await _legacyEncrypt(<int>[1, 2, 3]);
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final metadata = <String, String?>{
      'file_name_ciphertext': b64urlEncode(await aesGcmWrap(
          metadataKey, utf8.encode('synthetic-v3.bin'))),
    };
    final extra = <String, String?>{
      'relative_path': 'private/folder',
      'extracted_text': text,
    };
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final staged = await codec.stageFile(
      fileId: 'synthetic-v3', legacyCiphertext: legacy,
      declaredFileSize: 3, contentType: 'application/octet-stream',
      encryptedMetadata: metadata, legacyExtra: extra, extraVersion: 3,
    );
    expect(staged.migrationMetadataVersion, 3);
    expect(staged.toManifestBody()['migration_metadata_version'], 3);
    expect(await codec.verifyStagedFile(
      fileId: 'synthetic-v3', legacyCiphertext: legacy,
      declaredFileSize: 3, contentType: 'application/octet-stream',
      encryptedMetadata: metadata, legacyExtra: extra, extraVersion: 3,
      chunkSize: staged.chunkSize,
      chunkCount: staged.chunkCiphertexts.length,
      manifestCiphertext: staged.manifestCiphertext,
      chunkCiphertexts: staged.chunkCiphertexts,
    ), isTrue);
    final reader = FileV2Reader(mvk: _mvk, get: (path) async {
      if (path.endsWith('/manifest')) {
        return <String, dynamic>{
          'file_id': 'synthetic-v3',
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext': staged.manifestCiphertext,
          'total_bytes': 3, 'chunk_size': staged.chunkSize,
          'chunk_count': staged.chunkCiphertexts.length,
          'migration_metadata_version': 3,
          'lifecycle_state': 'legacy_migration_retired',
          'verification_state': 'client_verified',
          'name_version': 0,
        };
      }
      expect(path, '/vault/file-v2/synthetic-v3/chunk/0');
      return <String, dynamic>{
        'file_id': 'synthetic-v3', 'chunk_index': 0,
        'ciphertext': staged.chunkCiphertexts.single,
      };
    });
    final read = await reader.download('synthetic-v3', requireRetired: true);
    expect(read.bytes, [1, 2, 3]);
    expect(read.manifest.relativePath, 'private/folder');
    expect(read.manifest.extractedText, text);
  });

  test('unreadable local file source does not block a later valid file',
      () async {
    final wrongKey = SecretKey(List<int>.filled(32, 88));
    final box = await AesGcm.with256bits().encrypt(
      <int>[1, 2, 3],
      secretKey: wrongKey,
      nonce: List<int>.generate(12, (i) => i + 3),
    );
    final unreadable = base64.encode(<int>[
      ...box.nonce, ...box.cipherText, ...box.mac.bytes,
    ]);
    final valid = await _legacyEncrypt(<int>[7, 8, 9]);
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedName = b64urlEncode(await aesGcmWrap(
      metadataKey, utf8.encode('synthetic-valid.bin'),
    ));
    final prepared = await codec.stageFile(
      fileId: 'synthetic-valid-file',
      legacyCiphertext: valid,
      declaredFileSize: 3,
      contentType: null,
      encryptedMetadata: <String, String?>{
        'file_name_ciphertext': encryptedName,
        'saved_name_ciphertext': null,
        'content_type_ciphertext': null,
        'detected_type_ciphertext': null,
        'detected_service_ciphertext': null,
        'asset_type_ciphertext': null,
      },
    );
    final calls = <String>[];
    final phases = <LegacyStagePhase>[];
    final result = await LegacyContentMigrationStager(
      enabled: true,
      onPhase: phases.add,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-unreadable-file',
            'ciphertext_chars': unreadable.length,
            'file_size': 3,
            'file_name': 'synthetic-unreadable.bin',
          },
          <String, dynamic>{
            'file_id': 'synthetic-oversize-file',
            'ciphertext_chars':
                LegacyContentMigrationStager.maxAutomaticCiphertextChars + 1,
          },
          <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'ciphertext_chars': valid.length,
            'file_size': 3,
            'file_name': 'synthetic-valid.bin',
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{
          'synthetic-unreadable-file': unreadable,
          'synthetic-valid-file': valid,
        },
        calls: calls,
      ),
      codec: codec,
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' &&
            path.endsWith('/file-staged/synthetic-valid-file')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'source_snapshot': _snapshotA,
            'total_bytes': 3,
            'chunk_count': prepared.chunkCiphertexts.length,
            'manifest_ciphertext': prepared.manifestCiphertext,
          });
        }
        if (method == 'GET' && path.endsWith('/chunk/0')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'chunk_index': 0,
            'ciphertext': prepared.chunkCiphertexts.single,
          });
        }
        throw StateError('unexpected V2 stage route');
      },
    ).stageAndVerify();
    expect(result.filesVerified, 1);
    expect(result.filesDeferredForUnreadableSource, 1);
    expect(result.filesDeferredForSize, 1);
    expect(calls.where((path) => path.endsWith('/page')), hasLength(4));
    expect(phases, containsAllInOrder(<LegacyStagePhase>[
      LegacyStagePhase.itemsComplete,
      LegacyStagePhase.filesListed,
      LegacyStagePhase.fileSourceRead,
      LegacyStagePhase.fileSourceRead,
      LegacyStagePhase.filePrepared,
    ]));
  });

  test('unsupported legacy file metadata defers only that existing sidecar',
      () async {
    final extra = await _legacyEncrypt(<int>[1, 2, 3]);
    final valid = await _legacyEncrypt(<int>[4, 5, 6]);
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey,
      mvk: _mvk,
    );
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedName = b64urlEncode(await aesGcmWrap(
      metadataKey,
      utf8.encode('synthetic-file.bin'),
    ));
    final prepared = await codec.stageFile(
      fileId: 'synthetic-valid-file',
      legacyCiphertext: valid,
      declaredFileSize: 3,
      contentType: null,
      encryptedMetadata: <String, String?>{
        'file_name_ciphertext': encryptedName,
        'saved_name_ciphertext': null,
        'content_type_ciphertext': null,
        'detected_type_ciphertext': null,
        'detected_service_ciphertext': null,
        'asset_type_ciphertext': null,
      },
    );
    final calls = <String>[];
    final result = await LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-extra-file',
            'ciphertext_chars': extra.length,
            'file_size': 3,
            'file_name_ciphertext': encryptedName,
          },
          <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'ciphertext_chars': valid.length,
            'file_size': 3,
            'file_name_ciphertext': encryptedName,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{
          'synthetic-extra-file': extra,
          'synthetic-valid-file': valid,
        },
        calls: calls,
      ),
      codec: codec,
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' &&
            path.endsWith('/file-staged/synthetic-extra-file')) {
          return const MigrationReply(409, <String, dynamic>{
            'detail': 'file_extra_legacy_data_requires_migration',
          });
        }
        if (method == 'GET' &&
            path.endsWith('/file-staged/synthetic-valid-file')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'source_snapshot': _snapshotA,
            'total_bytes': 3,
            'chunk_count': prepared.chunkCiphertexts.length,
            'manifest_ciphertext': prepared.manifestCiphertext,
          });
        }
        if (method == 'GET' && path.endsWith('/chunk/0')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'chunk_index': 0,
            'ciphertext': prepared.chunkCiphertexts.single,
          });
        }
        fail('Unexpected file staging request: $method $path');
      },
    ).stageAndVerify();
    expect(result.filesVerified, 1);
    expect(result.filesDeferredForExtraLegacyData, 1);
    expect(result.filesDeferredForUnreadableSource, 0);
    expect(
        calls.where((call) => call.contains('synthetic-extra-file')),
        contains(
            'GET /vault/legacy-ciphertext/migrate/file-staged/synthetic-extra-file'));
    expect(
        calls.any((call) =>
            call.contains('retire') ||
            call.contains('delete') ||
            call == 'POST /vault/file-v2/manifest'),
        isFalse);
  });

  test('unsupported metadata after sidecar upload preserves and continues',
      () async {
    final extra = await _legacyEncrypt(<int>[1, 2, 3]);
    final valid = await _legacyEncrypt(<int>[4, 5, 6]);
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey,
      mvk: _mvk,
    );
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedName = b64urlEncode(await aesGcmWrap(
      metadataKey,
      utf8.encode('synthetic-file.bin'),
    ));
    final prepared = await codec.stageFile(
      fileId: 'synthetic-valid-file',
      legacyCiphertext: valid,
      declaredFileSize: 3,
      contentType: null,
      encryptedMetadata: <String, String?>{
        'file_name_ciphertext': encryptedName,
        'saved_name_ciphertext': null,
        'content_type_ciphertext': null,
        'detected_type_ciphertext': null,
        'detected_service_ciphertext': null,
        'asset_type_ciphertext': null,
      },
    );
    final calls = <String>[];
    var extraStageReads = 0;
    final result = await LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-extra-file',
            'ciphertext_chars': extra.length,
            'file_size': 3,
            'file_name_ciphertext': encryptedName,
          },
          <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'ciphertext_chars': valid.length,
            'file_size': 3,
            'file_name_ciphertext': encryptedName,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{
          'synthetic-extra-file': extra,
          'synthetic-valid-file': valid,
        },
        calls: calls,
      ),
      codec: codec,
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' &&
            path.endsWith('/file-staged/synthetic-extra-file')) {
          extraStageReads++;
          return MigrationReply(409, <String, dynamic>{
            'detail': extraStageReads == 1
                ? 'file_v2_not_staged'
                : 'file_extra_legacy_data_requires_migration',
          });
        }
        if (method == 'GET' &&
            path.endsWith('/synthetic-extra-file/manifest')) {
          return const MigrationReply(404, <String, dynamic>{
            'detail': 'file_v2_not_found',
          });
        }
        if (method == 'POST' && path == '/vault/file-v2/manifest') {
          expect(body?['migrating_legacy'], isTrue);
          return const MigrationReply(200, <String, dynamic>{});
        }
        if (method == 'GET' && path.endsWith('/synthetic-extra-file/chunk/0')) {
          return const MigrationReply(404, <String, dynamic>{
            'detail': 'file_v2_chunk_not_found',
          });
        }
        if (method == 'PUT' && path == '/vault/file-v2/chunk') {
          return const MigrationReply(200, <String, dynamic>{});
        }
        if (method == 'GET' &&
            path.endsWith('/file-staged/synthetic-valid-file')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'source_snapshot': _snapshotA,
            'total_bytes': 3,
            'chunk_count': prepared.chunkCiphertexts.length,
            'manifest_ciphertext': prepared.manifestCiphertext,
          });
        }
        if (method == 'GET' && path.endsWith('/synthetic-valid-file/chunk/0')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-valid-file',
            'chunk_index': 0,
            'ciphertext': prepared.chunkCiphertexts.single,
          });
        }
        fail('Unexpected file staging request: $method $path');
      },
    ).stageAndVerify();
    expect(extraStageReads, 2);
    expect(result.filesVerified, 1);
    expect(result.filesDeferredForExtraLegacyData, 1);
    expect(calls.where((call) => call == 'POST /vault/file-v2/manifest'),
        hasLength(1));
    expect(calls.where((call) => call == 'PUT /vault/file-v2/chunk'),
        hasLength(1));
    expect(
        calls.any((call) => call.contains('retire') || call.contains('delete')),
        isFalse);
  });

  test('other file-stage conflicts still abort the batch', () async {
    final legacy = await _legacyEncrypt(<int>[1, 2, 3]);
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedName = b64urlEncode(await aesGcmWrap(
      metadataKey, utf8.encode('synthetic-file.bin'),
    ));
    final calls = <String>[];
    final stager = LegacyContentMigrationStager(
      enabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': 'synthetic-conflict-file',
            'ciphertext_chars': legacy.length,
            'file_size': 3,
            'file_name_ciphertext': encryptedName,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{
          'synthetic-conflict-file': legacy,
        },
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        return const MigrationReply(409, <String, dynamic>{
          'detail': 'file_v2_manifest_conflict',
        });
      },
    );
    await expectLater(stager.stageAndVerify(), throwsA(isA<StateError>()));
    expect(calls.any((call) => call.contains('retire') ||
        call.contains('delete') || call == 'POST /vault/file-v2/manifest'),
        isFalse);
  });

  test('wallet-engine row is not generically staged or counted', () async {
    final legacy = await _legacyEncrypt(utf8.encode('{"wallet":"synthetic"}'));
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final encryptedType = b64urlEncode(await aesGcmWrap(
      key, utf8.encode('crypto_wallet_account'),
    ));
    final calls = <String>[];
    final result = await LegacyContentMigrationStager(
      enabled: true,
      recoveryEnabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[{
          'item_id': 21, 'ciphertext_chars': legacy.length,
          'item_type': null, 'service': 'ETH',
          'item_type_ciphertext': encryptedType,
        }],
        fileRows: const [],
        itemCiphertexts: {21: legacy},
        fileCiphertexts: const {},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (_, __, [___]) async {
        fail('Wallet row must not use generic item migration routes');
      },
    ).stageAndVerify();
    expect(result.itemsVerified, 0);
    expect(calls.any((call) => call.contains('reset-stage') ||
        call.contains('item-stage')), isFalse);
  });

  test('stages item, reads it back, and resumes without a second write',
      () async {
    var receiptExpiry = DateTime.now().toUtc().add(
      const Duration(minutes: 5),
    );
    var itemReceipt = 'ir1.${receiptExpiry.millisecondsSinceEpoch ~/ 1000}.'
        '$_snapshotA.$_snapshotB';
    final legacy = await _legacyEncrypt(utf8.encode(jsonEncode(
      <String, Object>{'username': 'synthetic-user', 'note': 'synthetic-note'},
    )));
    final calls = <String>[];
    Map<String, dynamic>? stageBody;
    var stageWrites = 0;
    var omitReceipt = false;
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
      requireReadbackEvidence: true,
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
                  if (!omitReceipt) 'readback_receipt': itemReceipt,
                  if (!omitReceipt)
                    'receipt_expires_at': receiptExpiry.toIso8601String(),
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
    expect(first.verifiedReadbacks, hasLength(1));
    expect(first.verifiedReadbacks.single.recordId, '9');
    expect(first.verifiedReadbacks.single.sourceSnapshot, _snapshotB);
    expect(first.verifiedReadbacks.single.readbackReceipt, itemReceipt);
    expect(first.verifiedReadbacks.single.isFile, isFalse);
    // The server starts its ten-minute TTL from its clock. A browser clock
    // 30 seconds behind must still accept a fresh signed receipt.
    receiptExpiry = DateTime.now().toUtc().add(
      const Duration(minutes: 10, seconds: 30),
    );
    itemReceipt = 'ir1.${receiptExpiry.millisecondsSinceEpoch ~/ 1000}.'
        '$_snapshotA.$_snapshotB';
    final skewed = await stager.stageAndVerify();
    expect(skewed.itemsVerified, 1);
    expect(skewed.verifiedReadbacks.single.readbackReceipt, itemReceipt);
    // A much longer receipt is still rejected locally.
    receiptExpiry = DateTime.now().toUtc().add(
      const Duration(minutes: 13),
    );
    itemReceipt = 'ir1.${receiptExpiry.millisecondsSinceEpoch ~/ 1000}.'
        '$_snapshotA.$_snapshotB';
    await expectLater(stager.stageAndVerify(), throwsFormatException);
    omitReceipt = true;
    await expectLater(stager.stageAndVerify(), throwsFormatException);
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
    final receiptExpiry = DateTime.now().toUtc().add(
      const Duration(minutes: 5),
    );
    final fileReceipt = 'fr1.${receiptExpiry.millisecondsSinceEpoch ~/ 1000}.'
        '$_snapshotA.$_snapshotB';
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
    final oldContentType = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('old/type')),
    );
    final oldDetectedType = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('old-detected')),
    );
    final oldDetectedService = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('old-service')),
    );
    final oldAssetType = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('old-asset')),
    );
    Map<String, dynamic>? manifest;
    final chunks = <int, String>{};
    var interruptSecondChunkOnce = true;
    var inFlightChunkGets = 0;
    var maxInFlightChunkGets = 0;
    final readbackCompletions = <int>[];
    var corruptFinalHash = false;
    var stagedReads = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true,
      requireReadbackEvidence: true,
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
            'file_name': 'Latest file name.bin',
            'saved_name': 'Latest saved name',
            'content_type': 'application/octet-stream',
            'detected_type': 'latest-detected',
            'detected_service': 'latest-service',
            'asset_type': 'latest-asset',
            'file_name_ciphertext': encryptedName,
            'saved_name_ciphertext': oldSavedName,
            'content_type_ciphertext': oldContentType,
            'detected_type_ciphertext': oldDetectedType,
            'detected_service_ciphertext': oldDetectedService,
            'asset_type_ciphertext': oldAssetType,
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
          stagedReads++;
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
            'v2_ciphertext_sha256': corruptFinalHash && stagedReads == 2
                ? List<String>.filled(64, 'b').join()
                : List<String>.filled(64, 'a').join(),
            'readback_receipt': fileReceipt,
            'receipt_expires_at': receiptExpiry.toIso8601String(),
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
          final encoded = jsonEncode(body);
          for (final privateLabel in <String>[
            'Latest file name.bin', 'Latest saved name',
            'application/octet-stream', 'latest-detected',
            'latest-service', 'latest-asset',
          ]) {
            expect(encoded, isNot(contains(privateLabel)));
          }
          manifest = body;
          return const MigrationReply(
              200, <String, dynamic>{'file_id': 'synthetic-file'});
        }
        if (path.contains('/chunk/') && method == 'GET') {
          final index = int.parse(path.split('/').last);
          final readbackPhase =
              chunks.length == (manifest?['chunk_count'] ?? -1);
          inFlightChunkGets++;
          if (inFlightChunkGets > maxInFlightChunkGets) {
            maxInFlightChunkGets = inFlightChunkGets;
          }
          await Future<void>.delayed(Duration(
            milliseconds: readbackPhase && index == 0
                ? 10
                : index == 1 && !readbackPhase ? 10 : 1,
          ));
          inFlightChunkGets--;
          if (readbackPhase) readbackCompletions.add(index);
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
          if (body['chunk_index'] == 0 && interruptSecondChunkOnce) {
            // The paired second write fails first. The stager must await this
            // idempotent write before reporting failure or starting recovery.
            await Future<void>.delayed(const Duration(milliseconds: 20));
          }
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
    expect(
      calls.where((call) => call.startsWith(
          'GET /vault/file-v2/synthetic-file/chunk/')),
      isEmpty,
    );
    final second = await stager.stageAndVerify();
    expect(second.filesVerified, 1);
    expect(second.verifiedReadbacks, hasLength(1));
    expect(second.verifiedReadbacks.single.recordId, 'synthetic-file');
    expect(second.verifiedReadbacks.single.sourceSnapshot, _snapshotA);
    expect(second.verifiedReadbacks.single.readbackReceipt, fileReceipt);
    expect(second.verifiedReadbacks.single.isFile, isTrue);
    expect(chunks.length, 2);
    expect(calls.where((c) => c == 'POST /vault/file-v2/manifest').length, 1);
    final writes = calls.where((c) => c == 'PUT /vault/file-v2/chunk').length;
    final third = await stager.stageAndVerify();
    expect(third.filesVerified, 1);
    stagedReads = 0;
    corruptFinalHash = true;
    await expectLater(stager.stageAndVerify(), throwsFormatException);
    expect(maxInFlightChunkGets, 2);
    expect(readbackCompletions.sublist(readbackCompletions.length - 2),
        <int>[1, 0]);
    expect(calls.where((c) => c == 'PUT /vault/file-v2/chunk').length, writes);
    expect(calls.any((c) => c.contains('retire')), isFalse);
    final manifestPlain = jsonDecode(utf8.decode(await aesGcmUnwrap(
      metadataKey,
      b64urlDecode(manifest!['manifest_ciphertext'] as String),
    ))) as Map<String, dynamic>;
    final labels = manifestPlain['encrypted_metadata'] as Map<String, dynamic>;
    for (final entry in <String, String>{
      'file_name_ciphertext': 'Latest file name.bin',
      'saved_name_ciphertext': 'Latest saved name',
      'content_type_ciphertext': 'application/octet-stream',
      'detected_type_ciphertext': 'latest-detected',
      'detected_service_ciphertext': 'latest-service',
      'asset_type_ciphertext': 'latest-asset',
    }.entries) {
      expect(utf8.decode(await aesGcmUnwrap(
        metadataKey, b64urlDecode(labels[entry.key] as String),
      )), entry.value);
    }
  });

  test('stages legacy text and path in an opaque V2 manifest', () async {
    final legacy = await _legacyEncrypt(const <int>[1, 2, 3]);
    const fileId = 'synthetic-extra-file';
    const extras = <String, String?>{
      'relative_path': 'private/folder/file.txt',
      'extracted_text': 'synthetic private document text',
    };
    final calls = <String>[];
    Map<String, dynamic>? manifest;
    String? chunk;
    var oldSidecar = true;
    final result = await LegacyContentMigrationStager(
      enabled: true,
      recoveryEnabled: true,
      extraFileMetadataEnabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[
          <String, dynamic>{
            'file_id': fileId,
            'ciphertext_chars': legacy.length,
            'extra_text_bytes': utf8.encode(extras['extracted_text']!).length,
            'extra_path_bytes': utf8.encode(extras['relative_path']!).length,
          },
        ],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: <String, String>{fileId: legacy},
        fileSourceMetadata: <String, Map<String, dynamic>>{
          fileId: <String, dynamic>{
            'file_size': 3,
            'file_name': 'synthetic.txt',
            'content_type': 'text/plain',
            'has_legacy_extra_data': true,
          },
        },
        fileExtras: const <String, Map<String, String?>>{fileId: extras},
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (path.endsWith('/file-staged/$fileId')) {
          if (oldSidecar) {
            return const MigrationReply(409, <String, dynamic>{
              'detail': 'file_extra_legacy_data_requires_migration',
            });
          }
          if (manifest == null) {
            return const MigrationReply(
              409, <String, dynamic>{'detail': 'file_v2_not_staged'},
            );
          }
          return MigrationReply(200, <String, dynamic>{
            'file_id': fileId,
            'source_snapshot': _snapshotA,
            'total_bytes': 3,
            'chunk_count': 1,
            'manifest_ciphertext': manifest!['manifest_ciphertext'],
            'migration_metadata_version': 2,
          });
        }
        if (method == 'POST' && path.endsWith('/file-reset-stage')) {
          expect(body!['source_snapshot'], _snapshotA);
          expect(body['zk_proof_token'], 'synthetic-opaque-proof');
          oldSidecar = false;
          return const MigrationReply(200, <String, dynamic>{
            'file_id': fileId,
            'stage_reset': true,
          });
        }
        if (method == 'GET' && path.endsWith('/manifest')) {
          return const MigrationReply(
            404, <String, dynamic>{'detail': 'file_v2_not_found'},
          );
        }
        if (method == 'POST' && path == '/vault/file-v2/manifest') {
          expect(body!['migration_metadata_version'], 2);
          expect(body['migrating_legacy'], isTrue);
          expect(jsonEncode(body), isNot(contains(extras['extracted_text'])));
          expect(jsonEncode(body), isNot(contains(extras['relative_path'])));
          manifest = body;
          return const MigrationReply(200, <String, dynamic>{});
        }
        if (method == 'GET' && path.endsWith('/chunk/0')) {
          return chunk == null
              ? const MigrationReply(404,
                  <String, dynamic>{'detail': 'file_v2_chunk_not_found'})
              : MigrationReply(200, <String, dynamic>{
                  'file_id': fileId,
                  'chunk_index': 0,
                  'ciphertext': chunk,
                });
        }
        if (method == 'PUT' && path == '/vault/file-v2/chunk') {
          chunk = body!['ciphertext'] as String;
          return const MigrationReply(200, <String, dynamic>{});
        }
        fail('Unexpected synthetic migration request');
      },
    ).stageAndVerify();
    expect(result.filesVerified, 1);
    expect(result.filesDeferredForExtraLegacyData, 0);
    expect(calls.where((call) => call.endsWith('/file-reset-stage')), hasLength(1));
    expect(calls.any((call) => call.contains('retire')), isFalse);
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final decoded = jsonDecode(utf8.decode(await aesGcmUnwrap(
      key, b64urlDecode(manifest!['manifest_ciphertext'] as String),
    ))) as Map<String, dynamic>;
    expect(decoded['schema'], 'vaultai.file.migrated.v2');
    expect(decoded['legacy_extra'], extras);
  });

  test('stale source rejection aborts without deleting legacy item', () async {
    final legacy = await _legacyEncrypt(utf8.encode(jsonEncode(
      <String, Object>{'note': 'synthetic protected value'},
    )));
    final calls = <String>[];
    var stageWrites = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true,
      recoveryEnabled: true,
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
    expect(calls.any((call) => call.contains('reset-stage')), isFalse,
        reason: 'a source changing during the request is not a stale sidecar');
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
    expect(legacy, isNotEmpty);
  });

  test('stale item stage resets once with fresh proof and restages', () async {
    final oldLegacy = await _legacyEncrypt(utf8.encode('{"value":"old"}'));
    final currentLegacy = await _legacyEncrypt(utf8.encode('{"value":"new"}'));
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final oldStage = await codec.stageItem(
      itemId: 9, itemType: 'note', service: 'Synthetic title',
      legacyCiphertext: oldLegacy,
    );
    Map<String, dynamic>? staged = Map<String, dynamic>.from(oldStage.toStageBody());
    final sourceSnapshots = <int, String>{9: _snapshotA};
    final calls = <String>[];
    var proofs = 0;
    var resets = 0;
    var writes = 0;
    final export = _export(
      itemRows: <Map<String, dynamic>>[
        {'item_id': 9, 'ciphertext_chars': currentLegacy.length,
         'item_type': 'note', 'service': 'Synthetic title'},
      ],
      fileRows: const [],
      itemCiphertexts: {9: currentLegacy},
      fileCiphertexts: const {},
      itemSnapshots: sourceSnapshots,
      calls: calls,
      proofProvider: () async => 'synthetic-proof-${++proofs}',
    );
    Future<MigrationReply> request(String method, String path,
        [Map<String, dynamic>? body]) async {
      calls.add('$method $path');
      if (method == 'GET' && path.endsWith('/item-staged/9')) {
        return staged == null
            ? const MigrationReply(409, {'detail': 'item_not_staged'})
            : MigrationReply(200, {
                'item_id': 9,
                ...staged!,
                'source_snapshot': writes == 0 ? _snapshotA : List.filled(43, 'C').join(),
              });
      }
      if (method == 'POST' && path.endsWith('/item-reset-stage')) {
        resets++;
        expect(body!.keys.toSet(), {'item_id', 'source_snapshot', 'zk_proof_token'});
        expect(body['source_snapshot'], _snapshotA);
        expect(body['zk_proof_token'], startsWith('synthetic-proof-'));
        staged = null;
        sourceSnapshots[9] = _snapshotB;
        return const MigrationReply(200, {'item_id': 9, 'stage_reset': true});
      }
      if (method == 'POST' && path.endsWith('/item-stage')) {
        writes++;
        expect(body!['source_snapshot'], _snapshotB);
        expect(body.containsKey('pin'), isFalse);
        staged = Map<String, dynamic>.from(body);
        return MigrationReply(200, {
          'item_id': 9, 'staged': true,
          'source_snapshot': List.filled(43, 'C').join(),
        });
      }
      fail('Unexpected item recovery request $method $path');
    }
    await expectLater(
      LegacyContentMigrationStager(enabled: true, export: export,
          codec: codec, request: request).stageAndVerify(),
      throwsA(isA<Exception>()),
    );
    expect(resets, 0, reason: 'recovery is off unless explicitly enabled');
    final result = await LegacyContentMigrationStager(
      enabled: true, recoveryEnabled: true, export: export,
      codec: codec, request: request,
    ).stageAndVerify();
    expect(result.itemsVerified, 1);
    expect(resets, 1);
    expect(writes, 1);
    expect(proofs, greaterThanOrEqualTo(3),
        reason: 'export, reset, and restage require fresh proofs');
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
  });

  test('authoritative item snapshot mismatch takes one proof-bound reset',
      () async {
    final legacy = await _legacyEncrypt(utf8.encode('{"value":"synthetic"}'));
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final existing = await codec.stageItem(
      itemId: 9, itemType: 'note', service: 'Synthetic title',
      legacyCiphertext: legacy,
    );
    final snapshots = <int, String>{9: _snapshotA};
    final calls = <String>[];
    Map<String, dynamic>? staged = existing.toStageBody();
    var resets = 0;
    var writes = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true, recoveryEnabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[{
          'item_id': 9, 'ciphertext_chars': legacy.length,
          'item_type': 'note', 'service': 'Synthetic title',
        }],
        fileRows: const [],
        itemCiphertexts: {9: legacy},
        fileCiphertexts: const {},
        itemSnapshots: snapshots,
        calls: calls,
      ),
      codec: codec,
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' && path.endsWith('/item-staged/9')) {
          return staged == null
              ? const MigrationReply(409, {'detail': 'item_not_staged'})
              : MigrationReply(200, {
                  'item_id': 9,
                  ...staged!,
                  'source_snapshot': writes == 0 ? _snapshotB : _snapshotA,
                });
        }
        if (method == 'POST' && path.endsWith('/item-reset-stage')) {
          resets++;
          expect(body!['source_snapshot'], _snapshotA);
          expect(body['zk_proof_token'], isNotEmpty);
          staged = null;
          snapshots[9] = _snapshotB;
          return const MigrationReply(200,
              {'item_id': 9, 'stage_reset': true});
        }
        if (method == 'POST' && path.endsWith('/item-stage')) {
          writes++;
          expect(body!['source_snapshot'], _snapshotB);
          staged = Map<String, dynamic>.from(body);
          snapshots[9] = _snapshotA;
          return MigrationReply(200, {
            'item_id': 9, 'staged': true, 'source_snapshot': _snapshotA,
          });
        }
        fail('Unexpected item staging request $method $path');
      },
    );
    final result = await stager.stageAndVerify();
    expect(result.itemsVerified, 1);
    expect(resets, 1);
    expect(writes, 1);
    expect(calls.where((call) => call.contains('item-reset-stage')), hasLength(1));
    expect(calls.any((call) => call.contains('retire')), isFalse);
  });

  test('stale file stage resets once and verifies current bytes', () async {
    final oldBytes = List<int>.filled(32, 1);
    final currentBytes = List<int>.filled(32, 2);
    final oldLegacy = await _legacyEncrypt(oldBytes);
    final currentLegacy = await _legacyEncrypt(currentBytes);
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
    final oldName = b64urlEncode(
      await aesGcmWrap(metadataKey, utf8.encode('Old name.txt')),
    );
    final oldPrepared = await codec.stageFile(
      fileId: 'synthetic-file', legacyCiphertext: oldLegacy,
      declaredFileSize: oldBytes.length, contentType: 'text/plain',
      encryptedMetadata: {'file_name_ciphertext': oldName},
    );
    Map<String, dynamic>? manifest = Map<String, dynamic>.from(oldPrepared.toManifestBody());
    final chunks = <int, String>{
      for (var i = 0; i < oldPrepared.chunkCiphertexts.length; i++)
        i: oldPrepared.chunkCiphertexts[i],
    };
    final fileSnapshots = <String, String>{'synthetic-file': _snapshotA};
    final calls = <String>[];
    var proofs = 0;
    var resets = 0;
    var writes = 0;
    final export = _export(
      itemRows: const [],
      fileRows: <Map<String, dynamic>>[{
        'file_id': 'synthetic-file',
        'ciphertext_chars': currentLegacy.length,
        'file_size': currentBytes.length,
        'file_name': 'Current name.txt',
        'content_type': 'text/plain',
      }],
      itemCiphertexts: const {},
      fileCiphertexts: {'synthetic-file': currentLegacy},
      fileSnapshots: fileSnapshots,
      calls: calls,
      proofProvider: () async => 'synthetic-proof-${++proofs}',
    );
    Future<MigrationReply> request(String method, String path,
        [Map<String, dynamic>? body]) async {
      calls.add('$method $path');
      if (method == 'GET' && path.endsWith('/file-staged/synthetic-file')) {
        return manifest == null
            ? const MigrationReply(409, {'detail': 'file_v2_not_staged'})
            : MigrationReply(200, {
                'file_id': 'synthetic-file',
                'source_snapshot': fileSnapshots['synthetic-file'],
                'total_bytes': currentBytes.length,
                'chunk_count': manifest!['chunk_count'],
                'manifest_ciphertext': manifest!['manifest_ciphertext'],
              });
      }
      if (method == 'GET' && path.endsWith('/manifest')) {
        return manifest == null
            ? const MigrationReply(404, {'detail': 'file_v2_not_found'})
            : MigrationReply(200, manifest!);
      }
      if (method == 'GET' && path.contains('/chunk/')) {
        final index = int.parse(path.split('/').last);
        return chunks[index] == null
            ? const MigrationReply(404, {'detail': 'file_v2_chunk_not_found'})
            : MigrationReply(200, {
                'file_id': 'synthetic-file', 'chunk_index': index,
                'ciphertext': chunks[index],
              });
      }
      if (method == 'POST' && path.endsWith('/file-reset-stage')) {
        resets++;
        expect(body!.keys.toSet(), {'file_id', 'source_snapshot', 'zk_proof_token'});
        expect(body['source_snapshot'], _snapshotA);
        manifest = null;
        chunks.clear();
        fileSnapshots['synthetic-file'] = _snapshotB;
        return const MigrationReply(200,
            {'file_id': 'synthetic-file', 'stage_reset': true});
      }
      if (method == 'POST' && path == '/vault/file-v2/manifest') {
        writes++;
        expect(body!['source_snapshot'], _snapshotB);
        expect(body.containsKey('pin'), isFalse);
        manifest = body;
        return const MigrationReply(200, {'file_id': 'synthetic-file'});
      }
      if (method == 'PUT' && path == '/vault/file-v2/chunk') {
        chunks[body!['chunk_index'] as int] = body['ciphertext'] as String;
        return const MigrationReply(200, {'file_id': 'synthetic-file'});
      }
      fail('Unexpected file recovery request $method $path');
    }
    final result = await LegacyContentMigrationStager(
      enabled: true, recoveryEnabled: true, export: export,
      codec: codec, request: request,
    ).stageAndVerify();
    expect(result.filesVerified, 1);
    expect(resets, 1);
    expect(writes, 1);
    expect(proofs, greaterThanOrEqualTo(3));
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
  });

  test('unreadable file after a V2 reset still aborts the batch', () async {
    final valid = await _legacyEncrypt(<int>[1, 2, 3]);
    final wrongKey = SecretKey(List<int>.filled(32, 88));
    final wrongBox = await AesGcm.with256bits().encrypt(
      <int>[1, 2, 3], secretKey: wrongKey,
      nonce: List<int>.generate(12, (i) => i + 4),
    );
    final unreadable = base64.encode(<int>[
      ...wrongBox.nonce, ...wrongBox.cipherText, ...wrongBox.mac.bytes,
    ]);
    final fileCiphertexts = <String, String>{'synthetic-file': valid};
    final calls = <String>[];
    var resets = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true,
      recoveryEnabled: true,
      export: _export(
        itemRows: const <Map<String, dynamic>>[],
        fileRows: <Map<String, dynamic>>[<String, dynamic>{
          'file_id': 'synthetic-file',
          'ciphertext_chars': valid.length,
          'file_size': 3,
          'file_name': 'synthetic-file.bin',
        }],
        itemCiphertexts: const <int, String>{},
        fileCiphertexts: fileCiphertexts,
        calls: calls,
      ),
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey, mvk: _mvk,
      ),
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' && path.endsWith('/file-staged/synthetic-file')) {
          return MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-file',
            'source_snapshot': _snapshotA,
            'total_bytes': 3,
            'chunk_count': 0,
            'manifest_ciphertext': 'synthetic-sidecar',
          });
        }
        if (method == 'POST' && path.endsWith('/file-reset-stage')) {
          resets++;
          fileCiphertexts['synthetic-file'] = unreadable;
          return const MigrationReply(200, <String, dynamic>{
            'file_id': 'synthetic-file', 'stage_reset': true,
          });
        }
        throw StateError('unexpected V2 stage route');
      },
    );
    await expectLater(stager.stageAndVerify(), throwsStateError);
    expect(resets, 1);
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
  });

  test('second stale stage fails closed without a second reset', () async {
    final oldLegacy = await _legacyEncrypt(utf8.encode('{"value":"old"}'));
    final currentLegacy = await _legacyEncrypt(utf8.encode('{"value":"new"}'));
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey, mvk: _mvk,
    );
    final oldStage = await codec.stageItem(
      itemId: 11, itemType: 'note', service: 'Synthetic title',
      legacyCiphertext: oldLegacy,
    );
    final calls = <String>[];
    var resets = 0;
    final stager = LegacyContentMigrationStager(
      enabled: true, recoveryEnabled: true,
      export: _export(
        itemRows: <Map<String, dynamic>>[{
          'item_id': 11, 'ciphertext_chars': currentLegacy.length,
          'item_type': 'note', 'service': 'Synthetic title',
        }],
        fileRows: const [],
        itemCiphertexts: {11: currentLegacy},
        fileCiphertexts: const {},
        calls: calls,
      ),
      codec: codec,
      request: (method, path, [body]) async {
        calls.add('$method $path');
        if (method == 'GET' && path.endsWith('/item-staged/11')) {
          return MigrationReply(200, {
            'item_id': 11, ...oldStage.toStageBody(),
            'source_snapshot': _snapshotA,
          });
        }
        if (method == 'POST' && path.endsWith('/item-reset-stage')) {
          resets++;
          return const MigrationReply(200,
              {'item_id': 11, 'stage_reset': true});
        }
        fail('Unexpected second-conflict request');
      },
    );
    await expectLater(stager.stageAndVerify(), throwsA(isA<Exception>()));
    expect(resets, 1);
    expect(calls.any((call) => call.contains('retire') ||
        call.startsWith('DELETE ')), isFalse);
  });
}
