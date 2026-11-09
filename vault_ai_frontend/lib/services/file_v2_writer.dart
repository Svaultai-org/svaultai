// Prepare a new file entirely on the unlocked client. Only MVK ciphertext,
// structural sizes, and a random file ID are sent to file-v2 routes.

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'file_v2_folder_path.dart';
import 'vault_key_hierarchy.dart';

class PreparedNewFileV2 {
  final String fileId;
  final int totalBytes;
  final int chunkSize;
  final int chunkCount;
  final String manifestCiphertext;

  /// Small files retain ciphertext for exact retry. Large files are encrypted
  /// a chunk at a time while uploading; existing chunks are decrypted and
  /// compared to the source before a retry accepts them.
  final List<String> chunkCiphertexts;

  const PreparedNewFileV2({
    required this.fileId,
    required this.totalBytes,
    required this.chunkSize,
    required this.chunkCount,
    required this.manifestCiphertext,
    required this.chunkCiphertexts,
  });

  Map<String, Object> toManifestBody() => <String, Object>{
        'file_id': fileId,
        'crypto_version': 'client_mvk_v2',
        'manifest_ciphertext': manifestCiphertext,
        'total_bytes': totalBytes,
        'chunk_size': chunkSize,
        'chunk_count': chunkCount,
        'migrating_legacy': false,
      };

  Map<String, Object> chunkBody(int index) => <String, Object>{
        'file_id': fileId,
        'chunk_index': index,
        'ciphertext': chunkCiphertexts[index],
      };
}

class FileV2Writer {
  static const int maxFileBytes = FileV2Reader.maxDownloadBytes;
  static const int defaultChunkSize = 256 * 1024;
  static const int maxChunkBytes = 1024 * 1024;
  static const int maxChunks = 4096;
  static const int eagerCiphertextLimitBytes = 64 * 1024 * 1024;

  final SecretKey mvk;
  final int eagerLimitBytes;

  const FileV2Writer(
    this.mvk, {
    this.eagerLimitBytes = eagerCiphertextLimitBytes,
  });

  static int requireChunkCount(int totalBytes, int chunkSize) {
    if (totalBytes < 0 ||
        totalBytes > maxFileBytes ||
        chunkSize <= 0 ||
        chunkSize > maxChunkBytes) {
      throw const FormatException('Invalid private file size');
    }
    final count = (totalBytes + chunkSize - 1) ~/ chunkSize;
    if (count > maxChunks) {
      throw const FormatException('Private file has too many chunks');
    }
    return count;
  }

  static String newFileId() {
    final random = Random.secure();
    return 'v2-${b64urlEncode(Uint8List.fromList(
      List<int>.generate(20, (_) => random.nextInt(256)),
    ))}';
  }

  Future<PreparedNewFileV2> prepare({
    required String fileId,
    required String fileName,
    required Uint8List bytes,
    String? savedName,
    String? contentType,
    String? relativePath,
    int chunkSize = defaultChunkSize,
  }) async {
    if (!RegExp(r'^v2-[A-Za-z0-9_-]{27}$').hasMatch(fileId) ||
        fileName.trim().isEmpty ||
        fileName.length > 255 ||
        (savedName?.length ?? 0) > 255 ||
        (contentType?.length ?? 0) > 255) {
      throw const FormatException('Invalid private file upload');
    }
    final chunkCount = requireChunkCount(bytes.length, chunkSize);
    final hierarchy = VaultKeyHierarchy(mvk);
    final metadataKey = await hierarchy.metadataKey();
    Future<String> wrapMetadata(String value) async =>
        b64urlEncode(await aesGcmWrap(metadataKey, utf8.encode(value)));
    final encryptedMetadata = <String, String>{
      'file_name_ciphertext': await wrapMetadata(fileName),
      if (savedName != null && savedName.trim().isNotEmpty)
        'saved_name_ciphertext': await wrapMetadata(savedName),
      if (contentType != null && contentType.isNotEmpty)
        'content_type_ciphertext': await wrapMetadata(contentType),
      if (relativePath != null)
        'relative_path_ciphertext': await wrapMetadata(
          requirePrivateV2RelativePath(relativePath, fileName: fileName),
        ),
    };
    final chunks = <String>[];
    if (bytes.length <= eagerLimitBytes) {
      final contentKey = await hierarchy.fileContentKey();
      for (var offset = 0; offset < bytes.length; offset += chunkSize) {
        final end = min(offset + chunkSize, bytes.length);
        chunks.add(b64urlEncode(await aesGcmWrap(
          contentKey,
          bytes.sublist(offset, end),
        )));
      }
    }
    final manifest = <String, Object?>{
      'schema': 'vaultai.file.migrated.v1',
      'file_id': fileId,
      'file_size': bytes.length,
      'content_type': null,
      'chunk_size': chunkSize,
      'chunk_count': chunkCount,
      'encrypted_metadata': encryptedMetadata,
    };
    return PreparedNewFileV2(
      fileId: fileId,
      totalBytes: bytes.length,
      chunkSize: chunkSize,
      chunkCount: chunkCount,
      manifestCiphertext: b64urlEncode(
        await aesGcmWrap(metadataKey, utf8.encode(jsonEncode(manifest))),
      ),
      chunkCiphertexts: List<String>.unmodifiable(chunks),
    );
  }

  Future<bool> verifyReadback({
    required PreparedNewFileV2 prepared,
    required Uint8List originalBytes,
    required FileV2Get get,
  }) async {
    try {
      if (originalBytes.length != prepared.totalBytes) return false;
      return await FileV2Reader(mvk: mvk, get: get)
          .matchesOriginalBytes(prepared.fileId, originalBytes);
    } catch (_) {
      return false;
    }
  }
}
