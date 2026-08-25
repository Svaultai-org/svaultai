import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/credential_lifecycle_diagnostics.dart';

void main() {
  test('diagnostic report contains only sanitized lifecycle metadata', () {
    final diag = CredentialLifecycleDiagnostics.instance;
    diag.beginSession(epoch: 7, vaultScopePresent: true);
    diag.integer('LEGACY_LOAD_HTTP_STATUS', 200);
    diag.integer('LEGACY_RECORD_COUNT', 3);
    diag.text('STALE_DROP_REASON', 'NONE');

    final report = diag.report();
    expect(report, contains('SESSION_EPOCH_AT_LOGIN=7'));
    expect(report, contains('LEGACY_RECORD_COUNT=3'));
    expect(report, isNot(contains('password')));
    expect(report, isNot(contains('ciphertext')));
    expect(report, isNot(contains('token')));
  }, skip: !credentialLifecycleDiagnosticsEnabled);

  test('free-form diagnostic values are rejected', () {
    final diag = CredentialLifecycleDiagnostics.instance;
    diag.beginSession(epoch: 8, vaultScopePresent: true);
    diag.text('STALE_DROP_REASON', 'not-an-allowed-value');
    expect(diag.report(), contains('STALE_DROP_REASON=UNKNOWN'));
  }, skip: !credentialLifecycleDiagnosticsEnabled);
}
