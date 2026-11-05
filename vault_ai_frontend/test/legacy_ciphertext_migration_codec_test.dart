import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';

final SecretKey _legacyKey = SecretKey(List<int>.filled(32, 7));
final SecretKey _mvk = SecretKey(List<int>.filled(32, 19));

Future<String> _legacyEncrypt(List<int> plain) async {
  final aes = AesGcm.with256bits();
  final box = await aes.encrypt(
    plain,
    secretKey: _legacyKey,
    nonce: List<int>.generate(12, (i) => i + 1),
  );
  return base64.encode(<int>[
    ...box.nonce,
    ...box.cipherText,
    ...box.mac.bytes,
  ]);
}

void main() {
  group('legacy ciphertext rewrapping', () {
    test('stages an item without plaintext fields and verifies remote readback',
        () async {
      const marker = 'synthetic-item-secret-only';
      final legacy =
          await _legacyEncrypt(utf8.encode(jsonEncode(<String, Object>{
        'username': 'synthetic-user',
        'note': marker,
        'flags': <Object>[1, true, 'sample'],
      })));
      final codec = LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      );
      final staged = await codec.stageItem(
        itemId: 12,
        itemType: 'login',
        service: 'synthetic.example',
        legacyCiphertext: legacy,
      );
      final body = jsonEncode(staged.toStageBody());
      expect(body, isNot(contains(marker)));
      expect(body, isNot(contains('synthetic-user')));
      expect(body, isNot(contains('synthetic.example')));
      expect(body, isNot(contains(legacy)));
      expect(
        await codec.verifyStagedItem(
          itemType: 'login',
          service: 'synthetic.example',
          legacyCiphertext: legacy,
          itemTypeCiphertext: staged.itemTypeCiphertext,
          serviceCiphertext: staged.serviceCiphertext,
          payloadCiphertext: staged.payloadCiphertext,
        ),
        isTrue,
      );
      expect(
        await codec.verifyStagedItem(
          itemType: 'login',
          service: 'another.example',
          legacyCiphertext: legacy,
          itemTypeCiphertext: staged.itemTypeCiphertext,
          serviceCiphertext: staged.serviceCiphertext,
          payloadCiphertext: staged.payloadCiphertext,
        ),
        isFalse,
      );
      expect(
        await codec.verifyStagedItem(
          itemType: 'login',
          service: 'synthetic.example',
          legacyCiphertext: legacy,
          itemTypeCiphertext: staged.itemTypeCiphertext,
          serviceCiphertext: staged.serviceCiphertext,
          payloadCiphertext: 'invalid',
        ),
        isFalse,
      );
    });

    test('does not stage corrupt legacy item ciphertext', () async {
      final codec = LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      );
      await expectLater(
        codec.stageItem(
          itemId: 3,
          itemType: 'login',
          service: 'synthetic.example',
          legacyCiphertext: base64.encode(List<int>.filled(28, 0)),
        ),
        throwsA(isA<Exception>()),
      );
    });

    test('stages file chunks and checks every readback byte and metadata',
        () async {
      final bytes = Uint8List.fromList(
        List<int>.generate(307, (i) => (i * 37) & 255),
      );
      final legacy = await _legacyEncrypt(bytes);
      final codec = LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      );
      final staged = await codec.stageFile(
        fileId: 'synthetic-file-3',
        legacyCiphertext: legacy,
        declaredFileSize: bytes.length,
        contentType: 'application/octet-stream',
        encryptedMetadata: const <String, String?>{
          'file_name_ciphertext': 'synthetic-encrypted-name',
          'saved_name_ciphertext': null,
        },
        chunkSize: 64,
      );
      expect(staged.chunkCiphertexts.length, 5);
      expect(staged.toManifestBody()['total_bytes'], bytes.length);
      expect(staged.chunkBody(0)['ciphertext'], staged.chunkCiphertexts[0]);
      final outgoing = jsonEncode(<Object>[
        staged.toManifestBody(),
        for (var i = 0; i < staged.chunkCiphertexts.length; i++)
          staged.chunkBody(i),
      ]);
      expect(outgoing, isNot(contains(legacy)));
      expect(
        await codec.verifyStagedFileManifest(
          fileId: staged.fileId,
          declaredFileSize: staged.totalBytes,
          contentType: 'application/octet-stream',
          encryptedMetadata: const <String, String?>{
            'file_name_ciphertext': 'synthetic-encrypted-name',
            'saved_name_ciphertext': null,
          },
          chunkSize: staged.chunkSize,
          chunkCount: staged.chunkCiphertexts.length,
          manifestCiphertext: staged.manifestCiphertext,
        ),
        isTrue,
      );
      Future<bool> verify(List<String> chunks, {String? contentType}) =>
          codec.verifyStagedFile(
            fileId: staged.fileId,
            legacyCiphertext: legacy,
            declaredFileSize: staged.totalBytes,
            contentType: contentType ?? 'application/octet-stream',
            encryptedMetadata: const <String, String?>{
              'file_name_ciphertext': 'synthetic-encrypted-name',
              'saved_name_ciphertext': null,
            },
            chunkSize: staged.chunkSize,
            chunkCount: staged.chunkCiphertexts.length,
            manifestCiphertext: staged.manifestCiphertext,
            chunkCiphertexts: chunks,
          );
      expect(await verify(staged.chunkCiphertexts), isTrue);
      expect(await verify(staged.chunkCiphertexts, contentType: 'text/plain'),
          isFalse);
      final tampered = List<String>.of(staged.chunkCiphertexts);
      tampered[2] = tampered[1];
      expect(await verify(tampered), isFalse);
      expect(await verify(tampered.sublist(1)), isFalse);
    });

    test('handles an empty legacy file without inventing a chunk', () async {
      final codec = LegacyCiphertextMigrationCodec(
        legacyKey: _legacyKey,
        mvk: _mvk,
      );
      final legacy = await _legacyEncrypt(const <int>[]);
      final staged = await codec.stageFile(
        fileId: 'empty-synthetic-file',
        legacyCiphertext: legacy,
        declaredFileSize: 0,
        contentType: 'application/octet-stream',
        encryptedMetadata: const <String, String?>{},
      );
      expect(staged.chunkCiphertexts, isEmpty);
      expect(
        await codec.verifyStagedFile(
          fileId: staged.fileId,
          legacyCiphertext: legacy,
          declaredFileSize: 0,
          contentType: 'application/octet-stream',
          encryptedMetadata: const <String, String?>{},
          chunkSize: staged.chunkSize,
          chunkCount: 0,
          manifestCiphertext: staged.manifestCiphertext,
          chunkCiphertexts: const <String>[],
        ),
        isTrue,
      );
    });
  });
}
