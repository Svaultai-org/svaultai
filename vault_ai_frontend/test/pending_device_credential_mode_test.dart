import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/device_pending_page.dart';

void main() {
  PendingDeviceCredentialMode mode({
    bool proofFlagEnabled = false,
    bool proofOffered = false,
    bool privateOnly = false,
    bool legacyFallbackEnabled = false,
    bool hasVaultHandle = false,
  }) =>
      pendingDeviceCredentialMode(
        proofFlagEnabled: proofFlagEnabled,
        proofOffered: proofOffered,
        privateOnly: privateOnly,
        legacyFallbackEnabled: legacyFallbackEnabled,
        hasVaultHandle: hasVaultHandle,
      );

  test('signed OPAQUE offer uses local proof even without global flag', () {
    expect(mode(proofOffered: true, hasVaultHandle: true),
        PendingDeviceCredentialMode.opaqueProof);
  });

  test('OPAQUE handle never falls back to raw PIN', () {
    expect(mode(hasVaultHandle: true, legacyFallbackEnabled: true),
        PendingDeviceCredentialMode.unavailable);
    expect(mode(proofOffered: true, legacyFallbackEnabled: true),
        PendingDeviceCredentialMode.unavailable);
  });

  test('legacy PIN path requires explicit fallback and no OPAQUE handle', () {
    expect(mode(legacyFallbackEnabled: true),
        PendingDeviceCredentialMode.legacyPin);
    expect(mode(), PendingDeviceCredentialMode.unavailable);
    expect(mode(privateOnly: true, legacyFallbackEnabled: true),
        PendingDeviceCredentialMode.unavailable);
  });
}
