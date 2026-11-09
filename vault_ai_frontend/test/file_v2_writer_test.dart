import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 47));
  final writer = FileV2Writer(mvk);

  test('new private file is encrypted, read back and verified before publish',
      () async {
    final id = FileV2Writer.newFileId();
    final bytes = Uint8List.fromList(utf8.encode('synthetic private bytes'));
    final prepared = await writer.prepare(
      fileId: id,
      fileName: 'private-note.txt',
      contentType: 'text/plain',
      bytes: bytes,
      chunkSize: 7,
    );
    expect(prepared.toManifestBody()['migrating_legacy'], false);
    expect(prepared.toManifestBody().toString(), isNot(contains('private-note')));
    expect(prepared.toManifestBody().toString(), isNot(contains('synthetic private bytes')));
    expect(prepared.chunkCiphertexts.join(''), isNot(contains('synthetic private bytes')));

    Future<Map<String, dynamic>> get(String path) async {
      if (path.endsWith('/manifest')) {
        return <String, dynamic>{
          ...prepared.toManifestBody(),
          'lifecycle_state': 'file_v2_written',
          'verification_state': 'not_verified',
        };
      }
      final index = int.parse(path.split('/').last);
      return <String, dynamic>{
        ...prepared.chunkBody(index),
      };
    }

    expect(await writer.verifyReadback(
      prepared: prepared,
      originalBytes: bytes,
      get: get,
    ), isTrue);
    final opened = await FileV2Reader(mvk: mvk, get: get).download(id);
    expect(opened.manifest.displayName, 'private-note.txt');
    expect(opened.manifest.contentType, 'text/plain');
    expect(opened.bytes, bytes);
    expect(await writer.verifyReadback(
      prepared: prepared,
      originalBytes: Uint8List.fromList(utf8.encode('different')),
      get: get,
    ), isFalse);
  });

  test('corrupt server readback blocks publish and oversize input fails',
      () async {
    final id = FileV2Writer.newFileId();
    final bytes = Uint8List.fromList([1, 2, 3]);
    final prepared = await writer.prepare(
      fileId: id,
      fileName: 'tiny.bin',
      bytes: bytes,
    );
    expect(await writer.verifyReadback(
      prepared: prepared,
      originalBytes: bytes,
      get: (path) async => <String, dynamic>{
        'file_id': id,
        'crypto_version': 'client_mvk_v2',
        'manifest_ciphertext': 'invalid',
        'total_bytes': 3,
        'chunk_size': FileV2Writer.defaultChunkSize,
        'chunk_count': 1,
      },
    ), isFalse);
    expect(() => writer.prepare(
      fileId: id,
      fileName: 'too big',
      bytes: Uint8List(FileV2Writer.maxFileBytes + 1),
    ), throwsFormatException);
  });

  test('folder path is encrypted and readable on web and native clients',
      () async {
    final id = FileV2Writer.newFileId();
    const privatePath = 'Holiday/Beach/red shoes.jpg';
    final bytes = Uint8List.fromList(<int>[9, 8, 7]);
    final prepared = await writer.prepare(
      fileId: id,
      fileName: 'red shoes.jpg',
      relativePath: privatePath,
      bytes: bytes,
    );
    final body = jsonEncode(prepared.toManifestBody());
    expect(body, isNot(contains('Holiday')));
    expect(body, isNot(contains('Beach')));
    expect(body, isNot(contains('red shoes')));
    final manifest = await FileV2Reader(
      mvk: mvk,
      get: (path) async => <String, dynamic>{
        ...prepared.toManifestBody(),
        'lifecycle_state': 'file_v2_written',
        'verification_state': 'not_verified',
      },
    ).readManifest(id);
    expect(manifest.relativePath, privatePath);
    expect(manifest.fileName, 'red shoes.jpg');
    for (final invalid in <String>[
      '/Holiday/red shoes.jpg',
      'Holiday/../red shoes.jpg',
      'Holiday/other.jpg',
      'Holiday\\red shoes.jpg',
      'red shoes.jpg',
    ]) {
      await expectLater(
        writer.prepare(fileId: FileV2Writer.newFileId(),
            fileName: 'red shoes.jpg', relativePath: invalid, bytes: bytes),
        throwsFormatException,
      );
    }
  });
}
