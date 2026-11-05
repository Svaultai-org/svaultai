import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

final SecretKey _legacyKey = SecretKey(List<int>.filled(32, 17));
final SecretKey _mvk = SecretKey(List<int>.filled(32, 29));

Future<String> _legacyEncrypt(List<int> plain) async {
  final box = await AesGcm.with256bits().encrypt(
    plain,
    secretKey: _legacyKey,
    nonce: List<int>.generate(12, (i) => i + 3),
  );
  return base64.encode(<int>[
    ...box.nonce,
    ...box.cipherText,
    ...box.mac.bytes,
  ]);
}

void main() {
  test('lists and opens a staged file using MVK only', () async {
    final bytes = List<int>.generate(307, (i) => (i * 11) & 255);
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final fileNameCt = b64urlEncode(
      await aesGcmWrap(key, utf8.encode('synthetic-photo.jpg')),
    );
    final savedNameCt = b64urlEncode(
      await aesGcmWrap(key, utf8.encode('synthetic-memory.jpg')),
    );
    final contentTypeCt = b64urlEncode(
      await aesGcmWrap(key, utf8.encode('image/jpeg')),
    );
    final staged = await LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey,
      mvk: _mvk,
    ).stageFile(
      fileId: 'synthetic-file-7',
      legacyCiphertext: await _legacyEncrypt(bytes),
      declaredFileSize: bytes.length,
      contentType: null,
      encryptedMetadata: <String, String?>{
        'file_name_ciphertext': fileNameCt,
        'saved_name_ciphertext': savedNameCt,
        'content_type_ciphertext': contentTypeCt,
      },
      chunkSize: 64,
    );
    final paths = <String>[];
    final reader = FileV2Reader(
      mvk: _mvk,
      get: (path) async {
        paths.add(path);
        if (path == '/vault/file-v2') {
          return <String, dynamic>{
            'files': <Map<String, dynamic>>[
              <String, dynamic>{'file_id': staged.fileId},
            ],
          };
        }
        if (path.endsWith('/manifest')) {
          return <String, dynamic>{
            ...staged.toManifestBody(),
          };
        }
        if (path.contains('/chunk/')) {
          final index = int.parse(path.split('/').last);
          return <String, dynamic>{
            'file_id': staged.fileId,
            'chunk_index': index,
            'ciphertext': staged.chunkCiphertexts[index],
          };
        }
        fail('Unexpected V2 path');
      },
    );
    final listed = await reader.list();
    expect(listed, hasLength(1));
    expect(listed.single.displayName, 'synthetic-memory.jpg');
    expect(listed.single.contentType, 'image/jpeg');
    final opened = await reader.download(staged.fileId);
    expect(opened.bytes, bytes);
    expect(paths.any((p) => p.contains('download-file')), isFalse);
    expect(paths.any((p) => p.contains('pin')), isFalse);
  });

  test('rejects mismatched manifest identity and never returns file bytes',
      () async {
    final staged = await LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey,
      mvk: _mvk,
    ).stageFile(
      fileId: 'synthetic-file-8',
      legacyCiphertext: await _legacyEncrypt(const <int>[1, 2, 3]),
      declaredFileSize: 3,
      contentType: 'application/octet-stream',
      encryptedMetadata: const <String, String?>{},
    );
    final reader = FileV2Reader(
      mvk: _mvk,
      get: (_) async => <String, dynamic>{
        ...staged.toManifestBody(),
        'file_id': 'wrong-file-id',
      },
    );
    await expectLater(
      reader.download(staged.fileId),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects a corrupted encrypted chunk', () async {
    final staged = await LegacyCiphertextMigrationCodec(
      legacyKey: _legacyKey,
      mvk: _mvk,
    ).stageFile(
      fileId: 'synthetic-file-9',
      legacyCiphertext: await _legacyEncrypt(const <int>[4, 5, 6]),
      declaredFileSize: 3,
      contentType: 'application/octet-stream',
      encryptedMetadata: const <String, String?>{},
    );
    final reader = FileV2Reader(
      mvk: _mvk,
      get: (path) async => path.endsWith('/manifest')
          ? <String, dynamic>{...staged.toManifestBody()}
          : <String, dynamic>{
              'file_id': staged.fileId,
              'chunk_index': 0,
              'ciphertext': b64urlEncode(List<int>.filled(40, 0)),
            },
    );
    await expectLater(reader.download(staged.fileId), throwsA(anything));
  });
}
