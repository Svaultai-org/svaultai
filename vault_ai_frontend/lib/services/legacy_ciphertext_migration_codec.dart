// Local-only rewrapping of legacy PIN-key ciphertext under the active MVK.
// This codec does not call migration routes or retire legacy data. Callers
// must read the staged ciphertext back and verify it before requesting a
// separate, proof-gated retirement.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

final AesGcm _legacyAesGcm = AesGcm.with256bits();

class StagedLegacyItem {
  final int itemId;
  final String itemTypeCiphertext;
  final String serviceCiphertext;
  final String payloadCiphertext;

  const StagedLegacyItem({
    required this.itemId,
    required this.itemTypeCiphertext,
    required this.serviceCiphertext,
    required this.payloadCiphertext,
  });

  Map<String, Object> toStageBody() => <String, Object>{
        'item_id': itemId,
        'item_type_ciphertext': itemTypeCiphertext,
        'service_ciphertext': serviceCiphertext,
        'payload_ciphertext': payloadCiphertext,
      };
}

class StagedLegacyFile {
  final String fileId;
  final int totalBytes;
  final int chunkSize;
  final String manifestCiphertext;
  final List<String> chunkCiphertexts;

  const StagedLegacyFile({
    required this.fileId,
    required this.totalBytes,
    required this.chunkSize,
    required this.manifestCiphertext,
    required this.chunkCiphertexts,
  });

  Map<String, Object> toManifestBody() => <String, Object>{
        'file_id': fileId,
        'crypto_version': 'client_mvk_v2',
        'manifest_ciphertext': manifestCiphertext,
        'total_bytes': totalBytes,
        'chunk_size': chunkSize,
        'chunk_count': chunkCiphertexts.length,
      };

  Map<String, Object> chunkBody(int index) => <String, Object>{
        'file_id': fileId,
        'chunk_index': index,
        'ciphertext': chunkCiphertexts[index],
      };
}

class LegacyCiphertextMigrationCodec {
  final SecretKey legacyKey;
  final SecretKey mvk;

  const LegacyCiphertextMigrationCodec({
    required this.legacyKey,
    required this.mvk,
  });

  Future<StagedLegacyItem> stageItem({
    required int itemId,
    required String itemType,
    required String service,
    required String legacyCiphertext,
  }) async {
    if (itemId <= 0) throw const FormatException('Invalid item ID');
    final legacyRecord = await _legacyItemFields(legacyCiphertext);
    final fields = _visibleLegacyFields(legacyRecord);
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String text) async =>
        b64urlEncode(await aesGcmWrap(key, utf8.encode(text)));
    return StagedLegacyItem(
      itemId: itemId,
      itemTypeCiphertext: await wrap(itemType),
      serviceCiphertext: await wrap(service),
      payloadCiphertext: await wrap(jsonEncode(<String, Object?>{
        'fields': fields,
        if (legacyRecord['notes'] is String) 'notes': legacyRecord['notes'],
        if (legacyRecord['draft_id'] is String)
          'draft_id': legacyRecord['draft_id'],
        // Preserve the complete old shape under MVK for exact readback and
        // future schema handling. Only `fields` is shown in the current UI.
        'legacy_record': legacyRecord,
      })),
    );
  }

  /// Compare the server's readback with the still-present legacy record.
  /// Returns false on any mismatch or malformed ciphertext. Never includes
  /// plaintext or ciphertext in an error message.
  Future<bool> verifyStagedItem({
    required String itemType,
    required String service,
    required String legacyCiphertext,
    required String itemTypeCiphertext,
    required String serviceCiphertext,
    required String payloadCiphertext,
  }) async {
    try {
      final legacyRecord = await _legacyItemFields(legacyCiphertext);
      final fields = _visibleLegacyFields(legacyRecord);
      final key = await VaultKeyHierarchy(mvk).metadataKey();
      Future<String> unwrap(String encoded) async => utf8.decode(
            await aesGcmUnwrap(key, b64urlDecode(encoded)),
          );
      if (await unwrap(itemTypeCiphertext) != itemType ||
          await unwrap(serviceCiphertext) != service) {
        return false;
      }
      final payload = jsonDecode(await unwrap(payloadCiphertext));
      if (payload is! Map || payload['fields'] is! Map) return false;
      return _sameJson(fields, payload['fields']) &&
          _sameJson(legacyRecord, payload['legacy_record']);
    } catch (_) {
      return false;
    }
  }

  Future<StagedLegacyFile> stageFile({
    required String fileId,
    required String legacyCiphertext,
    required int declaredFileSize,
    required String? contentType,
    required Map<String, String?> encryptedMetadata,
    int chunkSize = 256 * 1024,
  }) async {
    if (fileId.isEmpty || chunkSize <= 0) {
      throw const FormatException('Invalid file migration shape');
    }
    final plain = await _legacyBytes(legacyCiphertext);
    if (plain.length != declaredFileSize) {
      throw const FormatException('Legacy file size mismatch');
    }
    final hierarchy = VaultKeyHierarchy(mvk);
    final contentKey = await hierarchy.fileContentKey();
    final metadataKey = await hierarchy.metadataKey();
    for (final encoded in encryptedMetadata.values) {
      if (encoded == null) continue;
      try {
        utf8.decode(await aesGcmUnwrap(metadataKey, b64urlDecode(encoded)));
      } catch (_) {
        throw const FormatException('Legacy file metadata cannot be read');
      }
    }
    final chunks = <String>[];
    for (var offset = 0; offset < plain.length; offset += chunkSize) {
      final end =
          offset + chunkSize < plain.length ? offset + chunkSize : plain.length;
      chunks.add(b64urlEncode(await aesGcmWrap(
        contentKey,
        plain.sublist(offset, end),
      )));
    }
    final manifest = <String, Object?>{
      'schema': 'vaultai.file.migrated.v1',
      'file_id': fileId,
      'file_size': plain.length,
      'content_type': contentType,
      'chunk_size': chunkSize,
      'chunk_count': chunks.length,
      'encrypted_metadata': encryptedMetadata,
    };
    return StagedLegacyFile(
      fileId: fileId,
      totalBytes: plain.length,
      chunkSize: chunkSize,
      manifestCiphertext: b64urlEncode(
        await aesGcmWrap(metadataKey, utf8.encode(jsonEncode(manifest))),
      ),
      chunkCiphertexts: List<String>.unmodifiable(chunks),
    );
  }

  /// Readback verification must use the bytes fetched from file-v2, never
  /// the locally prepared upload buffers. It compares the decrypted file
  /// byte-for-byte with the legacy ciphertext that is still on the server.
  Future<bool> verifyStagedFileManifest({
    required String fileId,
    required int declaredFileSize,
    required String? contentType,
    required Map<String, String?> encryptedMetadata,
    required int chunkSize,
    required int chunkCount,
    required String manifestCiphertext,
  }) async {
    try {
      if (chunkSize <= 0 || chunkCount < 0 || declaredFileSize < 0) {
        return false;
      }
      final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
      final manifest = jsonDecode(utf8.decode(await aesGcmUnwrap(
        metadataKey,
        b64urlDecode(manifestCiphertext),
      )));
      return manifest is Map &&
          manifest['schema'] == 'vaultai.file.migrated.v1' &&
          manifest['file_id'] == fileId &&
          manifest['file_size'] == declaredFileSize &&
          manifest['content_type'] == contentType &&
          manifest['chunk_size'] == chunkSize &&
          manifest['chunk_count'] == chunkCount &&
          await _sameEncryptedMetadata(
            manifest['encrypted_metadata'], encryptedMetadata, metadataKey,
          );
    } catch (_) {
      return false;
    }
  }

  Future<bool> _sameEncryptedMetadata(
    Object? staged,
    Map<String, String?> expected,
    SecretKey key,
  ) async {
    if (staged is! Map || staged.length != expected.length) return false;
    for (final entry in expected.entries) {
      if (!staged.containsKey(entry.key)) return false;
      final oldValue = staged[entry.key];
      final newValue = entry.value;
      if (oldValue == null && newValue == null) continue;
      if (oldValue is! String || newValue is! String) return false;
      final oldPlain = utf8.decode(await aesGcmUnwrap(key, b64urlDecode(oldValue)));
      final newPlain = utf8.decode(await aesGcmUnwrap(key, b64urlDecode(newValue)));
      if (oldPlain != newPlain) return false;
    }
    return true;
  }

  Future<bool> verifyStagedFile({
    required String fileId,
    required String legacyCiphertext,
    required int declaredFileSize,
    required String? contentType,
    required Map<String, String?> encryptedMetadata,
    required int chunkSize,
    required int chunkCount,
    required String manifestCiphertext,
    required List<String> chunkCiphertexts,
  }) async {
    try {
      final plain = await _legacyBytes(legacyCiphertext);
      if (plain.length != declaredFileSize ||
          chunkSize <= 0 ||
          chunkCount != chunkCiphertexts.length) {
        return false;
      }
      if (!await verifyStagedFileManifest(
        fileId: fileId,
        declaredFileSize: declaredFileSize,
        contentType: contentType,
        encryptedMetadata: encryptedMetadata,
        chunkSize: chunkSize,
        chunkCount: chunkCount,
        manifestCiphertext: manifestCiphertext,
      )) {
        return false;
      }
      final hierarchy = VaultKeyHierarchy(mvk);
      final contentKey = await hierarchy.fileContentKey();
      final verified = BytesBuilder(copy: false);
      for (final encoded in chunkCiphertexts) {
        verified.add(await aesGcmUnwrap(contentKey, b64urlDecode(encoded)));
      }
      return _sameBytes(plain, verified.toBytes());
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>> _legacyItemFields(String encoded) async {
    final decoded = jsonDecode(utf8.decode(await _legacyBytes(encoded)));
    if (decoded is! Map) {
      throw const FormatException('Invalid legacy item payload');
    }
    return Map<String, dynamic>.from(decoded);
  }

  /// Read one exported legacy item on the client. The caller must obtain the
  /// ciphertext through a recent, session-bound OPAQUE export grant.
  Future<Map<String, dynamic>> decodeLegacyItem(String encoded) =>
      _legacyItemFields(encoded);

  Map<String, dynamic> _visibleLegacyFields(Map<String, dynamic> record) {
    const markers = <String>{'category', 'title', 'fields', 'item_id'};
    if (!markers.any(record.containsKey)) return record;
    final inner = record['fields'];
    if (inner is! Map) {
      throw const FormatException('Invalid legacy saved-item fields');
    }
    return Map<String, dynamic>.from(inner);
  }

  Future<Uint8List> _legacyBytes(String encoded) async {
    final combined = base64.decode(encoded);
    if (combined.length < 28) {
      throw const FormatException('Invalid legacy ciphertext');
    }
    final box = SecretBox(
      combined.sublist(12, combined.length - 16),
      nonce: combined.sublist(0, 12),
      mac: Mac(combined.sublist(combined.length - 16)),
    );
    return Uint8List.fromList(await _legacyAesGcm.decrypt(
      box,
      secretKey: legacyKey,
    ));
  }
}

bool _sameBytes(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  var difference = 0;
  for (var i = 0; i < a.length; i++) {
    difference |= a[i] ^ b[i];
  }
  return difference == 0;
}

bool _sameJson(Object? a, Object? b) {
  if (a is Map && b is Map) {
    if (a.length != b.length) return false;
    for (final key in a.keys) {
      if (!b.containsKey(key) || !_sameJson(a[key], b[key])) return false;
    }
    return true;
  }
  if (a is List && b is List) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!_sameJson(a[i], b[i])) return false;
    }
    return true;
  }
  return a == b;
}
