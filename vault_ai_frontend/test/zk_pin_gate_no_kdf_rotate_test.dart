import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show shouldRefreshLegacyVaultKdfAfterUnlock;

void main() {
  test('OPAQUE unlock skips legacy KDF refresh and never rotates with PIN', () {
    expect(shouldRefreshLegacyVaultKdfAfterUnlock('VLT-SYNTHETIC'), isFalse);
    expect(shouldRefreshLegacyVaultKdfAfterUnlock(''), isTrue);
    expect(shouldRefreshLegacyVaultKdfAfterUnlock(null), isTrue);

    final source = File('lib/main.dart').readAsStringSync();
    final verifyStart = source.indexOf('Future<bool> verifyPin(');
    final verifyEnd = source.indexOf('Future<bool> applyFreshKdfMetadata(',
        verifyStart);
    expect(verifyStart, greaterThan(-1));
    expect(verifyEnd, greaterThan(verifyStart));
    final verify = source.substring(verifyStart, verifyEnd);
    final guard = verify.indexOf(
      'if (shouldRefreshLegacyVaultKdfAfterUnlock(activeVaultHandle)) {',
    );
    final refresh = verify.indexOf('final freshMeta = await _API.getVaultMeta(');
    expect(guard, greaterThan(-1));
    expect(refresh, greaterThan(guard));
    expect(verify, isNot(contains('rotateVaultKdf(')));
  });
}
