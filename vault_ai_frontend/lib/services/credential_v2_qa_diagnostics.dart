import 'package:flutter/foundation.dart';

import 'credential_v2.dart';

const bool credentialV2QaDiagnosticsEnabled = bool.fromEnvironment(
  'QA_CREDENTIAL_V2_DIAGNOSTICS',
  defaultValue: false,
);

class CredentialV2QaDiagnostics {
  CredentialV2QaDiagnostics._();
  static final Map<String, CredentialV2Plaintext> _expected = {};
  static void remember(String recordId, CredentialV2Plaintext plaintext) {
    if (credentialV2QaDiagnosticsEnabled) _expected[recordId] = plaintext;
  }

  static bool? matches(String recordId, CredentialV2Plaintext decrypted) {
    if (!credentialV2QaDiagnosticsEnabled) return null;
    return _expected[recordId]?.semanticallyEquals(decrypted);
  }

  static CredentialV2QaComparison? compare(
      String recordId, CredentialV2Plaintext decrypted) {
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
    if (credentialV2QaDiagnosticsEnabled) _expected.remove(recordId);
  }

  static void clear() => _expected.clear();
}

class CredentialV2QaComparison {
  final bool username, password, url, notes, totp, customFields, service;
  const CredentialV2QaComparison(
      {required this.username,
      required this.password,
      required this.url,
      required this.notes,
      required this.totp,
      required this.customFields,
      required this.service});
  bool get all =>
      username && password && url && notes && totp && customFields && service;
}

bool _mapEquals(Map<String, String> left, Map<String, String> right) {
  if (left.length != right.length) return false;
  for (final entry in left.entries) {
    if (right[entry.key] != entry.value || !right.containsKey(entry.key))
      return false;
  }
  return true;
}

const bool qaV2DiagnosticsEnabled =
    bool.fromEnvironment('QA_AUTH_DIAGNOSTICS', defaultValue: false);
const String qaV2TargetRecordId = 'generated-1d1c9d799b70b2c919d2cb558bec682f';
final ValueNotifier<String> qaV2HydrationDiagnostic = ValueNotifier<String>('');
final Map<String, String> _state = <String, String>{};
void qaV2HydrationTrace(String stage, {String? error}) {
  if (!qaV2DiagnosticsEnabled || !stage.startsWith('target_')) return;
  _state[stage] = 'true';
  if (error != null) _state['target_safe_error_category'] = error;
  for (final failed in const [
    'target_parse_exception',
    'target_decrypt_exception'
  ]) {
    if (_state.containsKey(failed))
      _state['first_failed_target_stage'] = failed;
  }
  qaV2HydrationDiagnostic.value =
      _state.entries.map((e) => '${e.key}=${e.value}').join(';');
}
