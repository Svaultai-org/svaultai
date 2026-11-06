// Read older encrypted chunk frames through a proof-bound download token.
// File bytes and the legacy key remain on the owner device.

import 'dart:typed_data';

import '../chunked_aead.dart';

typedef LegacyChunkFrameRead = Future<Uint8List> Function(int chunkIndex);

class LegacyChunkedLocalDownload {
  static const int maxChunkBytes = 16 * 1024 * 1024;
  static const int maxChunks = 4096;
  static const int maxInMemoryFileBytes = 512 * 1024 * 1024;

  final LegacyChunkFrameRead readEncryptedFrame;
  final List<int> legacyKey;
  final bool Function() accessIsCurrent;

  const LegacyChunkedLocalDownload({
    required this.readEncryptedFrame,
    required this.legacyKey,
    required this.accessIsCurrent,
  });

  Future<Uint8List> read({
    required int fileSize,
    required int chunkSize,
    required int chunkCount,
  }) async {
    if (fileSize < 0 ||
        fileSize > maxInMemoryFileBytes ||
        chunkSize <= 0 ||
        chunkSize > maxChunkBytes ||
        chunkCount < 0 ||
        chunkCount > maxChunks ||
        fileSize > chunkCount * chunkSize ||
        (chunkCount == 0 && fileSize != 0) ||
        (chunkCount > 0 && fileSize <= (chunkCount - 1) * chunkSize)) {
      throw const FormatException('Invalid older chunked-file size');
    }
    if (legacyKey.length != 32) {
      throw const FormatException('Invalid older file key');
    }
    void checkAccess() {
      if (!accessIsCurrent()) {
        throw StateError('Vault access changed during file download');
      }
    }

    checkAccess();
    final out = Uint8List(fileSize);
    var offset = 0;
    for (var index = 0; index < chunkCount; index++) {
      checkAccess();
      final frame = await readEncryptedFrame(index);
      checkAccess();
      final plain = await decryptChunk(
        frame: frame,
        key: legacyKey,
        chunkIndex: index,
      );
      checkAccess();
      final expected = index == chunkCount - 1 ? fileSize - offset : chunkSize;
      if (plain.length != expected) {
        throw const FormatException('Older file changed during download');
      }
      out.setRange(offset, offset + expected, plain);
      offset += expected;
    }
    checkAccess();
    if (offset != fileSize) {
      throw const FormatException('Older file size did not match');
    }
    return out;
  }
}
