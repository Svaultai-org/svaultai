// Read client-MVK-v2 file manifests and chunks without a PIN or server-side
// decrypt. The caller supplies an authenticated GET transport; this service
// validates the encrypted manifest and every chunk before returning bytes.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

typedef FileV2Get = Future<Map<String, dynamic>> Function(String path);

class FileV2ReadException implements Exception {
  final int statusCode;

  const FileV2ReadException(this.statusCode);

  @override
  String toString() => 'V2 file request failed ($statusCode)';
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
  final bool retired;
  final bool readyForUse;

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
    required this.retired,
    required this.readyForUse,
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
  static const int maxDownloadBytes = 64 * 1024 * 1024;

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
      result.add(await readManifest(
        row['file_id'] as String,
        requireRetired: retiredOnly,
        requireReady: readyOnly,
      ));
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
    final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
    final plaintext = await aesGcmUnwrap(
      metadataKey,
      b64urlDecode(response['manifest_ciphertext'] as String),
    );
    final decoded = jsonDecode(utf8.decode(plaintext));
    if (decoded is! Map ||
        decoded['schema'] != 'vaultai.file.migrated.v1' ||
        decoded['file_id'] != fileId ||
        decoded['file_size'] != total ||
        decoded['chunk_size'] != chunkSize ||
        decoded['chunk_count'] != chunkCount) {
      throw const FormatException('V2 file manifest mismatch');
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

    final typeFromMetadata = await unwrapMetadata('content_type_ciphertext');
    final contentType = typeFromMetadata ?? decoded['content_type'];
    if (contentType != null && contentType is! String) {
      throw const FormatException('Invalid file content type');
    }
    return FileV2Manifest(
      fileId: fileId,
      totalBytes: total,
      chunkSize: chunkSize,
      chunkCount: chunkCount,
      fileName: await unwrapMetadata('file_name_ciphertext'),
      savedName: await unwrapMetadata('saved_name_ciphertext'),
      contentType: contentType as String?,
      assetType: await unwrapMetadata('asset_type_ciphertext'),
      detectedType: await unwrapMetadata('detected_type_ciphertext'),
      detectedService: await unwrapMetadata('detected_service_ciphertext'),
      retired: retired,
      readyForUse: ready,
    );
  }

  Future<FileV2Download> download(
    String fileId, {
    bool requireRetired = false,
    bool requireReady = false,
  }) async {
    final manifest = await readManifest(
      fileId,
      requireRetired: requireRetired,
      requireReady: requireReady,
    );
    final key = await VaultKeyHierarchy(mvk).fileContentKey();
    final out = Uint8List(manifest.totalBytes);
    var offset = 0;
    for (var i = 0; i < manifest.chunkCount; i++) {
      final response = await get(
        '/vault/file-v2/${Uri.encodeComponent(fileId)}/chunk/$i',
      );
      if (response['file_id'] != fileId ||
          response['chunk_index'] != i ||
          response['ciphertext'] is! String) {
        throw const FormatException('Invalid V2 file chunk');
      }
      final plain = await aesGcmUnwrap(
        key,
        b64urlDecode(response['ciphertext'] as String),
      );
      final expectedLength = i == manifest.chunkCount - 1
          ? manifest.totalBytes - offset
          : manifest.chunkSize;
      if (plain.length != expectedLength) {
        throw const FormatException('V2 file chunk length mismatch');
      }
      out.setRange(offset, offset + plain.length, plain);
      offset += plain.length;
    }
    if (offset != manifest.totalBytes) {
      throw const FormatException('V2 file length mismatch');
    }
    return FileV2Download(manifest: manifest, bytes: out);
  }
}

bool _isRetired(Map row) =>
    row['lifecycle_state'] == 'legacy_migration_retired' &&
    row['verification_state'] == 'client_verified';

bool _isReady(Map row) =>
    row['verification_state'] == 'client_verified' &&
    (row['lifecycle_state'] == 'legacy_migration_retired' ||
        row['lifecycle_state'] == 'client_v2_ready');
