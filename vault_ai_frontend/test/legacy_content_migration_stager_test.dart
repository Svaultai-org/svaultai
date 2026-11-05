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
  LegacyProofProvider? proofProvider,
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
