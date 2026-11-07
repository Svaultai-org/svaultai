// Client-side lazy metadata migration.
//
// After successful vault unlock, the client polls
// /vault/metadata-migration/next-batch, encrypts each row's legacy
// plaintext metadata locally under the appropriate vault-scoped
// subkey, and posts /vault/metadata-migration/apply-batch. The
// server writes the ciphertext columns. Memory source fields stay intact
// until a separate owner-verified cutover; other metadata is cleared.
//
// The loop is:
//   * resumable (state lives in vault_metadata_migration_state)
//   * bounded per unlock (max iterations / max wall-time to avoid
//     starving the UI)
//   * self-limiting (stops when the server returns table="" or when
//     status.completed_at is set)
//   * failure-tolerant (a failed batch does not delete user data;
//     the row simply stays legacy until the next unlock)
//   * memory copies are staged and read back without clearing source;
//     other metadata is NULLed only after ciphertext write succeeds.
//
// File content and wallet material are not rewritten by this loop. Legacy
// memory fields are preserved together in one encrypted JSON payload.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

typedef HttpJsonPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body, {
  String? bearerToken,
});

typedef HttpJsonGet = Future<Map<String, dynamic>> Function(
  String path, {
  String? bearerToken,
});

const memoryMigrationPayloadFormat = 'json_object_v1';

class MigrationRunResult {
  final int batchesApplied;
  final int rowsApplied;
  final int rowsSkipped;
  final bool completed;
  final Object? error;
  MigrationRunResult({
    required this.batchesApplied,
    required this.rowsApplied,
    required this.rowsSkipped,
    required this.completed,
    this.error,
  });
}

class MetadataMigrationClient {
  final SecretKey mvk;
  final String sessionToken;
  final HttpJsonPost post;
  final HttpJsonGet get;
  final int maxBatchesPerRun;

  MetadataMigrationClient({
    required this.mvk,
    required this.sessionToken,
    required this.post,
    required this.get,
    this.maxBatchesPerRun = 20,
  });

  Future<MigrationRunResult> runOnce() async {
    final hierarchy = VaultKeyHierarchy(mvk);
    final metadataKey = await hierarchy.metadataKey();
    final memoryKey = await hierarchy.memoryKey();

    int batchesApplied = 0;
    int rowsApplied = 0;
    int rowsSkipped = 0;

    try {
      for (var i = 0; i < maxBatchesPerRun; i++) {
        final batch = await get(
          '/vault/metadata-migration/next-batch',
          bearerToken: sessionToken,
        ).timeout(const Duration(seconds: 12));

        final table = batch['table']?.toString() ?? '';
        final rows = batch['rows'];
        if (table.isEmpty || rows is! List || rows.isEmpty) {
          final status = await get(
            '/vault/metadata-migration/status',
            bearerToken: sessionToken,
          );
          final completed = (status['completed_at'] != null);
          return MigrationRunResult(
            batchesApplied: batchesApplied,
            rowsApplied: rowsApplied,
            rowsSkipped: rowsSkipped,
            completed: completed,
          );
        }

        final subkey = _pickSubkey(table, metadataKey, memoryKey);
        final ciphertextRows = <Map<String, dynamic>>[];
        final memoryPayloads = <String, String>{};
        if (table == 'vault_ai_memory') {
          // An old server ignores unknown request fields and would clear the
          // source after accepting a malformed payload. Require the paired
          // non-destructive server before sending any memory ciphertext.
          final capabilities = await get(
            '/vault/metadata-migration/memory-capabilities',
            bearerToken: sessionToken,
          ).timeout(const Duration(seconds: 12));
          if (capabilities['memory_payload_format'] !=
                  memoryMigrationPayloadFormat ||
              capabilities['preserves_legacy_source'] != true ||
              capabilities['opaque_readback'] != true) {
            throw StateError('Safe memory migration is unavailable');
          }
        }
        for (final row in rows) {
          if (row is! Map) continue;
          final rowId = row['row_id'];
          final plaintext = row['plaintext'];
          if (rowId == null || plaintext is! Map) continue;

          final ctMap = <String, String>{};
          if (table == 'vault_ai_memory') {
            if (plaintext.isEmpty) continue;
            // Every field, including nulls and future JSON fields, belongs in
            // the same object. Encrypting scalars into the same destination
            // column would overwrite earlier fields before the request.
            final payload = <String, dynamic>{
              for (final entry in plaintext.entries)
                entry.key.toString(): entry.value,
            };
            final expectedJson = jsonEncode(payload);
            final ciphertext = await aesGcmWrap(
                subkey, Uint8List.fromList(utf8.encode(expectedJson)));
            final locallyOpened = utf8.decode(
                await aesGcmUnwrap(subkey, ciphertext));
            if (locallyOpened != expectedJson) {
              throw StateError('Memory aggregate verification failed');
            }
            ctMap['payload_ciphertext'] = b64urlEncode(ciphertext);
            memoryPayloads['$rowId'] = expectedJson;
          } else {
            for (final entry in plaintext.entries) {
              final colName = entry.key.toString();
              final value = entry.value;
              if (value == null) continue;
              final valueStr = value is String ? value : jsonEncode(value);
              final ctColName = _ciphertextColumnFor(table, colName);
              if (ctColName == null) continue;
              final encoded = await aesGcmWrap(subkey, utf8.encode(valueStr));
              ctMap[ctColName] = b64urlEncode(encoded);
            }
          }

          if (ctMap.isEmpty) continue;
          ciphertextRows.add({
            'row_id': rowId,
            'ciphertext': ctMap,
          });
        }

        if (ciphertextRows.isEmpty) {
          rowsSkipped += rows.length;
          continue;
        }

        final applyResp = await post(
          '/vault/metadata-migration/apply-batch',
          {
            'table': table,
            if (table == 'vault_ai_memory')
              'memory_payload_format': memoryMigrationPayloadFormat,
            'rows': ciphertextRows,
          },
          bearerToken: sessionToken,
        ).timeout(const Duration(seconds: 20));

        final applied = (applyResp['applied'] as int?) ?? 0;
        final skipped = (applyResp['skipped'] as int?) ?? 0;
        if (table == 'vault_ai_memory') {
          for (final row in ciphertextRows) {
            final rowId = '${row['row_id']}';
            final readback = await get(
              '/vault/metadata-migration/memory-readback/'
              '${Uri.encodeComponent(rowId)}',
              bearerToken: sessionToken,
            ).timeout(const Duration(seconds: 12));
            final ciphertext = readback['payload_ciphertext'];
            if (ciphertext is! String ||
                ciphertext !=
                    (row['ciphertext'] as Map)['payload_ciphertext']) {
              throw StateError('Memory readback does not match staged copy');
            }
            final opened = utf8.decode(await aesGcmUnwrap(
                memoryKey, b64urlDecode(ciphertext)));
            if (opened != memoryPayloads[rowId]) {
              throw StateError('Memory readback content does not match source');
            }
          }
        }
        batchesApplied += 1;
        rowsApplied += applied;
        rowsSkipped += skipped;
      }

      return MigrationRunResult(
        batchesApplied: batchesApplied,
        rowsApplied: rowsApplied,
        rowsSkipped: rowsSkipped,
        completed: false,
      );
    } catch (err) {
      return MigrationRunResult(
        batchesApplied: batchesApplied,
        rowsApplied: rowsApplied,
        rowsSkipped: rowsSkipped,
        completed: false,
        error: err,
      );
    }
  }

  SecretKey _pickSubkey(
    String table,
    SecretKey metadataKey,
    SecretKey memoryKey,
  ) {
    if (table == 'vault_ai_memory') return memoryKey;
    return metadataKey;
  }

  /// Map a legacy plaintext column to its ciphertext column name.
  /// Only the columns exposed by the backend migration endpoints are
  /// listed. Unknown columns return null and are skipped.
  String? _ciphertextColumnFor(String table, String col) {
    switch (table) {
      case 'uploaded_files':
        switch (col) {
          case 'file_name':
            return 'file_name_ciphertext';
          case 'saved_name':
            return 'saved_name_ciphertext';
          case 'content_type':
            return 'content_type_ciphertext';
          case 'detected_type':
            return 'detected_type_ciphertext';
          case 'detected_service':
            return 'detected_service_ciphertext';
          case 'asset_type':
            return 'asset_type_ciphertext';
        }
        return null;
      case 'vault_items':
        switch (col) {
          case 'item_type':
            return 'item_type_ciphertext';
          case 'service':
            return 'service_ciphertext';
        }
        return null;
      case 'notifications':
        switch (col) {
          case 'title':
            return 'title_ciphertext';
          case 'body':
            return 'body_ciphertext';
          case 'metadata':
            return 'metadata_ciphertext';
        }
        return null;
      default:
        return null;
    }
  }
}

/// Best-effort entry point for main.dart. Never throws; a failure
/// simply defers the migration to the next unlock.
Future<MigrationRunResult> runMetadataMigrationBestEffort({
  required SecretKey mvk,
  required String sessionToken,
  required HttpJsonPost post,
  required HttpJsonGet get,
}) async {
  try {
    final client = MetadataMigrationClient(
      mvk: mvk,
      sessionToken: sessionToken,
      post: post,
      get: get,
    );
    return await client.runOnce();
  } catch (err) {
    return MigrationRunResult(
      batchesApplied: 0,
      rowsApplied: 0,
      rowsSkipped: 0,
      completed: false,
      error: err,
    );
  }
}

// Explicit re-exports so callers only need to import this file to
// pack json-encoded row values.
Uint8List packJsonPayload(Map<String, dynamic> payload) {
  return Uint8List.fromList(utf8.encode(jsonEncode(payload)));
}
