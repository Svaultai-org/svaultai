import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/chunked_aead.dart';
import 'package:vault_ai_frontend/services/legacy_chunked_local_download.dart';

void main() {
  final key = List<int>.filled(32, 41);

  test('decrypts two encrypted chunks locally in order', () async {
    final first = Uint8List.fromList([1, 2, 3, 4]);
    final second = Uint8List.fromList([5, 6]);
    final frames = <Uint8List>[
      await encryptChunk(plaintext: first, key: key, chunkIndex: 0),
      await encryptChunk(plaintext: second, key: key, chunkIndex: 1),
    ];
    final requested = <int>[];
    final result = await LegacyChunkedLocalDownload(
      readEncryptedFrame: (index) async {
        requested.add(index);
        return frames[index];
      },
      legacyKey: key,
      accessIsCurrent: () => true,
    ).read(fileSize: 6, chunkSize: 4, chunkCount: 2);
    expect(result, Uint8List.fromList([1, 2, 3, 4, 5, 6]));
    expect(requested, [0, 1]);
  });

  test('tampered ciphertext fails without yielding a file', () async {
    final frame = await encryptChunk(
      plaintext: [1, 2, 3],
      key: key,
      chunkIndex: 0,
    );
    frame[13] ^= 1;
    final reader = LegacyChunkedLocalDownload(
      readEncryptedFrame: (_) async => frame,
      legacyKey: key,
      accessIsCurrent: () => true,
    );
    await expectLater(
      reader.read(fileSize: 3, chunkSize: 3, chunkCount: 1),
      throwsA(isA<Exception>()),
    );
  });

  test('lost session stops before requesting another chunk', () async {
    final frame = await encryptChunk(
      plaintext: [1, 2, 3],
      key: key,
      chunkIndex: 0,
    );
    var current = true;
    final requested = <int>[];
    final reader = LegacyChunkedLocalDownload(
      readEncryptedFrame: (index) async {
        requested.add(index);
        current = false;
        return frame;
      },
      legacyKey: key,
      accessIsCurrent: () => current,
    );
    await expectLater(
      reader.read(fileSize: 6, chunkSize: 3, chunkCount: 2),
      throwsStateError,
    );
    expect(requested, [0]);
  });

  test('rejects mismatched decrypted chunk lengths', () async {
    final frame = await encryptChunk(
      plaintext: [1, 2, 3],
      key: key,
      chunkIndex: 0,
    );
    final reader = LegacyChunkedLocalDownload(
      readEncryptedFrame: (_) async => frame,
      legacyKey: key,
      accessIsCurrent: () => true,
    );
    await expectLater(
      reader.read(fileSize: 4, chunkSize: 4, chunkCount: 1),
      throwsFormatException,
    );
  });

  test('accepts the existing upload chunk cap of 16 MiB', () async {
    final frame = await encryptChunk(
      plaintext: [9],
      key: key,
      chunkIndex: 0,
    );
    final reader = LegacyChunkedLocalDownload(
      readEncryptedFrame: (_) async => frame,
      legacyKey: key,
      accessIsCurrent: () => true,
    );
    expect(
      await reader.read(
        fileSize: 1,
        chunkSize: LegacyChunkedLocalDownload.maxChunkBytes,
        chunkCount: 1,
      ),
      Uint8List.fromList([9]),
    );
  });
}
