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
    final active = mvk_store.ZkActiveMvk.current();
    if (active == null) throw StateError('memory_v2_mvk_unavailable');
    final key = await keys.VaultKeyHierarchy(active).memoryLookupKey();
    final token = await keys.keyedLookupHash(
        key, utf8.encode(query.trim().toLowerCase()));
    return keys.b64urlEncode(token);
  }

  Future<void> create(
      {required String memoryId,
      required String memoryType,
      required MemoryV2Plaintext plaintext}) async {
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=repository_create_entered');
    final envelope = await keys.aesGcmWrapWithAad(
        await _recordKey(memoryId), utf8.encode(jsonEncode(plaintext.toJson())),
        aad: _aad(memoryId));
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=encryption_succeeded');
    await client.writeZkMemoryEnvelope(
      baseUrl: baseUrl,
      authToken: authToken,
      memoryId: memoryId,
      memoryType: memoryType,
      payloadCiphertext: keys.b64urlEncode(envelope),
      lookupHash: await _lookup(plaintext.normalized ?? plaintext.value),
    );
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=api_write_status_ok');
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
    for (final row in rows) {
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
    }
    if (_qaDiagnostics) print('QA_MEMORY_STAGE=list_decrypt_succeeded');
    return out;
  }

  Future<void> delete(String memoryId) => client.deleteZkMemoryEnvelope(
      baseUrl: baseUrl, authToken: authToken, memoryId: memoryId);
}
