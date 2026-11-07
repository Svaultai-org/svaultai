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
  });

  test('older vault without OPAQUE keeps its current compatibility path', () {
    expect(
      useLocalZkPasswordAnalysis(hasZkHandle: false, hasMvk: false),
      isFalse,
    );
  });
}
