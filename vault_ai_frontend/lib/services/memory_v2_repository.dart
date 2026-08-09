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
    final envelope = await keys.aesGcmWrapWithAad(
        await _recordKey(memoryId), utf8.encode(jsonEncode(plaintext.toJson())),
        aad: _aad(memoryId));
    await client.writeZkMemoryEnvelope(
      baseUrl: baseUrl,
      authToken: authToken,
      memoryId: memoryId,
      memoryType: memoryType,
      payloadCiphertext: keys.b64urlEncode(envelope),
      lookupHash: await _lookup(plaintext.normalized ?? plaintext.value),
    );
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

  Future<void> delete(String memoryId) => client.deleteZkMemoryEnvelope(
      baseUrl: baseUrl, authToken: authToken, memoryId: memoryId);
}
