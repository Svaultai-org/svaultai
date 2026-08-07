import 'credential_v2.dart';
import 'credential_v2_api.dart';

class CredentialV2LookupIntent {
  final bool listAll;
  final String? service;
  const CredentialV2LookupIntent._({required this.listAll, this.service});
}

CredentialV2LookupIntent? parseCredentialV2LookupIntent(String text) {
  final normalized = text.trim();
  if (RegExp(
    r'^(?:show|list|open)\s+(?:me\s+)?(?:my\s+)?saved\s+logins?\??$',
    caseSensitive: false,
  ).hasMatch(normalized)) {
    return const CredentialV2LookupIntent._(listAll: true);
  }
  final match = RegExp(
    r'^(?:show|find|open|get)\s+(?:me\s+)?(?:my\s+)?(.+?)\s+(?:saved\s+)?login\??$',
    caseSensitive: false,
  ).firstMatch(normalized);
  final service = match?.group(1)?.trim();
  if (service == null || service.isEmpty) return null;
  return CredentialV2LookupIntent._(listAll: false, service: service);
}

class DecryptedCredentialV2Record {
  final String recordId;
  final CredentialV2Plaintext plaintext;
  const DecryptedCredentialV2Record(this.recordId, this.plaintext);
}

class CredentialV2Repository {
  final CredentialV2Crypto crypto;
  final CredentialV2Api api;

  const CredentialV2Repository({required this.crypto, required this.api});

  Future<void> create({
    required String recordId,
    required CredentialV2Plaintext credential,
    String? serviceForLookup,
  }) async {
    final envelope = await crypto.encrypt(
      recordId: recordId,
      plaintext: credential,
      serviceForLookup: serviceForLookup,
    );
    await api.write(envelope);
  }

  Future<CredentialV2Plaintext> reveal(String recordId) async =>
      crypto.decrypt(await api.read(recordId));

  Future<void> edit({
    required String recordId,
    required CredentialV2Plaintext credential,
    String? serviceForLookup,
  }) =>
      create(
        recordId: recordId,
        credential: credential,
        serviceForLookup: serviceForLookup,
      );

  Future<List<String>> listRecordIds({
    String? blindIndexName,
    String? blindIndexToken,
  }) async =>
      (await api.list(
        blindIndexName: blindIndexName,
        blindIndexToken: blindIndexToken,
      ))
          .map((envelope) => envelope.recordId)
          .toList(growable: false);

  Future<List<DecryptedCredentialV2Record>> listDecrypted() async {
    final envelopes = await api.list();
    final records = <DecryptedCredentialV2Record>[];
    for (final envelope in envelopes) {
      records.add(DecryptedCredentialV2Record(
        envelope.recordId,
        await crypto.decrypt(envelope),
      ));
    }
    return records;
  }

  Future<List<DecryptedCredentialV2Record>> exactLookup({
    required String field,
    required String value,
  }) async {
    final token = await crypto.blindIndex(field, value);
    final candidates = await api.list(
      blindIndexName: field,
      blindIndexToken: token,
    );
    final clear = <DecryptedCredentialV2Record>[];
    for (final candidate in candidates) {
      clear.add(DecryptedCredentialV2Record(
        candidate.recordId,
        await crypto.decrypt(candidate),
      ));
    }
    return clear;
  }

  Future<void> delete(String recordId) => api.delete(recordId);
}
