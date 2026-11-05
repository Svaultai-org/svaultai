import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart';

void main() {
  test('stage trace accepts only short closed-set event codes', () {
    expect(kEnableLegacyStageDiagnostics, isFalse);
    for (final code in LegacyStageDiagnosticCode.values) {
      final message = legacyStageDiagnosticMessage(code);
      expect(message, matches(RegExp(r'^\[zk-stage-diag\] [a-zA-Z]+$')));
      expect(message.length, lessThan(80));
      for (final forbidden in <String>[
        '123456',
        'Bearer',
        'VLT-',
        'vault_id=',
        'ciphertext',
      ]) {
        expect(message, isNot(contains(forbidden)));
      }
    }
  });
}
