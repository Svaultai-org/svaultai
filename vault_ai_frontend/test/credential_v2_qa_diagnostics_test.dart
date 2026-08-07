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

  test('QA component diagnostics expose booleans only', () {
    CredentialV2QaDiagnostics.remember('record', plaintext);
    final comparison = CredentialV2QaDiagnostics.compare(
      'record',
      const CredentialV2Plaintext(
        service: 'Synthetic QA',
        username: 'different-user',
        password: 'synthetic-password',
      ),
    );
    if (credentialV2QaDiagnosticsEnabled) {
      expect(comparison, isNotNull);
      expect(comparison!.username, isFalse);
      expect(comparison.password, isTrue);
      expect(comparison.url, isTrue);
      expect(comparison.notes, isTrue);
      expect(comparison.totp, isTrue);
      expect(comparison.customFields, isTrue);
      expect(comparison.service, isTrue);
      expect(comparison.all, isFalse);
    } else {
      expect(comparison, isNull);
    }
    CredentialV2QaDiagnostics.clear();
  });
}
