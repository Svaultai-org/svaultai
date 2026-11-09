import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/security_center_page.dart';

void main() {
  test('OPAQUE vault selects local analysis without an optional flag', () {
    expect(
      useLocalZkPasswordAnalysis(hasZkHandle: true, hasMvk: true),
      isTrue,
    );
    // A lost key must fail in the local analyzer, never fall through to the
    // older server analyzer that takes a raw PIN.
    expect(
      useLocalZkPasswordAnalysis(hasZkHandle: true, hasMvk: false),
      isTrue,
    );
    // A private key without a recovered handle must also stay out of the
    // server analyzer. The local path can report that the vault is locked.
    expect(
      useLocalZkPasswordAnalysis(hasZkHandle: false, hasMvk: true),
      isTrue,
    );
  });

  test('older vault without OPAQUE keeps its current compatibility path', () {
    expect(
      useLocalZkPasswordAnalysis(hasZkHandle: false, hasMvk: false),
      isFalse,
    );
  });

  test('signed local analyzer offer cannot fall back after local key loss', () {
    expect(
      useLocalZkPasswordAnalysis(
        hasZkHandle: false,
        hasMvk: false,
        signedPasswordAnalysisOffered: true,
      ),
      isTrue,
    );
  });

  test('strict transport blocks legacy-only analysis before PIN entry', () {
    expect(
      legacyPasswordAnalysisNeedsPrivateUpgrade(
        localAnalysisAvailable: false,
        pinTransportRejected: true,
      ),
      isTrue,
    );
    expect(
      legacyPasswordAnalysisNeedsPrivateUpgrade(
        localAnalysisAvailable: true,
        pinTransportRejected: true,
      ),
      isFalse,
    );
    // Existing legacy-only sessions keep compatibility in ordinary builds.
    expect(
      legacyPasswordAnalysisNeedsPrivateUpgrade(
        localAnalysisAvailable: false,
        pinTransportRejected: false,
      ),
      isFalse,
    );
  });

  test('strict UI guard precedes the legacy PIN prompt', () async {
    final source = await File('lib/security_center_page.dart').readAsString();
    final start = source.indexOf('Future<void> _runAnalyzePasswords()');
    final end = source.indexOf('Future<void> _runLocalZkAnalyzePasswords()', start);
    expect(start, isNonNegative);
    expect(end, greaterThan(start));
    final body = source.substring(start, end);
    final guard = body.indexOf('if (_legacyAnalysisNeedsPrivateUpgrade) return;');
    final prompt = body.indexOf('_promptVaultAndPin()');
    expect(guard, isNonNegative);
    expect(prompt, isNonNegative);
    expect(guard, lessThan(prompt));
    expect(source, contains('legacy_password_analysis_upgrade_required'));
    expect(source, contains('This older check sends your vault PIN'));
    expect(source, isNot(contains('Passwords are never '
        'shown or stored on the server.')));
  });
}
