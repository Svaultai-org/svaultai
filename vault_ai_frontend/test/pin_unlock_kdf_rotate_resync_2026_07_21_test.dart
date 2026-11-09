// The client must never submit an unlock PIN for automatic KDF rotation.
// Older clients can still rotate a legacy-only vault's salt. A second
// PIN-free metadata fetch keeps this client aligned with that generation.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('legacy unlock refreshes authoritative KDF metadata without rotation',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    final verifyStart = source.indexOf('Future<bool> verifyPin(');
    final verifyEnd = source.indexOf('Future<bool> applyFreshKdfMetadata(',
        verifyStart);
    expect(verifyStart, greaterThan(-1));
    expect(verifyEnd, greaterThan(verifyStart));
    final verify = source.substring(verifyStart, verifyEnd);
    expect(verify, isNot(contains('rotateVaultKdf(')));
    expect(verify, isNot(contains("'pin': pin")));
    final guard = verify.indexOf(
      'if (shouldRefreshLegacyVaultKdfAfterUnlock(activeVaultHandle)) {',
    );
    final metadata = verify.indexOf('final freshMeta = await _API.getVaultMeta(',
        guard);
    final rederive = verify.indexOf('source: \'verify_pin.refresh_kdf\'',
        metadata);
    expect(guard, greaterThan(-1));
    expect(metadata, greaterThan(guard));
    expect(rederive, greaterThan(metadata));
  });
}
