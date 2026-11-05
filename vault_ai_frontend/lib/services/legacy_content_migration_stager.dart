// Opt-in, stage-and-readback-only migration of legacy ciphertext. This
// deliberately has no retirement request: until all V2 readers are live,
// legacy ciphertext must remain available to existing app versions.

import 'dart:convert';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';
import 'vault_key_hierarchy.dart';

Map<String, String> legacyContentMigrationHeaders({
  required String sessionToken,
  required String? deviceId,
}) {
  if (sessionToken.isEmpty || deviceId == null || deviceId.isEmpty) {
    throw StateError('Trusted vault session is unavailable for migration');
  }
  return <String, String>{
    'Authorization': 'Bearer $sessionToken',
    'X-Device-Id': deviceId,
    'Content-Type': 'application/json',
  };
}

class MigrationReply {
  final int statusCode;
  final Object? data;

  const MigrationReply(this.statusCode, this.data);
}

typedef MigrationRequest = Future<MigrationReply> Function(
  String method,
  String path, [
  Map<String, dynamic>? body,
]);

class LegacyStageResult {
  final int itemsVerified;
  final int filesVerified;

  const LegacyStageResult({
    required this.itemsVerified,
    required this.filesVerified,
  });
}

class LegacyContentMigrationStager {
  final bool enabled;
  final LegacyCiphertextExportClient export;
  final LegacyCiphertextMigrationCodec codec;
  final MigrationRequest request;

  const LegacyContentMigrationStager({
    this.enabled = false,
    required this.export,
    required this.codec,
    required this.request,
  });

  Future<LegacyStageResult> stageAndVerify() async {
    if (!enabled) {
      return const LegacyStageResult(itemsVerified: 0, filesVerified: 0);
    }
    var itemsVerified = 0;
    var filesVerified = 0;
    try {
      final items = await export.listItems();
      for (final item in items) {
        await _stageItem(item);
        itemsVerified++;
      }
      final files = await export.listFiles();
      for (final file in files) {
        await _stageFile(file);
        filesVerified++;
      }
      return LegacyStageResult(
        itemsVerified: itemsVerified,
        filesVerified: filesVerified,
      );
    } finally {
      export.clearGrant();
    }
  }

  Future<void> _stageItem(Map<String, dynamic> record) async {
    final id = record['item_id'];
    final chars = record['ciphertext_chars'];
    if (id is! int || id <= 0 || chars is! int) {
      throw const FormatException('Invalid legacy item listing');
    }
    final source = await export.readItemSource(
      itemId: id,
      ciphertextChars: chars,
    );
    final metadata = source.sourceMetadata;
    final itemType = await _itemLabel(
      metadata['item_type'], metadata['item_type_ciphertext'],
    );
    final service = await _itemLabel(
      metadata['service'], metadata['service_ciphertext'],
    );
    final legacy = source.ciphertext;
    var expectedSnapshot = source.sourceSnapshot;
    final readPath = '/vault/legacy-ciphertext/migrate/item-staged/$id';
    var readback = await request('GET', readPath);
    if (readback.statusCode == 409 &&
        _detailCode(readback) == 'item_not_staged') {
      final staged = await codec.stageItem(
        itemId: id,
        itemType: itemType,
        service: service,
        legacyCiphertext: legacy,
      );
      final response = await request(
        'POST',
        '/vault/legacy-ciphertext/migrate/item-stage',
        <String, dynamic>{
          ...staged.toStageBody(),
          'source_snapshot': source.sourceSnapshot,
        },
      );
      _require200(response);
      if ((response.data as Map?)?['item_id'] != id ||
          (response.data as Map?)?['staged'] != true ||
          !_validSnapshot((response.data as Map?)?['source_snapshot'])) {
        throw const FormatException('Invalid item stage acknowledgement');
      }
      expectedSnapshot = (response.data as Map)['source_snapshot'] as String;
      readback = await request('GET', readPath);
    }
    _require200(readback);
    final body = _requireMap(readback);
    if (body['item_id'] != id ||
        body['source_snapshot'] != expectedSnapshot ||
        body['item_type_ciphertext'] is! String ||
        body['service_ciphertext'] is! String ||
        body['payload_ciphertext'] is! String ||
        !await codec.verifyStagedItem(
          itemType: itemType,
          service: service,
          legacyCiphertext: legacy,
          itemTypeCiphertext: body['item_type_ciphertext'] as String,
          serviceCiphertext: body['service_ciphertext'] as String,
          payloadCiphertext: body['payload_ciphertext'] as String,
        )) {
      throw const FormatException('Item readback did not match legacy');
    }
  }

  Future<String> _itemLabel(Object? plain, Object? encrypted) async {
    if (plain is String && plain.isNotEmpty) return plain;
    if (encrypted is! String || encrypted.isEmpty) {
      throw const FormatException('Legacy item label is unavailable');
    }
    try {
      final key = await VaultKeyHierarchy(codec.mvk).metadataKey();
      final value = utf8.decode(
        await aesGcmUnwrap(key, b64urlDecode(encrypted)),
      );
      if (value.isEmpty) throw const FormatException('Empty item label');
      return value;
    } catch (_) {
      throw const FormatException('Legacy item label could not be read');
    }
  }

  Future<void> _stageFile(Map<String, dynamic> record) async {
    final id = record['file_id'];
    final chars = record['ciphertext_chars'];
    if (id is! String ||
        id.isEmpty ||
        chars is! int) {
      throw const FormatException('Invalid legacy file listing');
    }
    final source = await export.readFileSource(
      fileId: id,
      ciphertextChars: chars,
    );
    final metadata = source.sourceMetadata;
    final size = metadata['file_size'];
    final contentType = metadata['content_type'];
    if (size is! int || size < 0 ||
        (contentType != null && contentType is! String)) {
      throw const FormatException('Invalid legacy file source metadata');
    }
    final encryptedMetadata = await _fileEncryptedMetadata(metadata);
    if (encryptedMetadata['file_name_ciphertext'] == null &&
        encryptedMetadata['saved_name_ciphertext'] == null) {
      throw const FormatException('Legacy file name is unavailable');
    }
    final legacy = source.ciphertext;
    final prepared = await codec.stageFile(
      fileId: id,
      legacyCiphertext: legacy,
      declaredFileSize: size,
      contentType: contentType as String?,
      encryptedMetadata: encryptedMetadata,
    );
    final encodedId = Uri.encodeComponent(id);
    final stagePath = '/vault/legacy-ciphertext/migrate/file-staged/$encodedId';
    var staged = await request('GET', stagePath);
    if (staged.statusCode == 409 &&
        <String>{'file_v2_not_staged', 'file_v2_chunks_incomplete'}
            .contains(_detailCode(staged))) {
      final manifestPath = '/vault/file-v2/$encodedId/manifest';
      final manifest = await request('GET', manifestPath);
      if (manifest.statusCode == 404 &&
          _detailCode(manifest) == 'file_v2_not_found') {
        final ack = await request(
          'POST',
          '/vault/file-v2/manifest',
          <String, dynamic>{
            ...prepared.toManifestBody(),
            'migrating_legacy': true,
            'source_snapshot': source.sourceSnapshot,
          },
        );
        _require200(ack);
      } else {
        _require200(manifest);
        final body = _requireMap(manifest);
        if (body['file_id'] != id ||
            body['total_bytes'] != size ||
            body['chunk_size'] != prepared.chunkSize ||
            body['chunk_count'] != prepared.chunkCiphertexts.length ||
            body['manifest_ciphertext'] is! String ||
            !await codec.verifyStagedFileManifest(
              fileId: id,
              declaredFileSize: size,
              contentType: contentType,
              encryptedMetadata: encryptedMetadata,
              chunkSize: prepared.chunkSize,
              chunkCount: prepared.chunkCiphertexts.length,
              manifestCiphertext: body['manifest_ciphertext'] as String,
            )) {
          throw const FormatException('Existing file manifest mismatch');
        }
      }
      for (var i = 0; i < prepared.chunkCiphertexts.length; i++) {
        final chunkPath = '/vault/file-v2/$encodedId/chunk/$i';
        final existing = await request('GET', chunkPath);
        if (existing.statusCode == 404 &&
            _detailCode(existing) == 'file_v2_chunk_not_found') {
          final ack = await request(
            'PUT',
            '/vault/file-v2/chunk',
            Map<String, dynamic>.from(prepared.chunkBody(i)),
          );
          _require200(ack);
        } else {
          _require200(existing);
        }
      }
      staged = await request('GET', stagePath);
    }
    _require200(staged);
    final readback = _requireMap(staged);
    if (readback['file_id'] != id ||
        readback['source_snapshot'] != source.sourceSnapshot ||
        readback['total_bytes'] != size ||
        readback['chunk_count'] != prepared.chunkCiphertexts.length ||
        readback['manifest_ciphertext'] is! String) {
      throw const FormatException('Invalid staged file readback');
    }
    final chunks = <String>[];
    for (var i = 0; i < prepared.chunkCiphertexts.length; i++) {
      final response = await request(
        'GET',
        '/vault/file-v2/$encodedId/chunk/$i',
      );
      _require200(response);
      final chunk = _requireMap(response);
      if (chunk['file_id'] != id ||
          chunk['chunk_index'] != i ||
          chunk['ciphertext'] is! String) {
        throw const FormatException('Invalid staged file chunk');
      }
      chunks.add(chunk['ciphertext'] as String);
    }
    if (!await codec.verifyStagedFile(
      fileId: id,
      legacyCiphertext: legacy,
      declaredFileSize: size,
      contentType: contentType,
      encryptedMetadata: encryptedMetadata,
      chunkSize: prepared.chunkSize,
      chunkCount: prepared.chunkCiphertexts.length,
      manifestCiphertext: readback['manifest_ciphertext'] as String,
      chunkCiphertexts: chunks,
    )) {
      throw const FormatException('File readback did not match legacy');
    }
    final finalSource = await request('GET', stagePath);
    _require200(finalSource);
    if (_requireMap(finalSource)['source_snapshot'] != source.sourceSnapshot) {
      throw const FormatException('Legacy file changed during readback');
    }
  }

  Future<Map<String, String?>> _fileEncryptedMetadata(
    Map<String, dynamic> metadata,
  ) async {
    const names = <String, String>{
      'file_name_ciphertext': 'file_name',
      'saved_name_ciphertext': 'saved_name',
      'content_type_ciphertext': 'content_type',
      'detected_type_ciphertext': 'detected_type',
      'detected_service_ciphertext': 'detected_service',
      'asset_type_ciphertext': 'asset_type',
    };
    final key = await VaultKeyHierarchy(codec.mvk).metadataKey();
    final result = <String, String?>{};
    for (final entry in names.entries) {
      final encrypted = metadata[entry.key];
      final plain = metadata[entry.value];
      if ((encrypted != null && encrypted is! String) ||
          (plain != null && plain is! String)) {
        throw const FormatException('Invalid legacy file metadata');
      }
      // An old app can rename saved_name after a listing. Use the plaintext
      // value from the same locked source row over an older ciphertext label.
      final usePlain = plain is String && plain.isNotEmpty &&
          (entry.key == 'saved_name_ciphertext' ||
              encrypted == null || encrypted == '');
      result[entry.key] = usePlain
          ? b64urlEncode(await aesGcmWrap(key, utf8.encode(plain)))
          : encrypted is String && encrypted.isNotEmpty ? encrypted : null;
    }
    return result;
  }
}

bool _validSnapshot(Object? value) =>
    value is String && RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(value);

String? _detailCode(MigrationReply reply) {
  final data = reply.data;
  if (data is! Map) return null;
  final detail = data['detail'];
  if (detail is String) return detail;
  if (detail is Map) return detail['code']?.toString();
  return null;
}

Map<String, dynamic> _requireMap(MigrationReply reply) {
  final data = reply.data;
  if (data is! Map<String, dynamic>) {
    throw const FormatException('Invalid migration response');
  }
  return data;
}

void _require200(MigrationReply reply) {
  if (reply.statusCode == 409 && _detailCode(reply) == 'legacy_source_changed') {
    throw StateError('Legacy source changed. Restart migration to use the latest record.');
  }
  if (reply.statusCode != 200) {
    // Never attach server response bodies, ciphertext, or identifiers.
    throw StateError('Migration endpoint unavailable (${reply.statusCode})');
  }
}
