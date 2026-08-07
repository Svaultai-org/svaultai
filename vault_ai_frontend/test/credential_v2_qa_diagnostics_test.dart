import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_qa_diagnostics.dart';

void main() {
  const plaintext = CredentialV2Plaintext(
    service: 'Synthetic QA',
    username: 'synthetic-user',
    password: 'synthetic-password',
  );

  test('QA equality diagnostics obey their compile-time gate', () {
    CredentialV2QaDiagnostics.remember('record', plaintext);
    if (credentialV2QaDiagnosticsEnabled) {
      expect(CredentialV2QaDiagnostics.matches('record', plaintext), isTrue);
    } else {
      expect(CredentialV2QaDiagnostics.matches('record', plaintext), isNull);
    }
    CredentialV2QaDiagnostics.clear();
    expect(CredentialV2QaDiagnostics.matches('record', plaintext), isNull);
  });

  test('QA diagnostics API exposes no plaintext-returning operation', () {
    final source = CredentialV2QaDiagnostics.matches('missing', plaintext);
    expect(source, isNull);
  });
}
