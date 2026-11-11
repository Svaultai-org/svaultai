/// Device-only preparation and readback checks for older inherited items.
///
/// This deliberately has no transport. A future copy endpoint must verify the
/// released link, receipt, and source inventory on every write. The only body
/// this service prepares contains beneficiary ciphertext and source digests.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'legacy_ciphertext_migration_codec.dart';
import 'linked_inheritance_v2_readback_proof.dart';
import 'linked_inheritance_v2_release_readback.dart';
import 'vault_key_hierarchy.dart';

const _maxItems = 100;
const _maxSourceBytes = 1024 * 1024;
const _maxLabelBytes = 256;
const _maxDestinationGrowth = 4096;
final _digestPattern = RegExp(r'^[A-Za-z0-9_-]{43}$');
const _fields = <String>[
  'item_type_ciphertext',
  'service_ciphertext',
  'payload_ciphertext',
];

class _LegacySource {
  final int id;
  final String itemType;
  final String service;
  final String ciphertext;
  final String rowDigest;

  const _LegacySource(
    this.id,
    this.itemType,
    this.service,
    this.ciphertext,
    this.rowDigest,
  );
}

class _PreparedSource {
  final _LegacySource source;
  final String title;
  final Map<String, dynamic> expectedPayload;
  final String titleLookupHash;

  const _PreparedSource(
    this.source,
    this.title,
    this.expectedPayload,
    this.titleLookupHash,
  );
}

class PreparedLinkedLegacyItems {
  final int linkId;
  final int stageRevision;
  final String offerCommitment;
  final String ownerVaultId;
  final String beneficiaryVaultId;
  final String sourceInventorySha256;
  final List<Map<String, Object>> copyBodies;
  final List<_PreparedSource> _sources;

  const PreparedLinkedLegacyItems._({
    required this.linkId,
    required this.stageRevision,
    required this.offerCommitment,
    required this.ownerVaultId,
    required this.beneficiaryVaultId,
    required this.sourceInventorySha256,
    required this.copyBodies,
    required List<_PreparedSource> sources,
  }) : _sources = sources;

  int get itemCount => _sources.length;
}

String _b64(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

void _feed(BytesBuilder builder, Object value) {
  final raw = value is List<int> ? value : utf8.encode(value.toString());
  final length = ByteData(8)..setUint64(0, raw.length, Endian.big);
  builder.add(length.buffer.asUint8List());
  builder.add(raw);
}

Future<Uint8List> _sha(BytesBuilder builder) async =>
    Uint8List.fromList((await Sha256().hash(builder.toBytes())).bytes);

Uint8List _legacyCiphertext(String encoded) {
  if (encoded.isEmpty || encoded.length > _maxSourceBytes) {
    throw const FormatException('Invalid inherited legacy ciphertext');
  }
  final bytes = Uint8List.fromList(base64.decode(encoded));
  if (bytes.length < 28 || base64.encode(bytes) != encoded) {
    throw const FormatException('Invalid inherited legacy ciphertext');
  }
  return bytes;
}

Uint8List _privateCiphertext(Object? encoded) {
  if (encoded is! String || !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(encoded)) {
    throw const FormatException('Invalid copied item ciphertext');
  }
  final bytes = b64urlDecode(encoded);
  if (bytes.length < 29 ||
      bytes.length > 128 * 1024 ||
      bytes[0] != 1 ||
      _b64(bytes) != encoded) {
    throw const FormatException('Invalid copied item ciphertext');
  }
  return bytes;
}

Future<({List<_LegacySource> rows, String digest})> _parseExport({
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
      exported['content_scope'] != 'legacy_saved_items_only' ||
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
    throw const FormatException('Invalid inherited legacy item inventory');
  }
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-legacy-item-inventory/v1\u0000'));
  for (final value in <Object>[
    released.linkId,
    released.ownerVaultId,
    beneficiaryVaultId,
    released.stageRevision,
  ]) {
    _feed(inventory, value);
  }
  final parsed = <_LegacySource>[];
  var summed = 0;
  var previousId = 0;
  for (final raw in rawItems) {
    if (raw is! Map) {
      throw const FormatException('Invalid inherited legacy item');
    }
    final row = Map<String, dynamic>.from(raw);
    final id = row['item_id'];
    final itemType = row['item_type'];
    final service = row['service'];
    final ciphertext = row['encrypted_data'];
    final rowDigest = row['source_row_sha256'];
    if (id is! int ||
        id <= previousId ||
        itemType is! String ||
        itemType.trim().isEmpty ||
        utf8.encode(itemType).length > _maxLabelBytes ||
        service is! String ||
        service.trim().isEmpty ||
        utf8.encode(service).length > _maxLabelBytes ||
        ciphertext is! String ||
        rowDigest is! String ||
        !_digestPattern.hasMatch(rowDigest)) {
      throw const FormatException('Invalid inherited legacy item');
    }
    _legacyCiphertext(ciphertext);
    summed += utf8.encode(ciphertext).length;
    if (summed > _maxSourceBytes) {
      throw const FormatException('Inherited legacy inventory too large');
    }
    final rowHash = BytesBuilder()
      ..add(utf8.encode('linked-old-v2-legacy-item-source/v1\u0000'));
    for (final value in <Object>[id, itemType, service, ciphertext]) {
      _feed(rowHash, value);
    }
    final rowHashBytes = await _sha(rowHash);
    if (_b64(rowHashBytes) != rowDigest) {
      throw const FormatException('Inherited legacy item changed');
    }
    _feed(inventory, id);
    _feed(inventory, rowHashBytes);
    parsed.add(_LegacySource(id, itemType, service, ciphertext, rowDigest));
    previousId = id;
  }
  if (summed != total || _b64(await _sha(inventory)) != claimedDigest) {
    throw const FormatException('Inherited legacy inventory changed');
  }
  return (rows: parsed, digest: claimedDigest);
}

Future<PreparedLinkedLegacyItems> prepareReleasedLinkedLegacyItems({
  required ReleasedLinkedInheritanceV2 released,
  required LinkedReadbackReceipt readbackReceipt,
  required String beneficiaryVaultId,
  required SecretKey beneficiaryMvk,
  required Map<String, dynamic> exported,
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
      beneficiaryVaultId == released.ownerVaultId ||
      released.ownerLegacyKey == null ||
      (await released.ownerLegacyKey!.extractBytes()).length != 32) {
    throw const FormatException('Legacy inheritance release is unavailable');
  }
  checkAccess();
  final inventory = await _parseExport(
    exported: exported,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  checkAccess();
  final codec = LegacyCiphertextMigrationCodec(
    legacyKey: released.ownerLegacyKey!,
    mvk: beneficiaryMvk,
  );
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final metadataKey = await hierarchy.metadataKey();
  final lookupKey = await hierarchy.savedItemTitleLookupKey();
  final sources = <_PreparedSource>[];
  final bodies = <Map<String, Object>>[];
  for (final source in inventory.rows) {
    checkAccess();
    if ({
      'crypto_wallet_account',
      'wallet_account',
    }.contains(source.itemType.trim().toLowerCase())) {
      throw StateError('Wallet accounts need a separate inheritance import');
    }
    final title = '${source.service} '
        '(inherited ${released.linkId}-${source.id})';
    final staged = await codec.stageItem(
      itemId: source.id,
      itemType: source.itemType,
      service: title,
      legacyCiphertext: source.ciphertext,
    );
    checkAccess();
    final stagedPayload = jsonDecode(
      utf8.decode(
        await aesGcmUnwrap(metadataKey, b64urlDecode(staged.payloadCiphertext)),
      ),
    );
    if (stagedPayload is! Map ||
        stagedPayload.containsKey('_svaultai_inheritance_source_v2')) {
      throw const FormatException('Invalid inherited legacy item payload');
    }
    final payload = Map<String, dynamic>.from(stagedPayload)
      ..['_svaultai_inheritance_source_v2'] = <String, Object>{
        'link_id': released.linkId,
        'owner_vault_id': released.ownerVaultId,
        'item_id': source.id,
      };
    final payloadCt = await aesGcmWrap(
      metadataKey,
      utf8.encode(jsonEncode(payload)),
    );
    final canonical = '${source.itemType.trim().toLowerCase()}\u0000'
        '${title.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase()}';
    final titleHash = _b64(
      await keyedLookupHash(lookupKey, utf8.encode(canonical)),
    );
    final body = <String, Object>{
      'beneficiary_link_id': released.linkId,
      'source_item_id': source.id,
      'stage_revision': released.stageRevision,
      'offer_commitment': released.offerCommitment,
      'source_inventory_sha256': inventory.digest,
      'source_row_sha256': source.rowDigest,
      'item_type_ciphertext': staged.itemTypeCiphertext,
      'service_ciphertext': staged.serviceCiphertext,
      'payload_ciphertext': b64urlEncode(payloadCt),
      'title_lookup_hash': titleHash,
      'content_scope': 'legacy_saved_items_only',
    };
    final destinationBytes = _fields.fold<int>(
      0,
      (total, field) => total + b64urlDecode(body[field] as String).length,
    );
    if (destinationBytes >
        utf8.encode(source.ciphertext).length +
            utf8.encode(source.itemType).length +
            utf8.encode(source.service).length +
            _maxDestinationGrowth) {
      throw StateError('Inherited legacy item copy exceeds size limit');
    }
    checkAccess();
    sources.add(_PreparedSource(source, title, payload, titleHash));
    bodies.add(Map<String, Object>.unmodifiable(body));
  }
  return PreparedLinkedLegacyItems._(
    linkId: released.linkId,
    stageRevision: released.stageRevision,
    offerCommitment: released.offerCommitment,
    ownerVaultId: released.ownerVaultId,
    beneficiaryVaultId: beneficiaryVaultId,
    sourceInventorySha256: inventory.digest,
    copyBodies: List<Map<String, Object>>.unmodifiable(bodies),
    sources: List<_PreparedSource>.unmodifiable(sources),
  );
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

Future<Set<int>> verifyLinkedLegacyItemCopies({
  required PreparedLinkedLegacyItems prepared,
  required Map<String, dynamic> readback,
  required SecretKey beneficiaryMvk,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  checkAccess();
  final copies = readback['copies'];
  if (readback['beneficiary_link_id'] != prepared.linkId ||
      readback['owner_vault_id'] != prepared.ownerVaultId ||
      readback['beneficiary_vault_id'] != prepared.beneficiaryVaultId ||
      readback['stage_revision'] != prepared.stageRevision ||
      readback['offer_commitment'] != prepared.offerCommitment ||
      readback['content_scope'] != 'legacy_saved_items_only' ||
      readback['owner_content_complete'] != false ||
      readback['legacy_package_preserved'] != true ||
      readback['source_inventory_sha256'] != prepared.sourceInventorySha256 ||
      readback['item_count'] != prepared.itemCount ||
      copies is! List ||
      copies.length > prepared.itemCount ||
      readback['all_items_copied'] != (copies.length == prepared.itemCount)) {
    throw StateError('Inherited legacy copy readback differs');
  }
  final expected = {
    for (final source in prepared._sources) source.source.id: source,
  };
  final seen = <int>{};
  final key = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
  for (final raw in copies) {
    checkAccess();
    if (raw is! Map) throw StateError('Invalid inherited legacy copy');
    final row = Map<String, dynamic>.from(raw);
    final id = row['source_item_id'];
    final source = expected[id];
    if (id is! int ||
        source == null ||
        !seen.add(id) ||
        row['beneficiary_item_id'] is! int ||
        (row['beneficiary_item_id'] as int) <= 0 ||
        row['source_row_sha256'] != source.source.rowDigest ||
        row['title_lookup_hash'] != source.titleLookupHash) {
      throw StateError('Inherited legacy copy identity differs');
    }
    Future<String> decrypt(String field) async =>
        utf8.decode(await aesGcmUnwrap(key, _privateCiphertext(row[field])));
    final itemType = await decrypt('item_type_ciphertext');
    final title = await decrypt('service_ciphertext');
    final payload = jsonDecode(await decrypt('payload_ciphertext'));
    checkAccess();
    if (itemType != source.source.itemType ||
        title != source.title ||
        !_sameJson(payload, source.expectedPayload)) {
      throw StateError('Inherited legacy copy content differs');
    }
  }
  return seen;
}
