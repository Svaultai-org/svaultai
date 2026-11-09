// Read client-MVK-v2 file manifests and chunks without a PIN or server-side
// decrypt. The caller supplies an authenticated GET transport; this service
// validates the encrypted manifest and every chunk before returning bytes.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_folder_path.dart';
import 'vault_key_hierarchy.dart';

typedef FileV2Get = Future<Map<String, dynamic>> Function(String path);

class FileV2ReadException implements Exception {
  final int statusCode;

  const FileV2ReadException(this.statusCode);

  @override
  String toString() => 'V2 file request failed ($statusCode)';
}

class FileV2LocalSizeLimitException implements Exception {
  final int totalBytes;
  final int limitBytes;

  const FileV2LocalSizeLimitException(this.totalBytes, this.limitBytes);

  @override
  String toString() => 'V2 file exceeds local size limit';
}

class FileV2Manifest {
  final String fileId;
  final int totalBytes;
  final int chunkSize;
  final int chunkCount;
  final String? fileName;
  final String? savedName;
  final String? contentType;
  final String? assetType;
  final String? detectedType;
  final String? detectedService;
  final String? relativePath;
  final String? extractedText;
  final bool retired;
  final bool readyForUse;
  final int nameVersion;

  const FileV2Manifest({
    required this.fileId,
    required this.totalBytes,
    required this.chunkSize,
    required this.chunkCount,
    required this.fileName,
    required this.savedName,
    required this.contentType,
    required this.assetType,
    required this.detectedType,
    required this.detectedService,
    this.relativePath,
    this.extractedText,
    required this.retired,
    required this.readyForUse,
    this.nameVersion = 0,
  });

  String get displayName => (savedName?.trim().isNotEmpty ?? false)
      ? savedName!
      : (fileName?.trim().isNotEmpty ?? false)
          ? fileName!
          : 'File';
}

class FileV2Download {
  final FileV2Manifest manifest;
  final Uint8List bytes;

  const FileV2Download({required this.manifest, required this.bytes});
}

class FileV2Reader {
  static const int maxDownloadBytes = 512 * 1024 * 1024;

  final SecretKey mvk;
  final FileV2Get get;

  const FileV2Reader({required this.mvk, required this.get});

  Future<List<FileV2Manifest>> list({
    bool retiredOnly = false,
    bool readyOnly = false,
  }) async {
    final response = await get('/vault/file-v2');
    final raw = response['files'];
    if (raw is! List) throw const FormatException('Invalid file list');
    final result = <FileV2Manifest>[];
    for (final row in raw) {
      if (row is! Map || row['file_id'] is! String) {
        throw const FormatException('Invalid file listing entry');
      }
      if (retiredOnly && !_isRetired(row)) continue;
      if (readyOnly && !_isReady(row)) continue;
      result.add(
        await readManifest(
          row['file_id'] as String,
          requireRetired: retiredOnly,
          requireReady: readyOnly,
        ),
      );
    }
    return result;
  }

  Future<FileV2Manifest> readManifest(
    String fileId, {
    bool requireRetired = false,
    bool requireReady = false,
  }) async {
    if (fileId.isEmpty) throw const FormatException('Invalid file ID');
    final response = await get(
      '/vault/file-v2/${Uri.encodeComponent(fileId)}/manifest',
    );
    if (response['file_id'] != fileId ||
        response['crypto_version'] != 'client_mvk_v2' ||
        response['manifest_ciphertext'] is! String) {
      throw const FormatException('Invalid V2 file manifest');
    }
    final retired = _isRetired(response);
    if (requireRetired && !retired) {
      throw const FormatException('V2 file is not ready for use');
    }
    final ready = _isReady(response);
    if (requireReady && !ready) {
      throw const FormatException('V2 file is not ready for use');
    }
    final total = response['total_bytes'];
    final chunkSize = response['chunk_size'];
    final chunkCount = response['chunk_count'];
    if (total is! int ||
        total < 0 ||
        total > maxDownloadBytes ||
        chunkSize is! int ||
        chunkSize <= 0 ||
        chunkCount is! int ||
        chunkCount < 0 ||
        chunkCount != (total + chunkSize - 1) ~/ chunkSize) {
      throw const FormatException('Invalid V2 file framing');
    }
    final migrationMetadataVersion =
        response['migration_metadata_version'] ?? 1;
    if (migrationMetadataVersion is! int ||
        migrationMetadataVersion < 1 ||
        migrationMetadataVersion > 3) {
      throw const FormatException('Invalid V2 file metadata version');
    }
    final encodedManifest = response['manifest_ciphertext'] as String;
    final maxManifestBytes = migrationMetadataVersion == 3
        ? 2 * 1024 * 1024
        : migrationMetadataVersion == 2
            ? 512 * 1024
            : 128 * 1024;
    if (encodedManifest.length > ((maxManifestBytes + 64) * 4 ~/ 3) + 8) {
      throw const FormatException('V2 file manifest exceeds safe limit');
    }
    final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
    final plaintext = await aesGcmUnwrap(
      metadataKey,
      b64urlDecode(encodedManifest),
    );
    final decoded = jsonDecode(utf8.decode(plaintext));
    if (decoded is! Map ||
        decoded['schema'] !=
            (migrationMetadataVersion == 2
                ? 'vaultai.file.migrated.v2'
                : migrationMetadataVersion == 3
                    ? 'vaultai.file.migrated.v3'
                    : 'vaultai.file.migrated.v1') ||
        decoded['file_id'] != fileId ||
        decoded['file_size'] != total ||
        decoded['chunk_size'] != chunkSize ||
        decoded['chunk_count'] != chunkCount) {
      throw const FormatException('V2 file manifest mismatch');
    }
    String? relativePath;
    String? extractedText;
    if (migrationMetadataVersion >= 2) {
      final extra = decoded['legacy_extra'];
      if (extra is! Map ||
          extra.length != 2 ||
          !extra.containsKey('relative_path') ||
          !extra.containsKey('extracted_text') ||
          (extra['relative_path'] != null &&
              extra['relative_path'] is! String) ||
          (extra['extracted_text'] != null &&
              extra['extracted_text'] is! String)) {
        throw const FormatException('Invalid V2 legacy file extras');
      }
      relativePath = extra['relative_path'] as String?;
      extractedText = extra['extracted_text'] as String?;
      if ((relativePath != null && utf8.encode(relativePath).length > 4096) ||
          (extractedText != null &&
              utf8.encode(extractedText).length >
                  (migrationMetadataVersion == 3 ? 256 * 1024 : 64 * 1024))) {
        throw const FormatException('V2 legacy file extras too large');
      }
    } else if (decoded.containsKey('legacy_extra')) {
      throw const FormatException('Unexpected V2 legacy file extras');
    }
    final metadata = decoded['encrypted_metadata'];
    if (metadata is! Map) {
      throw const FormatException('V2 file metadata missing');
    }
    Future<String?> unwrapMetadata(String name) async {
      final encoded = metadata[name];
      if (encoded == null) return null;
      if (encoded is! String || encoded.isEmpty) {
        throw const FormatException('Invalid encrypted file metadata');
      }
      return utf8.decode(
        await aesGcmUnwrap(metadataKey, b64urlDecode(encoded)),
      );
    }

    final nameVersion = response['name_version'] ?? 0;
    final nameOverride = response['saved_name_override_ciphertext'];
    if (nameVersion is! int ||
        nameVersion < 0 ||
        (nameVersion == 0 && nameOverride != null) ||
        (nameVersion > 0 &&
            (nameOverride is! String || nameOverride.isEmpty))) {
      throw const FormatException('Invalid V2 file name version');
    }
    String? savedNameOverride;
    if (nameOverride is String) {
      savedNameOverride = utf8.decode(
        await aesGcmUnwrap(metadataKey, b64urlDecode(nameOverride)),
      );
      if (savedNameOverride.trim().isEmpty || savedNameOverride.length > 255) {
        throw const FormatException('Invalid encrypted file name');
      }
    }

    final typeFromMetadata = await unwrapMetadata('content_type_ciphertext');
    final contentType = typeFromMetadata ?? decoded['content_type'];
    if (contentType != null && contentType is! String) {
      throw const FormatException('Invalid file content type');
    }
    final fileName = await unwrapMetadata('file_name_ciphertext');
    final privatePath = await unwrapMetadata('relative_path_ciphertext');
    if (privatePath != null) {
      if (migrationMetadataVersion != 1 || fileName == null) {
        throw const FormatException('Invalid private folder manifest');
      }
      relativePath = requirePrivateV2RelativePath(
        privatePath,
        fileName: fileName,
      );
    }
    return FileV2Manifest(
      fileId: fileId,
      totalBytes: total,
      chunkSize: chunkSize,
      chunkCount: chunkCount,
      fileName: fileName,
      savedName:
          savedNameOverride ?? await unwrapMetadata('saved_name_ciphertext'),
      contentType: contentType as String?,
      assetType: await unwrapMetadata('asset_type_ciphertext'),
      detectedType: await unwrapMetadata('detected_type_ciphertext'),
      detectedService: await unwrapMetadata('detected_service_ciphertext'),
      relativePath: relativePath,
      extractedText: extractedText,
      retired: retired,
      readyForUse: ready,
      nameVersion: nameVersion,
    );
  }

  Future<FileV2Download> download(
    String fileId, {
    bool requireRetired = false,
    bool requireReady = false,
    // Enforced after manifest validation, before allocating the output.
    int maxBytes = maxDownloadBytes,
  }) async {
    if (maxBytes < 0 || maxBytes > maxDownloadBytes) {
      throw ArgumentError.value(maxBytes, 'maxBytes');
    }
    final manifest = await readManifest(
      fileId,
      requireRetired: requireRetired,
      requireReady: requireReady,
    );
    if (manifest.totalBytes > maxBytes) {
      throw FileV2LocalSizeLimitException(manifest.totalBytes, maxBytes);
    }
    final key = await VaultKeyHierarchy(mvk).fileContentKey();
    final out = Uint8List(manifest.totalBytes);
    var offset = 0;
    try {
      for (var i = 0; i < manifest.chunkCount; i++) {
        final plain = await _readChunk(fileId, i, key);
        try {
          final expectedLength = i == manifest.chunkCount - 1
              ? manifest.totalBytes - offset
              : manifest.chunkSize;
          if (plain.length != expectedLength) {
            throw const FormatException('V2 file chunk length mismatch');
          }
          out.setRange(offset, offset + plain.length, plain);
          offset += plain.length;
        } finally {
          plain.fillRange(0, plain.length, 0);
        }
      }
      if (offset != manifest.totalBytes) {
        throw const FormatException('V2 file length mismatch');
      }
      return FileV2Download(manifest: manifest, bytes: out);
    } catch (_) {
      out.fillRange(0, out.length, 0);
      rethrow;
    }
  }

  /// Recheck a staged upload without allocating a second full-file buffer.
  /// This is especially important for large files that are already resident
  /// in the upload queue's source buffer.
  Future<bool> matchesOriginalBytes(String fileId, Uint8List original) async {
    final manifest = await readManifest(fileId);
    if (manifest.totalBytes != original.length) return false;
    final key = await VaultKeyHierarchy(mvk).fileContentKey();
    var offset = 0;
    for (var i = 0; i < manifest.chunkCount; i++) {
      final plain = await _readChunk(fileId, i, key);
      final expected = i == manifest.chunkCount - 1
          ? manifest.totalBytes - offset
          : manifest.chunkSize;
      if (plain.length != expected) {
        throw const FormatException('V2 file chunk length mismatch');
      }
      for (var j = 0; j < expected; j++) {
        if (plain[j] != original[offset + j]) return false;
      }
      offset += expected;
    }
    return offset == original.length;
  }

  Future<Uint8List> _readChunk(String fileId, int index, SecretKey key) async {
    final response = await get(
      '/vault/file-v2/${Uri.encodeComponent(fileId)}/chunk/$index',
    );
    if (response['file_id'] != fileId ||
        response['chunk_index'] != index ||
        response['ciphertext'] is! String) {
      throw const FormatException('Invalid V2 file chunk');
    }
    return aesGcmUnwrap(
      key,
      b64urlDecode(response['ciphertext'] as String),
    );
  }
}

bool _isRetired(Map row) =>
    row['lifecycle_state'] == 'legacy_migration_retired' &&
    row['verification_state'] == 'client_verified';

bool _isReady(Map row) =>
    row['verification_state'] == 'client_verified' &&
    (row['lifecycle_state'] == 'legacy_migration_retired' ||
        row['lifecycle_state'] == 'client_v2_ready');
