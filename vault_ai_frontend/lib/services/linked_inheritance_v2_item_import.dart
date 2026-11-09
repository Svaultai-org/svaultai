/// Bounded saved-item copy after a verified linked inheritance readback.
///
/// Owner ciphertext is decrypted locally, then re-encrypted under the active
/// beneficiary MVK. The server receives only destination ciphertext and a
/// source-inventory digest. A separate readback verifies every copied item.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'inheritance_v2_item_import.dart';
import 'linked_inheritance_v2_readback_proof.dart';
import 'linked_inheritance_v2_release_readback.dart';
import 'vault_key_hierarchy.dart';

typedef FetchLinkedItemExport = Future<Map<String, dynamic>> Function(int linkId);
typedef WriteLinkedItemCopy = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);
typedef ReadbackLinkedItemCopies = Future<Map<String, dynamic>> Function(
  int linkId,
  String inventoryDigest,
);

const _maxItems = 100;
const _maxSourceBytes = 1024 * 1024;
const _maxFieldBytes = 128 * 1024;
const _fields = <String>[
  'item_type_ciphertext',
  'service_ciphertext',
  'payload_ciphertext',
];
final _digestPattern = RegExp(r'^[A-Za-z0-9_-]{43}$');

class LinkedV2SavedItemImport {
  final int itemCount;
  final int newItems;
  final String sourceInventorySha256;

  const LinkedV2SavedItemImport({
    required this.itemCount,
    required this.newItems,
    required this.sourceInventorySha256,
  });
}

class _SourceItem {
  final int id;
  final String rowDigest;
  final InheritedVaultItem clear;
  final String title;
  final Map<String, dynamic> payload;

  const _SourceItem({
    required this.id,
    required this.rowDigest,
    required this.clear,
    required this.title,
    required this.payload,
  });
}

String _b64(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

Uint8List _ciphertext(Object? value) {
  if (value is! String ||
      !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(value)) {
    throw const FormatException('Invalid inherited ciphertext');
  }
  final bytes = Uint8List.fromList(base64Url.decode(base64Url.normalize(value)));
  if (bytes.length < 29 ||
      bytes.length > _maxFieldBytes ||
      bytes[0] != 1 ||
      _b64(bytes) != value) {
    throw const FormatException('Invalid inherited ciphertext');
  }
  return bytes;
}

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final length = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(length.buffer.asUint8List());
  builder.add(raw);
}

Future<String> _hash(BytesBuilder builder) async =>
    _b64((await Sha256().hash(builder.toBytes())).bytes);

Future<String> _rowHash(int id, Map<String, Uint8List> ciphertext) async {
  final data = BytesBuilder()..add(utf8.encode('linked-old-v2-item-source/v1\u0000'));
  _feed(data, id);
  for (final field in _fields) {
    _feed(data, ciphertext[field]!);
  }
  return _hash(data);
}

Future<({List<_SourceItem> items, String digest, int bytes})> _sourceItems({
  required Map<String, dynamic> exported,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
}) async {
  final rawItems = exported['items'];
  final count = exported['item_count'];
  final total = exported['ciphertext_bytes'];
  final claimedDigest = exported['source_inventory_sha256'];
  if (exported['beneficiary_link_id'] != released.linkId ||
      exported['owner_vault_id'] != released.ownerVaultId ||
      exported['beneficiary_vault_id'] != beneficiaryVaultId ||
      exported['stage_revision'] != released.stageRevision ||
      exported['offer_commitment'] != released.offerCommitment ||
      exported['content_scope'] != 'saved_items_only' ||
      exported['owner_content_complete'] != false ||
      count is! int ||
      count < 0 ||
      count > _maxItems ||
      total is! int ||
      total < 0 ||
      total > _maxSourceBytes ||
      rawItems is! List ||
      rawItems.length != count ||
      claimedDigest is! String ||
      !_digestPattern.hasMatch(claimedDigest)) {
    throw const FormatException('Invalid inherited item inventory');
  }
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-item-inventory/v1\u0000'));
  for (final value in <Object>[
    released.linkId,
    released.ownerVaultId,
    beneficiaryVaultId,
    released.stageRevision,
  ]) {
    _feed(inventory, value);
  }
  final parsed = <_SourceItem>[];
  var summed = 0;
  var previousId = 0;
  for (final raw in rawItems) {
    if (raw is! Map) {
      throw const FormatException('Invalid inherited item inventory');
    }
    final row = Map<String, dynamic>.from(raw);
    final id = row['item_id'];
    final rowDigest = row['source_row_sha256'];
    if (id is! int ||
        id <= previousId ||
        rowDigest is! String ||
        !_digestPattern.hasMatch(rowDigest)) {
      throw const FormatException('Invalid inherited item inventory');
    }
    previousId = id;
    final ciphertext = <String, Uint8List>{};
    _feed(inventory, id);
    for (final field in _fields) {
      final encoded = _ciphertext(row[field]);
      ciphertext[field] = encoded;
      summed += encoded.length;
      if (summed > _maxSourceBytes) {
        throw const FormatException('Inherited item inventory too large');
      }
      _feed(inventory, encoded);
    }
    if (rowDigest != await _rowHash(id, ciphertext)) {
      throw const FormatException('Inherited item source hash differs');
    }
    final clear = await decodeInheritedVaultItem(
      ownerMvk: released.ownerMvk,
      encryptedRow: row,
    );
    // Wallet-account payloads can contain inner key wrapping under the owner
    // MVK. Re-encrypting only the outer saved-item fields would strand them.
    if ({'crypto_wallet_account', 'wallet_account'}
        .contains(clear.itemType.trim().toLowerCase())) {
      throw StateError('Wallet accounts need a separate inheritance import');
    }
    parsed.add(_SourceItem(
      id: id,
      rowDigest: rowDigest,
      clear: clear,
      title: inheritedItemTitle(clear, released.linkId),
      payload: inheritedItemPayload(
        clear,
        linkId: released.linkId,
        ownerVaultId: released.ownerVaultId,
      ),
    ));
  }
  if (summed != total || await _hash(inventory) != claimedDigest) {
    throw const FormatException('Inherited item inventory hash differs');
  }
  return (items: parsed, digest: claimedDigest, bytes: summed);
}

bool _deepEquals(Object? a, Object? b) {
  if (a is Map && b is Map) {
    if (a.length != b.length) return false;
    for (final key in a.keys) {
      if (!b.containsKey(key) || !_deepEquals(a[key], b[key])) return false;
    }
    return true;
  }
  if (a is List && b is List) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!_deepEquals(a[i], b[i])) return false;
    }
    return true;
  }
  return a == b;
}

Future<String> _titleLookupHash(
  SecretKey lookupKey, _SourceItem item,
) async {
  final canonical = '${item.clear.itemType.trim().toLowerCase()}\u0000'
      '${item.title.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase()}';
  return _b64(await keyedLookupHash(lookupKey, utf8.encode(canonical)));
}

Future<Set<int>> _verifiedCopies({
  required Map<String, dynamic> readback,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
  required String digest,
  required List<_SourceItem> sources,
  required SecretKey beneficiaryMvk,
}) async {
  final rows = readback['copies'];
  if (readback['beneficiary_link_id'] != released.linkId ||
      readback['owner_vault_id'] != released.ownerVaultId ||
      readback['beneficiary_vault_id'] != beneficiaryVaultId ||
      readback['stage_revision'] != released.stageRevision ||
      readback['offer_commitment'] != released.offerCommitment ||
      readback['content_scope'] != 'saved_items_only' ||
      readback['owner_content_complete'] != false ||
      readback['source_inventory_sha256'] != digest ||
      readback['item_count'] != sources.length ||
      readback['legacy_package_preserved'] != true ||
      rows is! List ||
      rows.length > sources.length ||
      readback['all_items_copied'] != (rows.length == sources.length)) {
    throw StateError('Inherited item copy readback differs');
  }
  final expected = {for (final source in sources) source.id: source};
  final seen = <int>{};
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final key = await hierarchy.metadataKey();
  final lookupKey = await hierarchy.savedItemTitleLookupKey();
  for (final raw in rows) {
    if (raw is! Map) throw StateError('Invalid inherited item copy');
    final row = Map<String, dynamic>.from(raw);
    final id = row['source_item_id'];
    final source = expected[id];
    if (id is! int ||
        source == null ||
        !seen.add(id) ||
        row['beneficiary_item_id'] is! int ||
        (row['beneficiary_item_id'] as int) <= 0 ||
        row['source_row_sha256'] != source.rowDigest) {
      throw StateError('Inherited item copy identity differs');
    }
    if (row['title_lookup_hash'] !=
        await _titleLookupHash(lookupKey, source)) {
      throw StateError('Inherited item copy title index differs');
    }
    Future<String> decrypt(String field) async => utf8.decode(
          await aesGcmUnwrap(key, _ciphertext(row[field])),
        );
    final type = await decrypt('item_type_ciphertext');
    final title = await decrypt('service_ciphertext');
    final payloadRaw = jsonDecode(await decrypt('payload_ciphertext'));
    if (type != source.clear.itemType ||
        title != source.title ||
        !_deepEquals(payloadRaw, source.payload)) {
      throw StateError('Inherited item copy content differs');
    }
  }
  return seen;
}

Future<LinkedV2SavedItemImport> importLinkedV2SavedItems({
  required ReleasedLinkedInheritanceV2 released,
  required LinkedReadbackReceipt readbackReceipt,
  required String beneficiaryVaultId,
  required SecretKey beneficiaryMvk,
  required FetchLinkedItemExport fetchExport,
  required WriteLinkedItemCopy copyItem,
  required ReadbackLinkedItemCopies readbackCopies,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  if (released.linkId != readbackReceipt.linkId ||
      released.stageRevision != readbackReceipt.stageRevision ||
      released.offerCommitment != readbackReceipt.offerCommitment ||
      beneficiaryVaultId.isEmpty ||
      beneficiaryVaultId == released.ownerVaultId) {
    throw const FormatException('Readback receipt does not match release');
  }
  checkAccess();
  final exported = await fetchExport(released.linkId);
  checkAccess();
  final source = await _sourceItems(
    exported: exported,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  checkAccess();
  final existing = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final copied = await _verifiedCopies(
    readback: existing,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    sources: source.items,
    beneficiaryMvk: beneficiaryMvk,
  );
  checkAccess();
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final metaKey = await hierarchy.metadataKey();
  final lookupKey = await hierarchy.savedItemTitleLookupKey();
  var newItems = 0;
  for (final item in source.items) {
    checkAccess();
    if (copied.contains(item.id)) continue;
    final typeCt = await aesGcmWrap(
      metaKey, utf8.encode(item.clear.itemType),
    );
    final titleCt = await aesGcmWrap(metaKey, utf8.encode(item.title));
    final payloadCt = await aesGcmWrap(
      metaKey, utf8.encode(jsonEncode(item.payload)),
    );
    final titleHash = await _titleLookupHash(lookupKey, item);
    checkAccess();
    final result = await copyItem({
      'beneficiary_link_id': released.linkId,
      'source_item_id': item.id,
      'stage_revision': released.stageRevision,
      'offer_commitment': released.offerCommitment,
      'source_inventory_sha256': source.digest,
      'source_row_sha256': item.rowDigest,
      'item_type_ciphertext': _b64(typeCt),
      'service_ciphertext': _b64(titleCt),
      'payload_ciphertext': _b64(payloadCt),
      'title_lookup_hash': titleHash,
      'content_scope': 'saved_items_only',
    });
    checkAccess();
    if (result['beneficiary_link_id'] != released.linkId ||
        result['source_item_id'] != item.id ||
        result['beneficiary_item_id'] is! int ||
        result['source_inventory_sha256'] != source.digest ||
        result['legacy_package_preserved'] != true ||
        result['created'] is! bool) {
      throw StateError('Inherited item copy was not confirmed');
    }
    if (result['created'] == true) newItems++;
    copied.add(item.id);
  }
  final verified = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final finalIds = await _verifiedCopies(
    readback: verified,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    sources: source.items,
    beneficiaryMvk: beneficiaryMvk,
  );
  if (finalIds.length != source.items.length ||
      verified['all_items_copied'] != true) {
    throw StateError('Inherited item copy is incomplete');
  }
  return LinkedV2SavedItemImport(
    itemCount: source.items.length,
    newItems: newItems,
    sourceInventorySha256: source.digest,
  );
}
