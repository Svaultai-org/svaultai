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
}
