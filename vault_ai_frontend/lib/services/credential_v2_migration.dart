import 'credential_v2.dart';
import 'credential_v2_api.dart';

typedef LocalLegacyCredentialDecrypt = Future<CredentialV2Plaintext> Function();
typedef CredentialV2MigrationStageCallback = void Function(String stage);

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
    CredentialV2MigrationStageCallback? onStage,
  }) async {
    final legacy = await decryptLegacyLocally();
    onStage?.call('legacy_decrypted');
    final encrypted = await crypto.encrypt(
      recordId: recordId,
      plaintext: legacy,
      serviceForLookup: serviceForLookup,
    );
    onStage?.call('encrypted');
    await api.write(encrypted, migrationOperationId: operationId);
    onStage?.call('put_complete');
    final roundTripEnvelope = await api.read(recordId);
    onStage?.call('readback_complete');
    final roundTrip = await crypto.decrypt(roundTripEnvelope);
    if (!legacy.semanticallyEquals(roundTrip)) {
      await api.verify(
        recordId,
        operationId,
        semanticEqualityVerified: false,
      );
      throw StateError('credential v2 semantic verification failed');
    }
    onStage?.call('local_verified');
    await api.verify(recordId, operationId);
    onStage?.call('verify_complete');
    return CredentialV2MigrationResult(roundTrip, roundTripEnvelope);
  }

  Future<void> rollbackOne(String recordId) => api.rollback(recordId);
}
