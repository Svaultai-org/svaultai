import 'dart:math';

const bool credentialLifecycleDiagnosticsEnabled = bool.fromEnvironment(
  'CREDENTIAL_LIFECYCLE_DIAGNOSTICS',
  defaultValue: false,
);

/// Secret-safe, in-memory credential lifecycle telemetry for diagnostic builds.
/// Values are restricted to booleans, integers, correlation IDs, HTTP status
/// codes, and allow-listed reason/state strings.
class CredentialLifecycleDiagnostics {
  CredentialLifecycleDiagnostics._();

  static final CredentialLifecycleDiagnostics instance =
      CredentialLifecycleDiagnostics._();

  static const Set<String> _allowedText = <String>{
    'NOT_STARTED',
    'STARTED',
    'COMPLETE',
    'PASS',
    'FAIL',
    'NONE',
    'LOGOUT',
    'LOGIN_START',
    'LOGIN_SUCCESS',
    'SESSION_EPOCH_CHANGE',
    'VAULT_SWITCH',
    'REPOSITORY_RECREATE',
    'LOAD_RETRY',
    'STALE_COMPLETION',
    'ERROR',
    'UNKNOWN',
    'LOADING',
    'READY_EMPTY',
    'READY_WITH_ITEMS',
  };

  final Map<String, Object> _fields = <String, Object>{};
  int _sequence = 0;
  bool _published = false;

  void beginSession({required int epoch, required bool vaultScopePresent}) {
    if (!credentialLifecycleDiagnosticsEnabled) return;
    final previousPublicationWasReset = _published;
    _fields.clear();
    _published = false;
    _sequence += 1;
    final random = Random.secure().nextInt(0x7fffffff).toRadixString(16);
    _fields['CREDENTIAL_DIAG_SESSION_ID'] = 'cd-${_sequence}_$random';
    for (final key in const <String>[
      'LEGACY_LOAD_STARTED',
      'V2_LOAD_STARTED',
      'MERGE_STARTED',
      'STALE_CHECK_PERFORMED',
      'INVENTORY_PUBLICATION_ATTEMPTED',
      'INVENTORY_PUBLICATION_SUCCEEDED',
      'POST_PUBLICATION_RESET_OCCURRED',
      'SAVE_REQUEST_STARTED',
      'AUTHORITATIVE_ROW_CONFIRMED',
      'SAVE_ACK_AFTER_CONFIRMATION',
    ]) {
      _fields[key] = false;
    }
    for (final key in const <String>[
      'SESSION_EPOCH_AT_LOAD_START',
      'SESSION_EPOCH_AT_LEGACY_COMPLETE',
      'SESSION_EPOCH_AT_V2_COMPLETE',
      'SESSION_EPOCH_AT_MERGE',
      'SESSION_EPOCH_AT_PUBLICATION',
      'SESSION_EPOCH_AT_PAGE_RENDER',
      'SESSION_EPOCH_AT_CHAT_LOOKUP',
      'LEGACY_LOAD_HTTP_STATUS',
      'LEGACY_RECORD_COUNT',
      'V2_LOAD_HTTP_STATUS',
      'V2_RECORD_COUNT',
      'MERGED_RECORD_COUNT',
      'PUBLISHED_RECORD_COUNT',
      'LOGINS_PAGE_RECORD_COUNT',
      'CHAT_LOOKUP_RECORD_COUNT',
      'SAVE_HTTP_STATUS',
      'POST_SAVE_LEGACY_COUNT',
      'POST_SAVE_V2_COUNT',
      'POST_SAVE_MERGED_COUNT',
    ]) {
      _fields[key] = key.startsWith('SESSION_EPOCH_') ? -1 : 0;
    }
    _fields['STALE_CHECK_RESULT'] = 'NOT_STARTED';
    _fields['STALE_DROP_REASON'] = 'NONE';
    _fields['LOGINS_PAGE_STATE'] = 'NOT_STARTED';
    _fields['CHAT_LOOKUP_INVENTORY_STATE'] = 'NOT_STARTED';
    _fields['POST_PUBLICATION_RESET_REASON'] = 'NONE';
    if (previousPublicationWasReset) {
      _fields['POST_PUBLICATION_RESET_OCCURRED'] = true;
      _fields['POST_PUBLICATION_RESET_REASON'] = 'SESSION_EPOCH_CHANGE';
    }
    integer('SESSION_EPOCH_AT_LOGIN', epoch);
    boolean('CURRENT_VAULT_SCOPE_PRESENT', vaultScopePresent);
    text('CREDENTIAL_STATE_RESET_REASON', 'SESSION_EPOCH_CHANGE');
  }

  void reset(String reason) {
    if (!credentialLifecycleDiagnosticsEnabled) return;
    if (_published) {
      boolean('POST_PUBLICATION_RESET_OCCURRED', true);
      text('POST_PUBLICATION_RESET_REASON', reason);
    }
    text('CREDENTIAL_STATE_RESET_REASON', reason);
  }

  void markPublished(bool value) => _published = value;

  void boolean(String key, bool value) {
    if (credentialLifecycleDiagnosticsEnabled) _fields[key] = value;
  }

  void integer(String key, int value) {
    if (credentialLifecycleDiagnosticsEnabled) _fields[key] = value;
  }

  void text(String key, String value) {
    if (!credentialLifecycleDiagnosticsEnabled) return;
    _fields[key] = _allowedText.contains(value) ? value : 'UNKNOWN';
  }

  String report() {
    if (!credentialLifecycleDiagnosticsEnabled) {
      return 'DIAGNOSTICS_DISABLED=true';
    }
    final keys = _fields.keys.toList()..sort();
    return keys.map((key) => '$key=${_fields[key]}').join('\n');
  }
}
