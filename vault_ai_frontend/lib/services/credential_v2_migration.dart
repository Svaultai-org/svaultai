import 'credential_v2.dart';
import 'credential_v2_api.dart';

typedef LocalLegacyCredentialDecrypt = Future<CredentialV2Plaintext> Function();

class CredentialV2MigrationResult {
  final CredentialV2Plaintext plaintext;
  final CredentialV2Envelope envelope;
  const CredentialV2MigrationResult(this.plaintext, this.envelope);
}

/// Explicit, item-only migration. The v2 layer never accepts a PIN; the
/// existing client-local legacy decrypt closure owns that boundary.
class CredentialV2Migrator {
  final CredentialV2Crypto crypto;
  final CredentialV2Api api;

  const CredentialV2Migrator({required this.crypto, required this.api});

  Future<CredentialV2MigrationResult> migrateOne({
    required String recordId,
    required String operationId,
    required LocalLegacyCredentialDecrypt decryptLegacyLocally,
    String? serviceForLookup,
  }) async {
    final legacy = await decryptLegacyLocally();
    final encrypted = await crypto.encrypt(
      recordId: recordId,
      plaintext: legacy,
      serviceForLookup: serviceForLookup,
    );
    await api.write(encrypted, migrationOperationId: operationId);
    final roundTripEnvelope = await api.read(recordId);
    final roundTrip = await crypto.decrypt(roundTripEnvelope);
    if (!legacy.semanticallyEquals(roundTrip)) {
      throw StateError('credential v2 semantic verification failed');
    }
    await api.verify(recordId, operationId);
    return CredentialV2MigrationResult(roundTrip, roundTripEnvelope);
  }

  Future<void> rollbackOne(String recordId) => api.rollback(recordId);
}
