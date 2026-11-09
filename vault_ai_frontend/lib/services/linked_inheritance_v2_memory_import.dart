/// Explicit, bounded Memory copy after an old-link V2 readback receipt.
///
/// Owner MVK ciphertext is opened only on the beneficiary device, then
/// re-encrypted under the beneficiary MVK. No PIN or plaintext is sent.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'linked_inheritance_v2_readback_proof.dart';
import 'linked_inheritance_v2_release_readback.dart';
import 'vault_key_hierarchy.dart';
import 'zk_proof_token_guard.dart';

typedef FetchLinkedMemoryExport =
    Future<Map<String, dynamic>> Function(int linkId);
typedef WriteLinkedMemoryCopy =
    Future<Map<String, dynamic>> Function(Map<String, dynamic> body);
typedef ReadbackLinkedMemoryCopies =
    Future<Map<String, dynamic>> Function(int linkId, String inventoryDigest);

const _maxMemories = 100;
const _maxSourceBytes = 1024 * 1024;
const _maxRowBytes = 128 * 1024;
final _digestPattern = RegExp(r'^[A-Za-z0-9_-]{43}$');

class LinkedV2MemoryImport {
  final int memoryCount;
  final int newMemories;
  final String sourceInventorySha256;

  const LinkedV2MemoryImport({
    required this.memoryCount,
    required this.newMemories,
    required this.sourceInventorySha256,
  });
}

class _SourceMemory {
  final int id;
  final String rowDigest;
  final String type;
  final String title;
  final String plaintext;

  const _SourceMemory({
    required this.id,
    required this.rowDigest,
    required this.type,
    required this.title,
    required this.plaintext,
  });
}

String _b64(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

Uint8List _ciphertext(Object? value) {
  if (value is! String || !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(value)) {
    throw const FormatException('Invalid inherited Memory ciphertext');
  }
  final bytes = Uint8List.fromList(
    base64Url.decode(base64Url.normalize(value)),
  );
  if (bytes.length < 29 ||
      bytes.length > _maxRowBytes ||
      bytes[0] != 1 ||
      _b64(bytes) != value) {
    throw const FormatException('Invalid inherited Memory ciphertext');
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

Future<String> _rowHash({
  required int id,
  required String type,
  required String recordId,
  required String snapshot,
  required Uint8List payload,
}) async {
  final data = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-memory-source/v1\u0000'));
  for (final value in <Object>[id, type, recordId, snapshot, payload]) {
    _feed(data, value);
  }
  return _hash(data);
}

Future<({List<_SourceMemory> memories, String digest})> _sourceMemories({
  required Map<String, dynamic> exported,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
}) async {
  final rawMemories = exported['memories'];
  final count = exported['memory_count'];
  final total = exported['ciphertext_bytes'];
  final claimedDigest = exported['source_inventory_sha256'];
  if (exported['beneficiary_link_id'] != released.linkId ||
      exported['owner_vault_id'] != released.ownerVaultId ||
      exported['beneficiary_vault_id'] != beneficiaryVaultId ||
      exported['stage_revision'] != released.stageRevision ||
      exported['offer_commitment'] != released.offerCommitment ||
      exported['content_scope'] != 'memory_only' ||
      exported['owner_content_complete'] != false ||
      count is! int ||
      count < 0 ||
      count > _maxMemories ||
      total is! int ||
      total < 0 ||
      total > _maxSourceBytes ||
      rawMemories is! List ||
      rawMemories.length != count ||
      claimedDigest is! String ||
      !_digestPattern.hasMatch(claimedDigest)) {
    throw const FormatException('Invalid inherited Memory inventory');
  }
  final inventory = BytesBuilder()
    ..add(utf8.encode('linked-old-v2-memory-inventory/v1\u0000'));
  for (final value in <Object>[
    released.linkId,
    released.ownerVaultId,
    beneficiaryVaultId,
    released.stageRevision,
  ]) {
    _feed(inventory, value);
  }
  final ownerKey = await VaultKeyHierarchy(released.ownerMvk).memoryKey();
  final parsed = <_SourceMemory>[];
  final titles = <String>{};
  var summed = 0;
  var previousId = 0;
  for (final raw in rawMemories) {
    if (raw is! Map) {
      throw const FormatException('Invalid inherited Memory inventory');
    }
    final row = Map<String, dynamic>.from(raw);
    final id = row['memory_id'];
    final type = row['memory_type'];
    final recordId = row['memory_record_id'];
    final snapshot = row['source_snapshot'];
    final rowDigest = row['source_row_sha256'];
    if (id is! int ||
        id <= previousId ||
        type is! String ||
        type.isEmpty ||
        type.length > 64 ||
        recordId is! String ||
        recordId.isEmpty ||
        recordId.length > 128 ||
        snapshot is! String || !_digestPattern.hasMatch(snapshot) ||
        rowDigest is! String ||
        !_digestPattern.hasMatch(rowDigest)) {
      throw const FormatException('Invalid inherited Memory identity');
    }
    previousId = id;
    final ciphertext = _ciphertext(row['payload_ciphertext']);
    summed += ciphertext.length;
    if (summed > _maxSourceBytes) {
      throw const FormatException('Inherited Memory inventory too large');
    }
    final calculated = await _rowHash(
      id: id,
      type: type,
      recordId: recordId,
      snapshot: snapshot,
      payload: ciphertext,
    );
    if (rowDigest != calculated) {
      throw const FormatException('Inherited Memory source hash differs');
    }
    _feed(inventory, id);
    _feed(inventory, b64urlDecode(rowDigest));
    final plaintext = utf8.decode(await aesGcmUnwrap(ownerKey, ciphertext));
    final decoded = jsonDecode(plaintext);
    if (decoded is! Map ||
        (decoded['memory_type'] != null && decoded['memory_type'] != type)) {
      throw const FormatException('Invalid inherited Memory payload');
    }
    final title = decoded['title'] ?? decoded['memory_key'];
    if (title is! String ||
        title.trim().isEmpty ||
        !titles.add(title.trim().toLowerCase())) {
      throw const FormatException('Inherited Memory title is unavailable');
    }
    parsed.add(
      _SourceMemory(
        id: id,
        rowDigest: rowDigest,
        type: type,
        title: title,
        plaintext: plaintext,
      ),
    );
  }
  if (summed != total || await _hash(inventory) != claimedDigest) {
    throw const FormatException('Inherited Memory inventory hash differs');
  }
  return (memories: parsed, digest: claimedDigest);
}

Future<String> _lookupHash(SecretKey lookupKey, _SourceMemory source) async =>
    _b64(
      await keyedLookupHash(
        lookupKey,
        utf8.encode(source.title.trim().toLowerCase()),
      ),
    );

Future<Set<int>> _verifiedCopies({
  required Map<String, dynamic> readback,
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
  required String digest,
  required List<_SourceMemory> sources,
  required SecretKey beneficiaryMvk,
}) async {
  final rows = readback['copies'];
  if (readback['beneficiary_link_id'] != released.linkId ||
      readback['owner_vault_id'] != released.ownerVaultId ||
      readback['beneficiary_vault_id'] != beneficiaryVaultId ||
      readback['stage_revision'] != released.stageRevision ||
      readback['offer_commitment'] != released.offerCommitment ||
      readback['content_scope'] != 'memory_only' ||
      readback['owner_content_complete'] != false ||
      readback['source_inventory_sha256'] != digest ||
      readback['memory_count'] != sources.length ||
      readback['legacy_package_preserved'] != true ||
      rows is! List ||
      rows.length > sources.length ||
      readback['all_memories_copied'] != (rows.length == sources.length)) {
    throw StateError('Inherited Memory copy readback differs');
  }
  final expected = {for (final source in sources) source.id: source};
  final seen = <int>{};
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final memoryKey = await hierarchy.memoryKey();
  final lookupKey = await hierarchy.memoryLookupKey();
  for (final raw in rows) {
    if (raw is! Map) throw StateError('Invalid inherited Memory copy');
    final row = Map<String, dynamic>.from(raw);
    final id = row['source_memory_id'];
    final source = expected[id];
    if (id is! int ||
        source == null ||
        !seen.add(id) ||
        row['beneficiary_memory_id'] is! int ||
        (row['beneficiary_memory_id'] as int) <= 0 ||
        row['beneficiary_memory_record_id'] !=
            'inherited-${released.linkId}-$id' ||
        row['memory_type'] != source.type ||
        row['source_row_sha256'] != source.rowDigest ||
        row['memory_lookup_hash'] != await _lookupHash(lookupKey, source)) {
      throw StateError('Inherited Memory copy identity differs');
    }
    final clear = utf8.decode(
      await aesGcmUnwrap(memoryKey, _ciphertext(row['payload_ciphertext'])),
    );
    if (clear != source.plaintext) {
      throw StateError('Inherited Memory copy content differs');
    }
  }
  return seen;
}

Future<LinkedV2MemoryImport> importLinkedV2Memories({
  required ReleasedLinkedInheritanceV2 released,
  required LinkedReadbackReceipt readbackReceipt,
  required String beneficiaryVaultId,
  required SecretKey beneficiaryMvk,
  required FetchLinkedMemoryExport fetchExport,
  required WriteLinkedMemoryCopy copyMemory,
  required ReadbackLinkedMemoryCopies readbackCopies,
  required Future<String> Function() freshZkProof,
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
  final source = await _sourceMemories(
    exported: exported,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  checkAccess();
  final prior = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final copied = await _verifiedCopies(
    readback: prior,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    sources: source.memories,
    beneficiaryMvk: beneficiaryMvk,
  );
  final hierarchy = VaultKeyHierarchy(beneficiaryMvk);
  final memoryKey = await hierarchy.memoryKey();
  final lookupKey = await hierarchy.memoryLookupKey();
  var newMemories = 0;
  for (final memory in source.memories) {
    checkAccess();
    if (copied.contains(memory.id)) continue;
    final ciphertext = await aesGcmWrap(
      memoryKey,
      utf8.encode(memory.plaintext),
    );
    final lookup = await _lookupHash(lookupKey, memory);
    checkAccess();
    final proof = rejectPinShapedZkProof(await freshZkProof());
    checkAccess();
    final result = await copyMemory({
      'beneficiary_link_id': released.linkId,
      'source_memory_id': memory.id,
      'stage_revision': released.stageRevision,
      'offer_commitment': released.offerCommitment,
      'source_inventory_sha256': source.digest,
      'source_row_sha256': memory.rowDigest,
      'beneficiary_memory_record_id':
          'inherited-${released.linkId}-${memory.id}',
      'memory_type': memory.type,
      'memory_lookup_hash': lookup,
      'payload_ciphertext': _b64(ciphertext),
      'content_scope': 'memory_only',
      'zk_proof_token': proof,
    });
    checkAccess();
    if (result['beneficiary_link_id'] != released.linkId ||
        result['source_memory_id'] != memory.id ||
        result['beneficiary_memory_id'] is! int ||
        result['source_inventory_sha256'] != source.digest ||
        result['legacy_package_preserved'] != true ||
        result['created'] is! bool) {
      throw StateError('Inherited Memory copy was not confirmed');
    }
    if (result['created'] == true) newMemories++;
    copied.add(memory.id);
  }
  checkAccess();
  final finalReadback = await readbackCopies(released.linkId, source.digest);
  checkAccess();
  final finalIds = await _verifiedCopies(
    readback: finalReadback,
    released: released,
    beneficiaryVaultId: beneficiaryVaultId,
    digest: source.digest,
    sources: source.memories,
    beneficiaryMvk: beneficiaryMvk,
  );
  if (finalIds.length != source.memories.length ||
      finalReadback['all_memories_copied'] != true) {
    throw StateError('Inherited Memory copy is incomplete');
  }
  return LinkedV2MemoryImport(
    memoryCount: source.memories.length,
    newMemories: newMemories,
    sourceInventorySha256: source.digest,
  );
}
