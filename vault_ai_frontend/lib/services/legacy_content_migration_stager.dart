// Opt-in, stage-and-readback-only migration of legacy ciphertext. This
// deliberately has no retirement request: until all V2 readers are live,
// legacy ciphertext must remain available to existing app versions.

import 'dart:convert';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';
import 'vault_key_hierarchy.dart';

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
    final itemType = await _itemLabel(
      record['item_type'],
      record['item_type_ciphertext'],
    );
    final service = await _itemLabel(
      record['service'],
      record['service_ciphertext'],
    );
    final legacy = await export.readItemCiphertext(
      itemId: id,
      ciphertextChars: chars,
    );
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
        Map<String, dynamic>.from(staged.toStageBody()),
      );
      _require200(response);
      if ((response.data as Map?)?['item_id'] != id ||
          (response.data as Map?)?['staged'] != true) {
        throw const FormatException('Invalid item stage acknowledgement');
      }
      readback = await request('GET', readPath);
    }
    _require200(readback);
    final body = _requireMap(readback);
    if (body['item_id'] != id ||
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
    final size = record['file_size'];
    final contentType = record['content_type'];
    if (id is! String ||
        id.isEmpty ||
        chars is! int ||
        size is! int ||
        size < 0 ||
        (contentType != null && contentType is! String)) {
      throw const FormatException('Invalid legacy file listing');
    }
    const metadataFields = <String>[
      'file_name_ciphertext',
      'saved_name_ciphertext',
      'content_type_ciphertext',
      'detected_type_ciphertext',
      'detected_service_ciphertext',
      'asset_type_ciphertext',
    ];
    final encryptedMetadata = <String, String?>{};
    for (final name in metadataFields) {
      final value = record[name];
      if (value != null && value is! String) {
        throw const FormatException('Invalid encrypted file metadata');
      }
      encryptedMetadata[name] = value as String?;
    }
    if (encryptedMetadata['file_name_ciphertext'] == null &&
        encryptedMetadata['saved_name_ciphertext'] == null) {
      throw const FormatException('Legacy file name is unavailable');
    }
    final legacy = await export.readFileCiphertext(
      fileId: id,
      ciphertextChars: chars,
    );
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
  }
}

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
  if (reply.statusCode != 200) {
    // Never attach server response bodies, ciphertext, or identifiers.
    throw StateError('Migration endpoint unavailable (${reply.statusCode})');
  }
}
