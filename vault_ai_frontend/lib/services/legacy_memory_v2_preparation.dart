// Prepare an MVK-encrypted copy of older Memory records on the owner device.
// The active PIN-key record stays untouched for existing clients. No raw PIN,
// key, or plaintext memory is sent to the preparation endpoints.

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';
import 'vault_key_hierarchy.dart';

typedef LegacyMemoryCopyPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body,
);
typedef LegacyMemoryCopyGet = Future<Map<String, dynamic>> Function(
    String path);

class LegacyMemoryV2Preparation {
  final LegacyCiphertextExportClient export;
  final LegacyCiphertextMigrationCodec codec;
  final SecretKey mvk;
  final Future<String> Function() proofProvider;
  final LegacyMemoryCopyPost post;
  final LegacyMemoryCopyGet get;
  final bool Function() accessIsCurrent;
  final void Function(int verified)? onProgress;

  const LegacyMemoryV2Preparation({
    required this.export,
    required this.codec,
    required this.mvk,
    required this.proofProvider,
    required this.post,
    required this.get,
    required this.accessIsCurrent,
    this.onProgress,
  });

  void _requireAccess() {
    if (!accessIsCurrent()) throw StateError('Vault session changed');
  }

  Future<int> prepare({int maxRecords = 5000}) async {
    _requireAccess();
    final inventory = await export.listMemoriesBounded(maxRecords: maxRecords);
    _requireAccess();
    final memoryKey = await VaultKeyHierarchy(mvk).memoryKey();
    var prepared = 0;
    for (final row in inventory) {
      _requireAccess();
      final id = row['memory_id'];
      final size = row['ciphertext_chars'];
      final type = row['memory_type'];
      if (id is! int ||
          id <= 0 ||
          size is! int ||
          size <= 0 ||
          size > 128 * 1024 ||
          type is! String ||
          type.isEmpty) {
        throw const FormatException('Invalid older Memory inventory');
      }
      final source = await export.readMemorySource(
        memoryId: id,
        ciphertextChars: size,
      );
      _requireAccess();
      if (source.sourceMetadata['memory_type'] != type ||
          !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot)) {
        throw const FormatException('Older Memory source changed');
      }
      final plaintext = await codec.decodeLegacyString(source.ciphertext);
      _requireAccess();
      final decoded = jsonDecode(plaintext);
      if (decoded is! Map<String, dynamic> ||
          decoded.isEmpty ||
          (decoded['memory_type'] != null && decoded['memory_type'] != type)) {
        throw const FormatException('Invalid older Memory payload');
      }
      final ciphertext = b64urlEncode(
        await aesGcmWrap(memoryKey, utf8.encode(plaintext)),
      );
      _requireAccess();
      final proof = await proofProvider();
      _requireAccess();
      final base = '/vault/memory/legacy-copy/$id';
      final staged = await post('$base/stage', <String, dynamic>{
        'source_snapshot': source.sourceSnapshot,
        'payload_ciphertext': ciphertext,
        'zk_proof_token': proof,
        'client_verified_source': true,
      });
      _requireAccess();
      if (staged['memory_id'] != id ||
          staged['prepared'] != true ||
          staged['active_legacy_unchanged'] != true) {
        throw const FormatException('Older Memory copy was not prepared');
      }
      final readback = await get('$base/readback');
      _requireAccess();
      if (readback['memory_id'] != id ||
          readback['source_snapshot'] != source.sourceSnapshot ||
          readback['memory_record_id'] != 'memory-migrated-$id' ||
          readback['memory_type'] != type ||
          readback['payload_ciphertext'] != ciphertext) {
        throw const FormatException('Older Memory copy changed');
      }
      final opened = utf8.decode(await aesGcmUnwrap(
        memoryKey,
        b64urlDecode(readback['payload_ciphertext'] as String),
      ));
      _requireAccess();
      if (opened != plaintext) {
        throw const FormatException('Older Memory copy does not match source');
      }
      prepared++;
      onProgress?.call(prepared);
    }
    return prepared;
  }

  Future<({int id, String snapshot, String plaintext})> _verifyCurrent(
      Map<String, dynamic> current) async {
    _requireAccess();
    final id = current['legacy_memory_id'];
    final snapshot = current['source_snapshot'];
    if (id is! int || id <= 0 || snapshot is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(snapshot)) {
      throw const FormatException('Invalid older Memory identity');
    }
    final inventory = await export.listMemoriesBounded(maxRecords: 5000);
    _requireAccess();
    Map<String, dynamic>? entry;
    for (final row in inventory) {
      if (row['memory_id'] == id) {
        entry = row;
        break;
      }
    }
    if (entry == null || entry['ciphertext_chars'] is! int) {
      throw StateError('Older Memory changed. Refresh and try again.');
    }
    final source = await export.readMemorySource(
      memoryId: id,
      ciphertextChars: entry['ciphertext_chars'] as int,
    );
    _requireAccess();
    if (source.sourceSnapshot != snapshot) {
      throw StateError('Older Memory changed. Refresh and try again.');
    }
    final oldPlaintext = await codec.decodeLegacyString(source.ciphertext);
    _requireAccess();
    final readback = await get('/vault/memory/legacy-copy/$id/readback');
    _requireAccess();
    if (readback['source_snapshot'] != snapshot ||
        readback['memory_record_id'] != 'memory-migrated-$id' ||
        readback['payload_ciphertext'] is! String) {
      throw StateError('Older Memory changed. Refresh and try again.');
    }
    final memoryKey = await VaultKeyHierarchy(mvk).memoryKey();
    final copyPlaintext = utf8.decode(await aesGcmUnwrap(
      memoryKey,
      b64urlDecode(readback['payload_ciphertext'] as String),
    ));
    _requireAccess();
    if (copyPlaintext != oldPlaintext) {
      throw StateError('Older Memory copy differs from its source.');
    }
    return (id: id, snapshot: snapshot, plaintext: oldPlaintext);
  }

  /// Preserve visibility to old clients by writing both ciphertext formats
  /// atomically on the server. The PIN and both encryption keys stay local.
  Future<void> edit({
    required Map<String, dynamic> current,
    required Map<String, dynamic> updated,
    required String expectedMemoryGeneration,
  }) async {
    if (!RegExp(r'^(0|[1-9][0-9]{0,18})$')
        .hasMatch(expectedMemoryGeneration)) {
      throw const FormatException('Invalid Memory inventory generation');
    }
    final verified = await _verifyCurrent(current);
    final old = jsonDecode(verified.plaintext);
    if (old is! Map<String, dynamic>) {
      throw const FormatException('Invalid older Memory source');
    }
    final next = <String, dynamic>{...old, ...updated};
    // The editor omits cleared optional fields. Do not resurrect their old
    // values when retaining the rest of the legacy payload shape.
    for (final key in const ['event_date', 'tags', 'custom_fields']) {
      if (!updated.containsKey(key)) next.remove(key);
    }
    final type = next['memory_type'];
    if (type is! String || type.isEmpty) {
      throw const FormatException('Invalid older Memory type');
    }
    final nextPlaintext = jsonEncode(next);
    final legacyCiphertext = await codec.encodeLegacyItem(next);
    if (await codec.decodeLegacyString(legacyCiphertext) != nextPlaintext) {
      throw const FormatException('Older Memory local encryption failed');
    }
    final memoryKey = await VaultKeyHierarchy(mvk).memoryKey();
    final v2Ciphertext = b64urlEncode(
      await aesGcmWrap(memoryKey, utf8.encode(nextPlaintext)),
    );
    if (utf8.decode(await aesGcmUnwrap(
          memoryKey, b64urlDecode(v2Ciphertext),
        )) != nextPlaintext) {
      throw const FormatException('Private Memory local encryption failed');
    }
    _requireAccess();
    final proof = await proofProvider();
    _requireAccess();
    final base = '/vault/memory/legacy-copy/${verified.id}';
    final result = await post('$base/edit', <String, dynamic>{
      'source_snapshot': verified.snapshot,
      'memory_type': type,
      'legacy_payload_ciphertext': legacyCiphertext,
      'payload_ciphertext': v2Ciphertext,
      'expected_memory_generation': expectedMemoryGeneration,
      'zk_proof_token': proof,
      'client_verified_source': true,
    });
    _requireAccess();
    final nextSnapshot = result['source_snapshot'];
    if (result['memory_id'] != verified.id ||
        nextSnapshot is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(nextSnapshot) ||
        result['active_legacy_updated'] != true ||
        result['prepared_copy_updated'] != true) {
      throw const FormatException('Older Memory edit was not committed');
    }
    final readback = await get('$base/readback');
    _requireAccess();
    if (readback['source_snapshot'] != nextSnapshot ||
        readback['payload_ciphertext'] != v2Ciphertext) {
      throw const FormatException('Older Memory edit readback changed');
    }
    final decrypted = utf8.decode(await aesGcmUnwrap(
      memoryKey, b64urlDecode(v2Ciphertext),
    ));
    _requireAccess();
    if (decrypted != nextPlaintext) {
      throw const FormatException('Older Memory edit readback differs');
    }
    final afterInventory = await export.listMemoriesBounded(maxRecords: 5000);
    _requireAccess();
    Map<String, dynamic>? afterEntry;
    for (final row in afterInventory) {
      if (row['memory_id'] == verified.id) {
        afterEntry = row;
        break;
      }
    }
    if (afterEntry == null || afterEntry['ciphertext_chars'] is! int) {
      throw const FormatException('Older Memory source readback unavailable');
    }
    final afterSource = await export.readMemorySource(
      memoryId: verified.id,
      ciphertextChars: afterEntry['ciphertext_chars'] as int,
    );
    _requireAccess();
    if (afterSource.sourceSnapshot != nextSnapshot ||
        await codec.decodeLegacyString(afterSource.ciphertext) != nextPlaintext) {
      throw const FormatException('Older Memory source readback differs');
    }
  }

  /// Hide from both clients without physically deleting encrypted source.
  Future<void> delete(Map<String, dynamic> current) async {
    final verified = await _verifyCurrent(current);
    _requireAccess();
    final proof = await proofProvider();
    _requireAccess();
    final result = await post(
      '/vault/memory/legacy-copy/${verified.id}/delete',
      <String, dynamic>{
        'source_snapshot': verified.snapshot,
        'zk_proof_token': proof,
        'client_confirmed_delete': true,
      },
    );
    _requireAccess();
    if (result['memory_id'] != verified.id ||
        result['hidden_from_old_clients'] != true ||
        result['original_ciphertext_preserved'] != true) {
      throw const FormatException('Older Memory delete was not committed');
    }
  }
}
