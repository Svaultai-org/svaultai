import 'credential_v2.dart';
import 'credential_v2_api.dart';

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

  Future<List<CredentialV2Plaintext>> exactLookup({
    required String field,
    required String value,
  }) async {
    final token = await crypto.blindIndex(field, value);
    final candidates = await api.list(
      blindIndexName: field,
      blindIndexToken: token,
    );
    final clear = <CredentialV2Plaintext>[];
    for (final candidate in candidates) {
      clear.add(await crypto.decrypt(candidate));
    }
    return clear;
  }

  Future<void> delete(String recordId) => api.delete(recordId);
}
