// A legacy saved-item edit is encrypted and verified on the owner device.
// The old ciphertext stays active until a fresh OPAQUE proof promotes an
// exact readback of the staged replacement.

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'legacy_ciphertext_migration_codec.dart';
import 'zk_proof_token_guard.dart';

typedef LegacyItemRequest =
    Future<Map<String, dynamic>> Function(
      String path,
      Map<String, dynamic> body,
    );
typedef LegacyItemRead = Future<Map<String, dynamic>> Function(String path);

class LegacySavedItemSource {
  final int itemId;
  final String itemType;
  final String service;
  final String sourceSnapshot;
  final String ciphertext;

  const LegacySavedItemSource({
    required this.itemId,
    required this.itemType,
    required this.service,
    required this.sourceSnapshot,
    required this.ciphertext,
  });
}

class LegacySavedItemReplacement {
  static const int maxCiphertextChars = 8 * 1024 * 1024;

  final SecretKey legacyKey;
  final SecretKey mvk;
  final Future<LegacySavedItemSource> Function(int itemId) sourceReader;
  final Future<String> Function() proofProvider;
  final LegacyItemRequest post;
  final LegacyItemRead get;
  final void Function() requireCurrentSession;

  const LegacySavedItemReplacement({
    required this.legacyKey,
    required this.mvk,
    required this.sourceReader,
    required this.proofProvider,
    required this.post,
    required this.get,
    required this.requireCurrentSession,
  });

  Future<Map<String, dynamic>> replace({
    required int itemId,
    required String itemType,
    required String oldService,
    String? newService,
    Map<String, dynamic>? fields,
  }) async {
    if (itemId <= 0 || itemType.trim().isEmpty || oldService.trim().isEmpty) {
      throw const FormatException('Invalid saved-item identity');
    }
    final title = newService?.trim().isNotEmpty == true
        ? newService!.trim()
        : oldService;
    if (title.trim().isEmpty || title.length > 256) {
      throw const FormatException('Invalid saved-item title');
    }
    requireCurrentSession();
    final source = await sourceReader(itemId);
    requireCurrentSession();
    if (source.itemId != itemId ||
        source.itemType != itemType ||
        source.service != oldService ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot) ||
        source.ciphertext.length > maxCiphertextChars) {
      throw const FormatException('Saved item changed during edit');
    }
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: legacyKey,
      mvk: mvk,
    );
    final oldRecord = await codec.decodeLegacyItem(source.ciphertext);
    requireCurrentSession();
    const envelopeKeys = <String>{'category', 'title', 'fields', 'item_id'};
    final hasEnvelope = envelopeKeys.any(oldRecord.containsKey);
    final oldFields = hasEnvelope ? oldRecord['fields'] : oldRecord;
    if (oldFields is! Map) {
      throw const FormatException('Invalid saved-item fields');
    }
    final mergedFields = <String, dynamic>{
      ...Map<String, dynamic>.from(oldFields),
      if (fields != null) ...fields,
    };
    final merged = <String, dynamic>{
      if (hasEnvelope) ...oldRecord,
      'category': hasEnvelope && oldRecord['category'] is String
          ? oldRecord['category']
          : itemType,
      'title': title,
      'fields': mergedFields,
      'notes': hasEnvelope ? oldRecord['notes'] : null,
      'item_id': hasEnvelope && oldRecord['item_id'] != null
          ? oldRecord['item_id']
          : itemId,
    };
    final candidate = await codec.encodeLegacyItem(merged);
    requireCurrentSession();
    if (candidate.length > maxCiphertextChars) {
      throw const FormatException('Saved item is too large');
    }
    final base = '/vault/items/legacy-ciphertext/$itemId/replace';
    await post('$base/stage', <String, dynamic>{
      'source_snapshot': source.sourceSnapshot,
      'candidate_encrypted_data': candidate,
      if (title != oldService) 'new_service': title,
    });
    requireCurrentSession();
    final staged = await get('$base/staged');
    requireCurrentSession();
    final receipt = staged['readback_receipt'];
    if (staged['item_id'] != itemId ||
        staged['source_snapshot'] != source.sourceSnapshot ||
        staged['candidate_encrypted_data'] != candidate ||
        staged['new_service'] != (title == oldService ? null : title) ||
        receipt is! String ||
        receipt.isEmpty ||
        receipt.length > 256) {
      throw const FormatException('Saved-item readback did not match');
    }
    final readback = await codec.decodeLegacyItem(candidate);
    requireCurrentSession();
    if (jsonEncode(readback) != jsonEncode(merged)) {
      throw const FormatException('Saved-item readback could not be verified');
    }
    final proof = rejectPinShapedZkProof(await proofProvider());
    requireCurrentSession();
    final promoted = await post('$base/promote', <String, dynamic>{
      'source_snapshot': source.sourceSnapshot,
      'readback_receipt': receipt,
      'zk_proof_token': proof,
      'client_verified_exact_content': true,
    });
    requireCurrentSession();
    if (promoted['item_id'] != itemId ||
        promoted['id'] != itemId ||
        promoted['item_type'] != itemType ||
        promoted['service'] != title ||
        promoted['updated'] != true) {
      throw const FormatException('Saved-item promotion result is invalid');
    }
    return promoted;
  }
}
