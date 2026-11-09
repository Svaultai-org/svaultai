// A legacy saved-item edit is encrypted and verified on the owner device.
// The old ciphertext stays active until a fresh OPAQUE proof promotes an
// exact readback of the staged replacement.

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'legacy_ciphertext_migration_codec.dart';
import 'vault_key_hierarchy.dart';
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
  final String? stagedSourceSnapshot;
  final String? stagedItemTypeCiphertext;
  final String? stagedServiceCiphertext;
  final String? stagedPayloadCiphertext;

  const LegacySavedItemSource({
    required this.itemId,
    required this.itemType,
    required this.service,
    required this.sourceSnapshot,
    required this.ciphertext,
    this.stagedSourceSnapshot,
    this.stagedItemTypeCiphertext,
    this.stagedServiceCiphertext,
    this.stagedPayloadCiphertext,
  });
}

class LegacySavedItemReplacement {
  static const int maxCiphertextChars = 8 * 1024 * 1024;
  static const int maxCandidateCiphertextChars = 174764;

  final SecretKey legacyKey;
  final SecretKey mvk;
  final Future<LegacySavedItemSource> Function(int itemId) sourceReader;
  final Future<String> Function() proofProvider;
  final LegacyItemRequest post;
  final LegacyItemRead get;
  final void Function() requireCurrentSession;
  final bool allowEncryptedRename;

  const LegacySavedItemReplacement({
    required this.legacyKey,
    required this.mvk,
    required this.sourceReader,
    required this.proofProvider,
    required this.post,
    required this.get,
    required this.requireCurrentSession,
    this.allowEncryptedRename = false,
  });

  String _canonicalTitle(String value) =>
      value.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();

  Future<String> _metadataLabel(
    Map<String, dynamic> row,
    String encryptedField,
    String plainField,
    SecretKey key,
  ) async {
    final encrypted = row[encryptedField];
    if (encrypted is String && encrypted.isNotEmpty) {
      final label = utf8.decode(
        await aesGcmUnwrap(key, b64urlDecode(encrypted)),
      );
      requireCurrentSession();
      return label;
    }
    final plain = row[plainField];
    if (row['is_legacy'] == true && plain is String && plain.isNotEmpty) {
      return plain;
    }
    throw const FormatException('Saved-item metadata is incomplete');
  }

  Future<void> _ensureRenameDoesNotDuplicate(
    int itemId,
    String itemType,
    String title,
    SecretKey metadataKey,
  ) async {
    var afterId = 0;
    for (var page = 0; page < 1000; page++) {
      requireCurrentSession();
      final body = await get(
        '/vault/items/metadata?after_item_id=$afterId&limit=100',
      );
      requireCurrentSession();
      final records = body['records'];
      if (records is! List || records.length > 100) {
        throw const FormatException('Saved-item inventory is incomplete');
      }
      for (final raw in records) {
        if (raw is! Map) {
          throw const FormatException('Saved-item inventory is invalid');
        }
        final row = Map<String, dynamic>.from(raw);
        final id = row['item_id'];
        if (id is! int || id <= afterId) {
          throw const FormatException('Saved-item inventory is out of order');
        }
        afterId = id;
        final type = await _metadataLabel(
          row,
          'item_type_ciphertext',
          'item_type',
          metadataKey,
        );
        final service = await _metadataLabel(
          row,
          'service_ciphertext',
          'service',
          metadataKey,
        );
        if (id != itemId &&
            type.trim().toLowerCase() == itemType.trim().toLowerCase() &&
            _canonicalTitle(service) == _canonicalTitle(title)) {
          throw StateError('A saved item already uses that title');
        }
      }
      if (body['has_more'] == false) return;
      if (body['has_more'] != true ||
          records.isEmpty ||
          body['next_after_item_id'] != afterId) {
        throw const FormatException('Saved-item inventory is incomplete');
      }
    }
    throw const FormatException('Saved-item inventory is too large');
  }

  Future<void> _verifyRenamedMetadata(
    int itemId,
    String title,
    String expectedCiphertext,
    SecretKey metadataKey,
  ) async {
    requireCurrentSession();
    final body = await get(
      '/vault/items/metadata?after_item_id=${itemId - 1}&limit=1',
    );
    requireCurrentSession();
    final rows = body['records'];
    if (rows is! List || rows.length != 1 || rows.single is! Map) {
      throw const FormatException('Renamed saved item is unavailable');
    }
    final row = Map<String, dynamic>.from(rows.single as Map);
    if (row['item_id'] != itemId ||
        row['is_legacy'] != true ||
        row['service_ciphertext'] != expectedCiphertext ||
        await _metadataLabel(
              row,
              'service_ciphertext',
              'service',
              metadataKey,
            ) !=
            title) {
      throw const FormatException('Renamed saved-item readback did not match');
    }
  }

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
    final rename =
        newService != null &&
        newService.trim().isNotEmpty &&
        newService.trim() != oldService;
    if (rename && !allowEncryptedRename) {
      throw StateError('Private saved-item rename is not available yet');
    }
    final title = rename ? newService.trim() : oldService;
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
    final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
    requireCurrentSession();
    String? titleCiphertext;
    String? titleLookupHash;
    if (rename) {
      await _ensureRenameDoesNotDuplicate(itemId, itemType, title, metadataKey);
      requireCurrentSession();
      titleCiphertext = b64urlEncode(
        await aesGcmWrap(metadataKey, utf8.encode(title)),
      );
      final lookupKey = await VaultKeyHierarchy(mvk).savedItemTitleLookupKey();
      titleLookupHash = b64urlEncode(
        await keyedLookupHash(
          lookupKey,
          utf8.encode(
            '${itemType.trim().toLowerCase()}\u0000${_canonicalTitle(title)}',
          ),
        ),
      );
      requireCurrentSession();
    }
    final codec = LegacyCiphertextMigrationCodec(
      legacyKey: legacyKey,
      mvk: mvk,
    );
    final oldRecord = await codec.decodeLegacyItem(source.ciphertext);
    requireCurrentSession();
    final hasStagedCopy =
        source.stagedItemTypeCiphertext != null ||
        source.stagedPayloadCiphertext != null;
    if (hasStagedCopy) {
      final stagedSnapshot = source.stagedSourceSnapshot;
      final stagedType = source.stagedItemTypeCiphertext;
      final stagedService = source.stagedServiceCiphertext;
      final stagedPayload = source.stagedPayloadCiphertext;
      if (stagedSnapshot == null ||
          !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(stagedSnapshot) ||
          stagedType == null ||
          stagedService == null ||
          stagedPayload == null ||
          !await codec.verifyStagedItem(
            itemType: itemType,
            service: oldService,
            legacyCiphertext: source.ciphertext,
            itemTypeCiphertext: stagedType,
            serviceCiphertext: stagedService,
            payloadCiphertext: stagedPayload,
          )) {
        throw const FormatException(
          'Staged saved item differs from its source',
        );
      }
      requireCurrentSession();
    }
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
    if (candidate.length > maxCandidateCiphertextChars) {
      throw const FormatException('Saved item is too large');
    }
    final base = '/vault/items/legacy-ciphertext/$itemId/replace';
    await post('$base/stage', <String, dynamic>{
      'source_snapshot': source.sourceSnapshot,
      'candidate_encrypted_data': candidate,
      if (hasStagedCopy) 'staged_source_snapshot': source.stagedSourceSnapshot,
      if (hasStagedCopy) 'client_verified_staged_copy': true,
      if (rename) 'new_service_ciphertext': titleCiphertext,
      if (rename) 'new_title_lookup_hash': titleLookupHash,
    });
    requireCurrentSession();
    final staged = await get('$base/staged');
    requireCurrentSession();
    final receipt = staged['readback_receipt'];
    if (staged['item_id'] != itemId ||
        staged['source_snapshot'] != source.sourceSnapshot ||
        staged['candidate_encrypted_data'] != candidate ||
        (staged.containsKey('new_service') && staged['new_service'] != null) ||
        staged['new_service_ciphertext'] != titleCiphertext ||
        staged['new_title_lookup_hash'] != titleLookupHash ||
        receipt is! String ||
        receipt.isEmpty ||
        receipt.length > 256) {
      throw const FormatException('Saved-item readback did not match');
    }
    if (rename &&
        utf8.decode(
              await aesGcmUnwrap(metadataKey, b64urlDecode(titleCiphertext!)),
            ) !=
            title) {
      throw const FormatException('Saved-item title readback did not match');
    }
    final readback = await codec.decodeLegacyItem(
      staged['candidate_encrypted_data'] as String,
    );
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
        (rename ? promoted['renamed'] != true : promoted['renamed'] == true) ||
        (rename && promoted['service_ciphertext'] != titleCiphertext) ||
        promoted['updated'] != true) {
      throw const FormatException('Saved-item promotion result is invalid');
    }
    if (rename) {
      await _verifyRenamedMetadata(
        itemId,
        title,
        titleCiphertext!,
        metadataKey,
      );
      requireCurrentSession();
    }
    return promoted;
  }
}
