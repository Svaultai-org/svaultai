// Opt-in, stage-and-readback-only migration of legacy ciphertext. This
// deliberately has no retirement request: until all V2 readers are live,
// legacy ciphertext must remain available to existing app versions.

import 'dart:convert';

import 'package:cryptography/cryptography.dart'
    show SecretBoxAuthenticationError;

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

typedef MigrationRequest =
    Future<MigrationReply> Function(
      String method,
      String path, [
      Map<String, dynamic>? body,
    ]);

/// Closed-set phase markers for temporary, content-free migration diagnosis.
enum LegacyStagePhase {
  itemsComplete,
  filesListed,
  fileSourceRead,
  filePrepared,
}

class LegacyStageResult {
  final int itemsVerified;
  final int filesVerified;
  final int itemsDeferredForSize;
  final int filesDeferredForSize;
  final int filesDeferredForUnreadableSource;
  final int filesDeferredForExtraLegacyData;

  const LegacyStageResult({
    required this.itemsVerified,
    required this.filesVerified,
    this.itemsDeferredForSize = 0,
    this.filesDeferredForSize = 0,
    this.filesDeferredForUnreadableSource = 0,
    this.filesDeferredForExtraLegacyData = 0,
  });
}

class LegacyContentMigrationStager {
  // The current codec holds old ciphertext, plaintext, prepared V2 chunks,
  // and fetched readback chunks at once. Keep automatic unlock-time work
  // below a conservative per-record memory budget until it streams.
  static const int maxAutomaticCiphertextChars = 8 * 1024 * 1024;
  // Only independent V2 status/chunk requests run together. Export grant
  // pages, proof operations, and whole-file verification remain sequential.
  static const int maxConcurrentV2Requests = 2;

  final bool enabled;
  final bool recoveryEnabled;
  final bool prioritizeUnstagedFiles;
  final bool extraFileMetadataEnabled;
  final LegacyCiphertextExportClient export;
  final LegacyCiphertextMigrationCodec codec;
  final MigrationRequest request;
  final void Function(LegacyStagePhase)? onPhase;

  const LegacyContentMigrationStager({
    this.enabled = false,
    this.recoveryEnabled = false,
    this.prioritizeUnstagedFiles = false,
    this.extraFileMetadataEnabled = false,
    required this.export,
    required this.codec,
    required this.request,
    this.onPhase,
  });

  Future<LegacyStageResult> stageAndVerify() async {
    if (!enabled) {
      return const LegacyStageResult(itemsVerified: 0, filesVerified: 0);
    }
    var itemsVerified = 0;
    var filesVerified = 0;
    var itemsDeferredForSize = 0;
    var filesDeferredForSize = 0;
    var filesDeferredForUnreadableSource = 0;
    var filesDeferredForExtraLegacyData = 0;
    try {
      final items = await export.listItems();
      for (final item in items) {
        if (item['ciphertext_chars'] is int &&
            (item['ciphertext_chars'] as int) > maxAutomaticCiphertextChars) {
          itemsDeferredForSize++;
          continue;
        }
        if (await _stageItem(item)) itemsVerified++;
      }
      onPhase?.call(LegacyStagePhase.itemsComplete);
      final files = await export.listFiles();
      onPhase?.call(LegacyStagePhase.filesListed);
      final eligibleFiles = <Map<String, dynamic>>[];
      for (final file in files) {
        if (extraFileMetadataEnabled) {
          final textBytes = file['extra_text_bytes'];
          final pathBytes = file['extra_path_bytes'];
          if (textBytes is! int || textBytes < 0 ||
              pathBytes is! int || pathBytes < 0) {
            throw const FormatException('Legacy file extra size unavailable');
          }
          if (textBytes > 64 * 1024 || pathBytes > 4096) {
            filesDeferredForSize++;
            continue;
          }
        }
        if (file['ciphertext_chars'] is int &&
            (file['ciphertext_chars'] as int) > maxAutomaticCiphertextChars) {
          filesDeferredForSize++;
          continue;
        }
        eligibleFiles.add(file);
      }
      // A short owner PIN lease must not repeatedly spend its whole budget
      // rechecking the same early sidecars while later files remain unstaged.
      // This status-only preflight never counts a sidecar as verified: both
      // groups still undergo the full source and V2 readback checks below.
      final orderedFiles = prioritizeUnstagedFiles
          ? await _unstagedFilesFirst(eligibleFiles)
          : eligibleFiles;
      for (final file in orderedFiles) {
        try {
          await _stageFile(file);
          filesVerified++;
        } on _UnreadableLegacyFileSource {
          // A historical file can be malformed or encrypted under a key that
          // no longer opens it. Keep the old row intact and try later files.
          // Export, session, network, quota, and V2 conflicts still abort.
          filesDeferredForUnreadableSource++;
        } on _ExtraLegacyFileData {
          // The V2 sidecar cannot represent all legacy file metadata yet.
          // Preserve the original and any unverified sidecar; continue safely.
          filesDeferredForExtraLegacyData++;
        }
      }
      return LegacyStageResult(
        itemsVerified: itemsVerified,
        filesVerified: filesVerified,
        itemsDeferredForSize: itemsDeferredForSize,
        filesDeferredForSize: filesDeferredForSize,
        filesDeferredForUnreadableSource: filesDeferredForUnreadableSource,
        filesDeferredForExtraLegacyData: filesDeferredForExtraLegacyData,
      );
    } finally {
      export.clearGrant();
    }
  }

  Future<List<Map<String, dynamic>>> _unstagedFilesFirst(
      List<Map<String, dynamic>> files) async {
    final unstaged = <Map<String, dynamic>>[];
    final existing = <Map<String, dynamic>>[];
    for (final file in files) {
      final id = file['file_id'];
      final chars = file['ciphertext_chars'];
      if (id is! String || id.isEmpty || id.length > 128 ||
          chars is! int || chars <= 0) {
        throw const FormatException('Invalid legacy file listing');
      }
    }
    final hasManifest = await _boundedV2Requests<bool>(
      files.length,
      (index) async {
        final id = files[index]['file_id'] as String;
        final response = await request(
          'GET', '/vault/file-v2/${Uri.encodeComponent(id)}/manifest',
        );
        if (response.statusCode == 404 &&
            _detailCode(response) == 'file_v2_not_found') {
          return false;
        }
        _require200(response);
        _requireMap(response);
        return true;
      },
    );
    for (var index = 0; index < files.length; index++) {
      (hasManifest[index] ? existing : unstaged).add(files[index]);
    }
    return <Map<String, dynamic>>[...unstaged, ...existing];
  }

  Future<List<T>> _boundedV2Requests<T>(
    int count,
    Future<T> Function(int index) task,
  ) async {
    final results = <T>[];
    for (var start = 0; start < count; start += maxConcurrentV2Requests) {
      final end = start + maxConcurrentV2Requests < count
          ? start + maxConcurrentV2Requests
          : count;
      results.addAll(await Future.wait<T>(
        <Future<T>>[
          for (var index = start; index < end; index++) task(index),
        ],
        // A failed V2 write must not start a recovery reset while the paired
        // idempotent request is still in flight.
        eagerError: false,
      ));
    }
    return results;
  }

  Future<bool> _stageItem(Map<String, dynamic> record) async {
    try {
      return await _stageItemOnce(record);
    } on _StageConflict {
      if (!recoveryEnabled) rethrow;
      final id = record['item_id'];
      if (id is! int || id <= 0) rethrow;
      await _resetItemStageAfterFreshExport(id);
      return _stageItemOnce(await _freshItemRecord(id));
    }
  }

  Future<bool> _stageItemOnce(Map<String, dynamic> record) async {
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
      metadata['item_type'],
      metadata['item_type_ciphertext'],
    );
    // Wallet-engine accounts have a dedicated migration and reader contract.
    // Generic saved-item V2 staging would obstruct that cutover.
    if (itemType == 'crypto_wallet_account') return false;
    final service = await _itemLabel(
      metadata['service'],
      metadata['service_ciphertext'],
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
      if (response.statusCode == 409 &&
          _detailCode(response) == 'staged_item_conflict') {
        throw const _StageConflict();
      }
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
        body['payload_ciphertext'] is! String) {
      throw const FormatException('Invalid staged item readback');
    }
    if (!await codec.verifyStagedItem(
      itemType: itemType,
      service: service,
      legacyCiphertext: legacy,
      itemTypeCiphertext: body['item_type_ciphertext'] as String,
      serviceCiphertext: body['service_ciphertext'] as String,
      payloadCiphertext: body['payload_ciphertext'] as String,
    )) {
      throw const _StageConflict();
    }
    return true;
  }

  Future<Map<String, dynamic>> _freshItemRecord(int itemId) async {
    export.clearGrant();
    final matches = (await export.listItems())
        .where((record) => record['item_id'] == itemId)
        .toList();
    if (matches.length != 1 || matches.single['ciphertext_chars'] is! int) {
      throw const FormatException('Legacy item is unavailable for recovery');
    }
    return matches.single;
  }

  Future<void> _resetItemStageAfterFreshExport(int itemId) async {
    final record = await _freshItemRecord(itemId);
    final source = await export.readItemSource(
      itemId: itemId,
      ciphertextChars: record['ciphertext_chars'] as int,
    );
    final proof = await export.proofProvider();
    if (proof.isEmpty) throw StateError('PIN proof is unavailable');
    final response = await request(
      'POST',
      '/vault/legacy-ciphertext/migrate/item-reset-stage',
      <String, dynamic>{
        'item_id': itemId,
        'source_snapshot': source.sourceSnapshot,
        'zk_proof_token': proof,
      },
    );
    _require200(response);
    final body = _requireMap(response);
    if (body['item_id'] != itemId || body['stage_reset'] != true) {
      throw const FormatException('Invalid item stage reset acknowledgement');
    }
    export.clearGrant();
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
    try {
      await _stageFileOnce(record);
    } on _StageConflict {
      if (!recoveryEnabled) rethrow;
      final id = record['file_id'];
      if (id is! String || id.isEmpty) rethrow;
      await _resetFileStageAfterFreshExport(id);
      try {
        await _stageFileOnce(await _freshFileRecord(id));
      } on _UnreadableLegacyFileSource {
        // The recovery reset may already have changed a V2 sidecar. Abort
        // rather than counting this as a harmless pre-write deferral.
        throw StateError('Legacy file became unreadable after stage reset');
      }
    }
  }

  Future<Map<String, dynamic>> _freshFileRecord(String fileId) async {
    export.clearGrant();
    final matches = (await export.listFiles())
        .where((record) => record['file_id'] == fileId)
        .toList();
    if (matches.length != 1 || matches.single['ciphertext_chars'] is! int) {
      throw const FormatException('Legacy file is unavailable for recovery');
    }
    return matches.single;
  }

  Future<void> _resetFileStageAfterFreshExport(String fileId) async {
    final record = await _freshFileRecord(fileId);
    final source = await export.readFileSource(
      fileId: fileId,
      ciphertextChars: record['ciphertext_chars'] as int,
    );
    final proof = await export.proofProvider();
    if (proof.isEmpty) throw StateError('PIN proof is unavailable');
    final response = await request(
      'POST',
      '/vault/legacy-ciphertext/migrate/file-reset-stage',
      <String, dynamic>{
        'file_id': fileId,
        'source_snapshot': source.sourceSnapshot,
        'zk_proof_token': proof,
      },
    );
    _require200(response);
    final body = _requireMap(response);
    if (body['file_id'] != fileId || body['stage_reset'] != true) {
      throw const FormatException('Invalid file stage reset acknowledgement');
    }
    export.clearGrant();
  }

  Future<void> _stageFileOnce(Map<String, dynamic> record) async {
    final id = record['file_id'];
    final chars = record['ciphertext_chars'];
    if (id is! String || id.isEmpty || chars is! int) {
      throw const FormatException('Invalid legacy file listing');
    }
    final source = await export.readFileSource(
      fileId: id,
      ciphertextChars: chars,
    );
    onPhase?.call(LegacyStagePhase.fileSourceRead);
    final metadata = source.sourceMetadata;
    final size = metadata['file_size'];
    final contentType = metadata['content_type'];
    if (size is! int ||
        size < 0 ||
        (contentType != null && contentType is! String)) {
      throw const _UnreadableLegacyFileSource();
    }
    Map<String, String?>? legacyExtra;
    if (extraFileMetadataEnabled) {
      final hasExtra = metadata['has_legacy_extra_data'];
      if (hasExtra is! bool) {
        throw const FormatException('Legacy file extra contract unavailable');
      }
      if (hasExtra) {
        legacyExtra = await export.readFileExtras(
          fileId: id,
          sourceSnapshot: source.sourceSnapshot,
        );
        if (legacyExtra.values.every((value) => value == null)) {
          throw const FormatException('Legacy file extra source changed');
        }
      }
    }
    late final Map<String, String?> encryptedMetadata;
    try {
      encryptedMetadata = await _fileEncryptedMetadata(metadata);
    } on FormatException {
      throw const _UnreadableLegacyFileSource();
    }
    if (encryptedMetadata['file_name_ciphertext'] == null &&
        encryptedMetadata['saved_name_ciphertext'] == null) {
      throw const _UnreadableLegacyFileSource();
    }
    final legacy = source.ciphertext;
    late final StagedLegacyFile prepared;
    try {
      prepared = await codec.stageFile(
        fileId: id,
        legacyCiphertext: legacy,
        declaredFileSize: size,
        contentType: contentType as String?,
        encryptedMetadata: encryptedMetadata,
        legacyExtra: legacyExtra,
      );
    } on FormatException {
      throw const _UnreadableLegacyFileSource();
    } on SecretBoxAuthenticationError {
      throw const _UnreadableLegacyFileSource();
    }
    onPhase?.call(LegacyStagePhase.filePrepared);
    final encodedId = Uri.encodeComponent(id);
    final stagePath = '/vault/legacy-ciphertext/migrate/file-staged/$encodedId';
    var staged = await request('GET', stagePath);
    if (_hasExtraLegacyFileData(staged)) {
      if (legacyExtra != null) throw const _StageConflict();
      throw const _ExtraLegacyFileData();
    }
    if (staged.statusCode == 409 &&
        <String>{
          'file_v2_not_staged',
          'file_v2_chunks_incomplete',
        }.contains(_detailCode(staged))) {
      final manifestPath = '/vault/file-v2/$encodedId/manifest';
      final manifest = await request('GET', manifestPath);
      var manifestWasAbsent = false;
      if (manifest.statusCode == 404 &&
          _detailCode(manifest) == 'file_v2_not_found') {
        manifestWasAbsent = true;
        final ack =
            await request('POST', '/vault/file-v2/manifest', <String, dynamic>{
              ...prepared.toManifestBody(),
              'migrating_legacy': true,
              'source_snapshot': source.sourceSnapshot,
            });
        if (ack.statusCode == 409 &&
            _detailCode(ack) == 'file_v2_manifest_conflict') {
          throw const _StageConflict();
        }
        _require200(ack);
      } else {
        _require200(manifest);
        final body = _requireMap(manifest);
        if (body['file_id'] != id ||
            body['total_bytes'] is! int ||
            body['chunk_size'] is! int ||
            body['chunk_count'] is! int ||
            body['manifest_ciphertext'] is! String ||
            (body['migration_metadata_version'] ?? 1) !=
                prepared.migrationMetadataVersion) {
          throw const FormatException('Invalid existing file manifest');
        }
        if (body['total_bytes'] != size ||
            body['chunk_size'] != prepared.chunkSize ||
            body['chunk_count'] != prepared.chunkCiphertexts.length ||
            !await codec.verifyStagedFileManifest(
              fileId: id,
              declaredFileSize: size,
              contentType: contentType,
              encryptedMetadata: encryptedMetadata,
              legacyExtra: legacyExtra,
              chunkSize: prepared.chunkSize,
              chunkCount: prepared.chunkCiphertexts.length,
              manifestCiphertext: body['manifest_ciphertext'] as String,
            )) {
          throw const _StageConflict();
        }
      }
      await _boundedV2Requests<bool>(
        prepared.chunkCiphertexts.length,
        (i) async {
          if (manifestWasAbsent) {
            // The manifest was missing before this pass. PUT is idempotent
            // and the server compares exact ciphertext on conflict, so a
            // speculative GET adds a round trip without improving safety.
            // The full GET/readback pass below still verifies every byte.
            final ack = await request(
              'PUT',
              '/vault/file-v2/chunk',
              Map<String, dynamic>.from(prepared.chunkBody(i)),
            );
            _require200(ack);
          } else {
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
          return true;
        },
      );
      staged = await request('GET', stagePath);
    }
    if (_hasExtraLegacyFileData(staged)) {
      if (legacyExtra != null) throw const _StageConflict();
      throw const _ExtraLegacyFileData();
    }
    _require200(staged);
    final readback = _requireMap(staged);
    if (readback['file_id'] != id ||
        readback['source_snapshot'] != source.sourceSnapshot ||
        readback['total_bytes'] is! int ||
        readback['chunk_count'] is! int ||
        readback['manifest_ciphertext'] is! String ||
        (readback['migration_metadata_version'] ?? 1) !=
            prepared.migrationMetadataVersion) {
      throw const FormatException('Invalid staged file readback');
    }
    if (readback['total_bytes'] != size ||
        readback['chunk_count'] != prepared.chunkCiphertexts.length) {
      throw const _StageConflict();
    }
    final chunks = await _boundedV2Requests<String>(
      prepared.chunkCiphertexts.length,
      (i) async {
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
        return chunk['ciphertext'] as String;
      },
    );
    if (!await codec.verifyStagedFile(
      fileId: id,
      legacyCiphertext: legacy,
      declaredFileSize: size,
      contentType: contentType,
      encryptedMetadata: encryptedMetadata,
      legacyExtra: legacyExtra,
      chunkSize: prepared.chunkSize,
      chunkCount: prepared.chunkCiphertexts.length,
      manifestCiphertext: readback['manifest_ciphertext'] as String,
      chunkCiphertexts: chunks,
    )) {
      throw const _StageConflict();
    }
    final finalSource = await request('GET', stagePath);
    if (_hasExtraLegacyFileData(finalSource)) {
      if (legacyExtra != null) throw const _StageConflict();
      throw const _ExtraLegacyFileData();
    }
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
      // Old clients can rename or classify a file by changing the plaintext
      // columns while leaving older encrypted labels in place. The export
      // snapshot binds this latest source row; re-encrypt every nonempty
      // plaintext label from it rather than carrying stale ciphertext into V2.
      final usePlain = plain is String && plain.isNotEmpty;
      result[entry.key] = usePlain
          ? b64urlEncode(await aesGcmWrap(key, utf8.encode(plain)))
          : encrypted is String && encrypted.isNotEmpty
          ? encrypted
          : null;
    }
    return result;
  }
}

/// Only an exact, well-formed stale V2 sidecar may enter one owner-approved
/// reset attempt. Missing source data and unexpected responses fail closed.
class _StageConflict implements Exception {
  const _StageConflict();
}

class _ExtraLegacyFileData implements Exception {
  const _ExtraLegacyFileData();
}

bool _hasExtraLegacyFileData(MigrationReply reply) =>
    reply.statusCode == 409 &&
    _detailCode(reply) == 'file_extra_legacy_data_requires_migration';

/// Only pre-write, deterministic local source failures may be deferred. This
/// marker carries no record identifier, ciphertext, plaintext, or error body.
class _UnreadableLegacyFileSource implements Exception {
  const _UnreadableLegacyFileSource();
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
  if (reply.statusCode == 409 &&
      _detailCode(reply) == 'legacy_source_changed') {
    throw StateError(
      'Legacy source changed. Restart migration to use the latest record.',
    );
  }
  if (reply.statusCode != 200) {
    // Never attach server response bodies, ciphertext, or identifiers.
    throw StateError('Migration endpoint unavailable (${reply.statusCode})');
  }
}
