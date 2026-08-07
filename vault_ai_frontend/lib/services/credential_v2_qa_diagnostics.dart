import 'credential_v2.dart';

/// Compile-time-only QA diagnostics for comparing synthetic credential
/// plaintext entirely inside the client process.
///
/// The production default is false. When disabled, expected plaintext is
/// never retained. The API deliberately returns only booleans and has no
/// persistence, logging, accessibility, network, or screenshot integration.
const bool credentialV2QaDiagnosticsEnabled = bool.fromEnvironment(
  'QA_CREDENTIAL_V2_DIAGNOSTICS',
  defaultValue: false,
);

class CredentialV2QaDiagnostics {
  CredentialV2QaDiagnostics._();

  static final Map<String, CredentialV2Plaintext> _expected = {};

  static void remember(
    String recordId,
    CredentialV2Plaintext plaintext,
  ) {
    if (!credentialV2QaDiagnosticsEnabled) return;
    _expected[recordId] = plaintext;
  }

  static bool? matches(
    String recordId,
    CredentialV2Plaintext decrypted,
  ) {
    if (!credentialV2QaDiagnosticsEnabled) return null;
    final expected = _expected[recordId];
    if (expected == null) return null;
    return expected.semanticallyEquals(decrypted);
  }

  static void forget(String recordId) {
    if (!credentialV2QaDiagnosticsEnabled) return;
    _expected.remove(recordId);
  }

  static void clear() {
    _expected.clear();
  }
}
