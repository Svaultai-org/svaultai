import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show shouldRotateLegacyVaultKdfAfterUnlock;

void main() {
  test('OPAQUE vault unlock never selects raw-PIN KDF rotation', () {
    expect(shouldRotateLegacyVaultKdfAfterUnlock('VLT-SYNTHETIC'), isFalse);
    expect(shouldRotateLegacyVaultKdfAfterUnlock(''), isTrue);
    expect(shouldRotateLegacyVaultKdfAfterUnlock(null), isTrue);

    final source = File('lib/main.dart').readAsStringSync();
    final verifyStart = source.indexOf('Future<bool> verifyPin(');
    final verifyEnd = source.indexOf('Future<bool> applyFreshKdfMetadata(',
        verifyStart);
    expect(verifyStart, greaterThan(-1));
    expect(verifyEnd, greaterThan(verifyStart));
    final verify = source.substring(verifyStart, verifyEnd);
    final guard = verify.indexOf(
      'if (shouldRotateLegacyVaultKdfAfterUnlock(activeVaultHandle)) {',
    );
    final rotate = verify.indexOf('await client.rotateVaultKdf(');
    expect(guard, greaterThan(-1));
    expect(rotate, greaterThan(guard));
    expect(verify.substring(guard, rotate).contains('}'), isFalse,
        reason: 'rotation must remain inside the OPAQUE-vault guard');
  });
}
