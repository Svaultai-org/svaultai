/// Complete mixed saved-item copy after a linked inheritance release.
///
/// Both old PIN-key and private MVK rows are verified against one inventory.
/// Decryption and beneficiary re-encryption occur only on this device.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'inheritance_v2_item_import.dart';
import 'legacy_ciphertext_migration_codec.dart';
import 'linked_inheritance_v2_readback_proof.dart';
import 'linked_inheritance_v2_release_readback.dart';
import 'vault_key_hierarchy.dart';

const _scope = 'mixed_saved_items_only';
const _maxItems = 100;
const _maxSourceBytes = 1024 * 1024;
const _maxFieldBytes = 128 * 1024;
const _maxDestinationGrowth = 4096;
const _fields = <String>[
  'item_type_ciphertext',
  'service_ciphertext',
  'payload_ciphertext',
];
final _digestPattern = RegExp(r'^[A-Za-z0-9_-]{43}$');

class LinkedV2MixedSavedItemImport {
  final int itemCount;
  final int newItems;
  final String sourceInventorySha256;

  const LinkedV2MixedSavedItemImport({
    required this.itemCount,
    required this.newItems,
    required this.sourceInventorySha256,
  });
}

class _Source {
  final int id;
  final String kind;
  final String rowDigest;
  final int sourceBytes;
  final Map<String, dynamic> row;

  const _Source(this.id, this.kind, this.rowDigest, this.sourceBytes, this.row);
}

class _Prepared {
  final _Source source;
  final String itemType;
  final String title;
  final Map<String, dynamic> payload;
  final String titleHash;
  final Map<String, dynamic> body;

  const _Prepared(
    this.source,
    this.itemType,
    this.title,
    this.payload,
    this.titleHash,
    this.body,
  );
}

typedef FetchMixedSavedItems = Future<Map<String, dynamic>> Function(
    int linkId);
typedef WriteMixedSavedItem = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);
typedef ReadbackMixedSavedItems = Future<Map<String, dynamic>> Function(
  int linkId,
  String sourceInventorySha256,
);

String _b64(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final length = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(length.buffer.asUint8List());
  builder.add(raw);
}

Future<Uint8List> _sha(BytesBuilder builder) async => Uint8List.fromList(
      (await Sha256().hash(builder.toBytes())).bytes,
    );

Uint8List _privateCiphertext(Object? raw) {
  if (raw is! String || !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(raw)) {
    throw const FormatException('Invalid inherited private ciphertext');
  }
  final decoded = b64urlDecode(raw);
  if (decoded.length < 29 ||
      decoded.length > _maxFieldBytes ||
      decoded[0] != 1 ||
      _b64(decoded) != raw) {
    throw const FormatException('Invalid inherited private ciphertext');
  }
  return decoded;
}

int _legacyCiphertextLength(Object? raw) {
  if (raw is! String || raw.isEmpty || raw.length > _maxSourceBytes) {
    throw const FormatException('Invalid inherited old ciphertext');
  }
  final decoded = base64.decode(raw);
  if (decoded.length < 28 || base64.encode(decoded) != raw) {
    throw const FormatException('Invalid inherited old ciphertext');
  }
  return utf8.encode(raw).length;
}

Future<({List<_Source> sources, String digest})> _parse({
  required Map<String, dynamic> exported,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
}) async {
  final count = exported['item_count'];
  final total = exported['ciphertext_bytes'];
  final rows = exported['items'];
  final claimedDigest = exported['source_inventory_sha256'];
  if (exported['beneficiary_link_id'] != released.linkId ||
      exported['owner_vault_id'] != released.ownerVaultId ||
      exported['beneficiary_vault_id'] != beneficiaryVaultId ||
      exported['stage_revision'] != released.stageRevision ||
      exported['offer_commitment'] != released.offerCommitment ||
      exported['content_scope'] != _scope ||
      exported['owner_content_complete'] != false ||
      count is! int ||
      count < 0 ||
      count > _maxItems ||
      total is! int ||
      total < 0 ||
      total > _maxSourceBytes ||
      rows is! List ||
      rows.length != count ||
      claimedDigest is! String ||
      !_digestPattern.hasMatch(claimedDigest)) {
    throw const FormatException('Invalid mixed item inventory');
  }
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-mixed-item-inventory/v1\u0000'));
  for (final value in <Object>[
    released.linkId,
    released.ownerVaultId,
    beneficiaryVaultId,
    released.stageRevision,
  ]) {
    _feed(inventory, value);
  }
  final parsed = <_Source>[];
  var previousId = 0;
  var summed = 0;
  for (final raw in rows) {
    if (raw is! Map) throw const FormatException('Invalid mixed item');
    final row = Map<String, dynamic>.from(raw);
    final id = row['item_id'];
    final kind = row['source_kind'];
    final rowDigest = row['source_row_sha256'];
    if (id is! int ||
        id <= previousId ||
        kind is! String ||
        !{'legacy', 'private'}.contains(kind) ||
        rowDigest is! String ||
        !_digestPattern.hasMatch(rowDigest)) {
      throw const FormatException('Invalid mixed item');
    }
    previousId = id;
    final sourceFields = <Object>[];
    var size = 0;
    if (kind == 'legacy') {
      final itemType = row['item_type'];
      final service = row['service'];
      if (itemType is! String ||
          itemType.trim().isEmpty ||
          utf8.encode(itemType).length > 256 ||
          service is! String ||
          service.trim().isEmpty ||
          utf8.encode(service).length > 256) {
        throw const FormatException('Invalid mixed old item');
      }
      size = _legacyCiphertextLength(row['encrypted_data']);
      sourceFields.addAll([itemType, service, row['encrypted_data'] as String]);
      size += utf8.encode(itemType).length + utf8.encode(service).length;
      summed += _legacyCiphertextLength(row['encrypted_data']);
    } else {
      if (row.containsKey('encrypted_data') ||
          row.containsKey('item_type') ||
          row.containsKey('service')) {
        throw const FormatException('Invalid mixed private item');
      }
      for (final field in _fields) {
        final bytes = _privateCiphertext(row[field]);
        sourceFields.add(bytes);
        size += bytes.length;
        summed += bytes.length;
      }
    }
    if (summed > _maxSourceBytes) {
      throw const FormatException('Mixed item inventory too large');
    }
    final rowBuilder = BytesBuilder()
      ..add(utf8.encode('linked-old-v2-mixed-item-source/v1\u0000'));
    for (final value in <Object>[id, kind, ...sourceFields]) {
      _feed(rowBuilder, value);
    }
    final hash = await _sha(rowBuilder);
    if (_b64(hash) != rowDigest) {
      throw const FormatException('Mixed item source changed');
    }
    _feed(inventory, id);
    _feed(inventory, kind);
    _feed(inventory, hash);
    parsed.add(_Source(id, kind, rowDigest, size, row));
  }
  if (summed != total || _b64(await _sha(inventory)) != claimedDigest) {
    throw const FormatException('Mixed item inventory changed');
  }
  return (sources: parsed, digest: claimedDigest);
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

Future<Set<int>> _verifyCopies({
  required Map<String, dynamic> readback,
  required List<_Prepared> prepared,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
  required String digest,
  required SecretKey beneficiaryMvk,
  required bool Function() accessIsCurrent,
}) async {
  final copies = readback['copies'];
  if (readback['beneficiary_link_id'] != released.linkId ||
      readback['owner_vault_id'] != released.ownerVaultId ||
      readback['beneficiary_vault_id'] != beneficiaryVaultId ||
      readback['stage_revision'] != released.stageRevision ||
      readback['offer_commitment'] != released.offerCommitment ||
      readback['content_scope'] != _scope ||
      readback['owner_content_complete'] != false ||
      readback['legacy_package_preserved'] != true ||
      readback['source_inventory_sha256'] != digest ||
      readback['item_count'] != prepared.length ||
      copies is! List ||
      copies.length > prepared.length ||
      readback['all_items_copied'] != (copies.length == prepared.length)) {
    throw StateError('Mixed item readback differs');
  }
  final expected = {for (final item in prepared) item.source.id: item};
  final seen = <int>{};
  final key = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
  for (final raw in copies) {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
    if (raw is! Map) throw StateError('Invalid mixed item copy');
    final row = Map<String, dynamic>.from(raw);
    final id = row['source_item_id'];
    final item = expected[id];
    if (id is! int ||
        item == null ||
        !seen.add(id) ||
        row['beneficiary_item_id'] is! int ||
        (row['beneficiary_item_id'] as int) <= 0 ||
        row['source_row_sha256'] != item.source.rowDigest ||
        row['title_lookup_hash'] != item.titleHash) {
      throw StateError('Mixed item copy identity differs');
    }
    Future<String> decrypt(String field) async => utf8.decode(
          await aesGcmUnwrap(key, _privateCiphertext(row[field])),
        );
    final type = await decrypt('item_type_ciphertext');
    final title = await decrypt('service_ciphertext');
    final payload = jsonDecode(await decrypt('payload_ciphertext'));
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
    if (type != item.itemType ||
        title != item.title ||
        !_sameJson(payload, item.payload)) {
      throw StateError('Mixed item copy content differs');
    }
  }
  return seen;
}

Future<LinkedV2MixedSavedItemImport> importReleasedLinkedMixedSavedItems({
  required ReleasedLinkedInheritanceV2 released,
  required LinkedReadbackReceipt readbackReceipt,
  required String beneficiaryVaultId,
  required SecretKey beneficiaryMvk,
  required FetchMixedSavedItems fetchExport,
  required WriteMixedSavedItem copyItem,
  required ReadbackMixedSavedItems readbackCopies,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  if (released.linkId <= 0 ||
      released.stageRevision <= 0 ||
      released.linkId != readbackReceipt.linkId ||
      released.stageRevision != readbackReceipt.stageRevision ||
      released.offerCommitment != readbackReceipt.offerCommitment ||
      !_digestPattern.hasMatch(released.offerCommitment) ||
      beneficiaryVaultId.isEmpty ||
      beneficiaryVaultId == released.ownerVaultId) {
    throw const FormatException('Mixed inheritance release is unavailable');
  }
  checkAccess();
  final exported = await fetchExport(released.linkId);
  checkAccess();
  final source = await _parse(
    exported: exported,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  checkAccess();
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final metadataKey = await hierarchy.metadataKey();
  final lookupKey = await hierarchy.savedItemTitleLookupKey();
  final oldKey = released.ownerLegacyKey;
  final oldCodec = oldKey == null
      ? null
      : LegacyCiphertextMigrationCodec(
          legacyKey: oldKey,
          mvk: beneficiaryMvk,
        );
  final prepared = <_Prepared>[];
  for (final raw in source.sources) {
    checkAccess();
    late String itemType;
    late String title;
    late Map<String, dynamic> payload;
    if (raw.kind == 'private') {
      final clear = await decodeInheritedVaultItem(
        ownerMvk: released.ownerMvk,
        encryptedRow: raw.row,
      );
      itemType = clear.itemType;
      title = inheritedItemTitle(clear, released.linkId);
      payload = inheritedItemPayload(
        clear,
        linkId: released.linkId,
        ownerVaultId: released.ownerVaultId,
      );
    } else {
      if (oldCodec == null || (await oldKey!.extractBytes()).length != 32) {
        throw const FormatException('Old item key unavailable');
      }
      itemType = raw.row['item_type'] as String;
      title = '${raw.row['service']} '
          '(inherited ${released.linkId}-${raw.id})';
      final staged = await oldCodec.stageItem(
        itemId: raw.id,
        itemType: itemType,
        service: title,
        legacyCiphertext: raw.row['encrypted_data'] as String,
      );
      final decoded = jsonDecode(utf8.decode(await aesGcmUnwrap(
        metadataKey,
        b64urlDecode(staged.payloadCiphertext),
      )));
      if (decoded is! Map ||
          decoded.containsKey('_svaultai_inheritance_source_v2')) {
        throw const FormatException('Invalid old item payload');
      }
      payload = Map<String, dynamic>.from(decoded)
        ..['_svaultai_inheritance_source_v2'] = <String, Object>{
          'link_id': released.linkId,
          'owner_vault_id': released.ownerVaultId,
          'item_id': raw.id,
        };
    }
    checkAccess();
    if ({'crypto_wallet_account', 'wallet_account'}
        .contains(itemType.trim().toLowerCase())) {
      throw StateError('Wallet accounts need a separate inheritance import');
    }
    final typeCt = await aesGcmWrap(metadataKey, utf8.encode(itemType));
    final titleCt = await aesGcmWrap(metadataKey, utf8.encode(title));
    final payloadCt = await aesGcmWrap(
      metadataKey,
      utf8.encode(jsonEncode(payload)),
    );
    final canonical = '${itemType.trim().toLowerCase()}\u0000'
        '${title.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase()}';
    final titleHash = _b64(
      await keyedLookupHash(lookupKey, utf8.encode(canonical)),
    );
    final destSize = typeCt.length + titleCt.length + payloadCt.length;
    if (destSize > raw.sourceBytes + _maxDestinationGrowth ||
        [typeCt, titleCt, payloadCt]
            .any((field) => field.length > _maxFieldBytes)) {
      throw StateError('Mixed item copy exceeds size limit');
    }
    final body = <String, dynamic>{
      'beneficiary_link_id': released.linkId,
      'source_item_id': raw.id,
      'stage_revision': released.stageRevision,
      'offer_commitment': released.offerCommitment,
      'source_inventory_sha256': source.digest,
      'source_row_sha256': raw.rowDigest,
      'item_type_ciphertext': _b64(typeCt),
      'service_ciphertext': _b64(titleCt),
      'payload_ciphertext': _b64(payloadCt),
      'title_lookup_hash': titleHash,
      'content_scope': _scope,
    };
    checkAccess();
    prepared.add(_Prepared(
      raw,
      itemType,
      title,
      payload,
      titleHash,
      Map<String, dynamic>.unmodifiable(body),
    ));
  }
  final existing = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final copied = await _verifyCopies(
    readback: existing,
    prepared: prepared,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    beneficiaryMvk: beneficiaryMvk,
    accessIsCurrent: accessIsCurrent,
  );
  var newItems = 0;
  for (final item in prepared) {
    checkAccess();
    if (copied.contains(item.source.id)) continue;
    final result = await copyItem(Map<String, dynamic>.from(item.body));
    checkAccess();
    if (result['beneficiary_link_id'] != released.linkId ||
        result['source_item_id'] != item.source.id ||
        result['beneficiary_item_id'] is! int ||
        (result['beneficiary_item_id'] as int) <= 0 ||
        result['source_inventory_sha256'] != source.digest ||
        result['legacy_package_preserved'] != true ||
        result['created'] is! bool) {
      throw StateError('Mixed item copy was not confirmed');
    }
    if (result['created'] == true) newItems++;
    copied.add(item.source.id);
  }
  final finalReadback = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final verified = await _verifyCopies(
    readback: finalReadback,
    prepared: prepared,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    beneficiaryMvk: beneficiaryMvk,
    accessIsCurrent: accessIsCurrent,
  );
  if (verified.length != prepared.length ||
      finalReadback['all_items_copied'] != true) {
    throw StateError('Mixed item copy is incomplete');
  }
  return LinkedV2MixedSavedItemImport(
    itemCount: prepared.length,
    newItems: newItems,
    sourceInventorySha256: source.digest,
  );
}
