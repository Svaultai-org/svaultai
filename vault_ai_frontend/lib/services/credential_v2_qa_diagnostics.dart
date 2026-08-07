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

  static CredentialV2QaComparison? compare(
    String recordId,
    CredentialV2Plaintext decrypted,
  ) {
    if (!credentialV2QaDiagnosticsEnabled) return null;
    final expected = _expected[recordId];
    if (expected == null) return null;
    return CredentialV2QaComparison(
      username: expected.username == decrypted.username,
      password: expected.password == decrypted.password,
      url: expected.url == decrypted.url,
      notes: expected.notes == decrypted.notes,
      totp: expected.totpSecret == decrypted.totpSecret,
      customFields: _mapEquals(expected.customFields, decrypted.customFields),
      service: expected.service == decrypted.service,
    );
  }

  static void forget(String recordId) {
    if (!credentialV2QaDiagnosticsEnabled) return;
    _expected.remove(recordId);
  }

  static void clear() {
    _expected.clear();
  }
}

class CredentialV2QaComparison {
  final bool username;
  final bool password;
  final bool url;
  final bool notes;
  final bool totp;
  final bool customFields;
  final bool service;

  const CredentialV2QaComparison({
    required this.username,
    required this.password,
    required this.url,
    required this.notes,
    required this.totp,
    required this.customFields,
    required this.service,
  });

  bool get all =>
      username && password && url && notes && totp && customFields && service;
}

bool _mapEquals(Map<String, String> left, Map<String, String> right) {
  if (left.length != right.length) return false;
  for (final entry in left.entries) {
    if (right[entry.key] != entry.value || !right.containsKey(entry.key)) {
      return false;
    }
  }
  return true;
}
