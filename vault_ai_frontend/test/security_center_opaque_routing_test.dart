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
}
