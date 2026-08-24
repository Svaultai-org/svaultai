import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../api_client.dart';
import 'vault_key_hierarchy.dart' as keys;
import 'zk_active_mvk.dart' as mvk_store;

class MemoryV2Plaintext {
  final String value;
  final String? normalized;
  final String? summary;
  final List<String> tags;

  const MemoryV2Plaintext(
      {required this.value,
      this.normalized,
      this.summary,
      this.tags = const []});

  Map<String, dynamic> toJson() => {
        'value': value,
        if (normalized != null) 'normalized': normalized,
        if (summary != null) 'summary': summary,
        if (tags.isNotEmpty) 'tags': tags,
      };

  factory MemoryV2Plaintext.fromJson(Map<String, dynamic> json) =>
      MemoryV2Plaintext(
        value: json['value'] as String,
        normalized: json['normalized'] as String?,
        summary: json['summary'] as String?,
        tags: (json['tags'] as List? ?? const [])
            .whereType<String>()
            .toList(growable: false),
      );
}

class MemoryV2WriteResult {
  final String memoryId;
  final bool duplicate;
  final int? supersededId;

  const MemoryV2WriteResult({
    required this.memoryId,
    required this.duplicate,
    this.supersededId,
  });
}

class MemoryV2Repository {
  static const _qaDiagnostics =
      bool.fromEnvironment('QA_CHAT_PRIVACY_DIAGNOSTICS', defaultValue: false);
  final String baseUrl;
  final String authToken;
  final VaultAIClient client;

  MemoryV2Repository({required this.baseUrl, required this.authToken})
      : client = VaultAIClient(baseUrl: baseUrl);

  Future<SecretKey> _recordKey(String memoryId) async {
    final active = mvk_store.ZkActiveMvk.current();
    if (active == null) throw StateError('memory_v2_mvk_unavailable');
    final domain = await keys.VaultKeyHierarchy(active).memoryKey();
    final raw = await domain.extractBytes();
    final hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
    return hkdf.deriveKey(
        secretKey: SecretKey(raw),
        nonce: utf8.encode(memoryId),
        info: utf8.encode('vaultai.memory.record.v2'));
  }

  List<int> _aad(String memoryId) =>
      utf8.encode('svaultai|client_mvk_v2|memory|$memoryId');

  Future<String> _lookup(String query) async {
    try {
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=normalization_entered');
      final normalized = query.trim().toLowerCase();
      if (_qaDiagnostics)
        print('QA_MEMORY_LOOKUP_STAGE=normalization_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=mvk_fetch_entered');
      final active = mvk_store.ZkActiveMvk.current();
      if (active == null) throw StateError('memory_v2_mvk_unavailable');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=mvk_fetch_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=hkdf_entered');
      final key = await keys.VaultKeyHierarchy(active).memoryLookupKey();
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=hkdf_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=hmac_entered');
      final token = await keys.keyedLookupHash(key, utf8.encode(normalized));
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=hmac_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=base64_entered');
      final encoded = keys.b64urlEncode(token);
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=base64_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_LOOKUP_STAGE=returned');
      return encoded;
    } catch (e) {
      if (_qaDiagnostics) {
        print('QA_MEMORY_LOOKUP_EXCEPTION_TYPE=${e.runtimeType}');
      }
      rethrow;
    }
  }

  Future<String> _newRecordId(
    String memoryType,
    MemoryV2Plaintext plaintext,
  ) async {
    final active = mvk_store.ZkActiveMvk.current();
    if (active == null) throw StateError('memory_v2_mvk_unavailable');
    final key = await keys.VaultKeyHierarchy(active).memoryLookupKey();
    final canonical = <String>[
      'memory-record-v2',
      memoryType.trim().toLowerCase(),
      (plaintext.normalized ?? plaintext.value).trim().toLowerCase(),
      plaintext.value.trim().toLowerCase(),
    ].join('\u0000');
    final digest = await keys.keyedLookupHash(key, utf8.encode(canonical));
    return 'memory-${keys.b64urlEncode(digest)}';
  }

  Future<MemoryV2WriteResult> create(
      {String? memoryId,
      required String memoryType,
      required MemoryV2Plaintext plaintext}) async {
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=repository_create_entered');
    final resolvedMemoryId =
        memoryId ?? await _newRecordId(memoryType, plaintext);
    final envelope = await keys.aesGcmWrapWithAad(
        await _recordKey(resolvedMemoryId),
        utf8.encode(jsonEncode(plaintext.toJson())),
        aad: _aad(resolvedMemoryId));
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=encryption_succeeded');
    try {
      final lookupHash = await _lookup(plaintext.normalized ?? plaintext.value);
      if (_qaDiagnostics) print('QA_MEMORY_STAGE=blind_index_created');
      final requestMemoryId = resolvedMemoryId;
      final requestMemoryType = memoryType;
      if (_qaDiagnostics) print('QA_MEMORY_REQUEST_STAGE=fields_ready');
      if (_qaDiagnostics)
        print('QA_MEMORY_REQUEST_STAGE=envelope_encoding_entered');
      final encodedEnvelope = keys.b64urlEncode(envelope);
      if (_qaDiagnostics)
        print('QA_MEMORY_REQUEST_STAGE=envelope_encoding_succeeded');
      if (_qaDiagnostics) print('QA_MEMORY_REQUEST_STAGE=lookup_hash_ready');
      final response = await client.writeZkMemoryEnvelope(
        baseUrl: baseUrl,
        authToken: authToken,
        memoryId: requestMemoryId,
        memoryType: requestMemoryType,
        payloadCiphertext: encodedEnvelope,
        lookupHash: lookupHash,
        replaceExisting: memoryId != null,
      );
      if (_qaDiagnostics) print('QA_MEMORY_STAGE=api_write_status_ok');
      return MemoryV2WriteResult(
        memoryId: resolvedMemoryId,
        duplicate: response['duplicate'] == true,
        supersededId: (response['superseded_id'] as num?)?.toInt(),
      );
    } catch (e, st) {
      if (_qaDiagnostics) {
        print('QA_MEMORY_WRITE_EXCEPTION_TYPE=${e.runtimeType}');
        final topFrame = st.toString().split('\n').first.trim();
        print('QA_MEMORY_WRITE_EXCEPTION_TOP_FRAME=$topFrame');
      }
      rethrow;
    }
  }

  Future<List<MemoryV2Plaintext>> exactRecall(String query) async {
    final rows = await client.listZkMemoryEnvelopes(
        baseUrl: baseUrl,
        authToken: authToken,
        lookupHash: await _lookup(query));
    final out = <MemoryV2Plaintext>[];
    for (final row in rows) {
      final id = row['memory_id'].toString();
      final raw = keys.b64urlDecode(row['payload_ciphertext'] as String);
      final clear = await keys.aesGcmUnwrapWithAad(
          await _recordKey(id), Uint8List.fromList(raw),
          aad: _aad(id));
      out.add(MemoryV2Plaintext.fromJson(
          jsonDecode(utf8.decode(clear)) as Map<String, dynamic>));
    }
    return out;
  }

  Future<List<Map<String, dynamic>>> listDecrypted() async {
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=list_entered');
    final rows = await client.listZkMemoryEnvelopes(
        baseUrl: baseUrl, authToken: authToken);
    if (_qaDiagnostics) print('QA_MEMORY_RAW_COUNT=${rows.length}');
    final out = <Map<String, dynamic>>[];
    var rejected = 0;
    for (final row in rows) {
      try {
        final id = row['memory_id'].toString();
        final clear = await keys.aesGcmUnwrapWithAad(
          await _recordKey(id),
          Uint8List.fromList(
              keys.b64urlDecode(row['payload_ciphertext'] as String)),
          aad: _aad(id),
        );
        final payload = MemoryV2Plaintext.fromJson(
            jsonDecode(utf8.decode(clear)) as Map<String, dynamic>);
        out.add({
          'id': id,
          'memory_record_id': id,
          'memory_type': row['memory_type'],
          'title': payload.normalized ?? '',
          'value': payload.value,
          'tags': payload.tags
        });
      } catch (_) {
        rejected++;
      }
    }
    if (_qaDiagnostics) print('QA_MEMORY_REJECTED_COUNT=$rejected');
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=list_decrypt_succeeded');
    return out;
  }

  Future<void> delete(String memoryId) => client.deleteZkMemoryEnvelope(
      baseUrl: baseUrl, authToken: authToken, memoryId: memoryId);
}
