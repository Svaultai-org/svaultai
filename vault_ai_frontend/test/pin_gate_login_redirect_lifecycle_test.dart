import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('logged-out PinGate redirect is deferred beyond initState build', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('class _PinGatePageState');
    final end = source.indexOf('class VaultRecoveryPage', start);
    expect(start, greaterThanOrEqualTo(0));
    final pinGate = source.substring(start, end);
    final noToken = pinGate.substring(
      pinGate.indexOf('if (token == null)'),
      pinGate.indexOf('try {', pinGate.indexOf('if (token == null)')),
    );
    expect(noToken, contains('WidgetsBinding.instance.addPostFrameCallback'));
    expect(noToken, contains('Navigator.pushReplacementNamed'));
    expect(
      noToken.indexOf('addPostFrameCallback'),
      lessThan(noToken.indexOf('Navigator.pushReplacementNamed')),
    );
  });

  test('PinGate restores ZK session keys when unlocking after refresh', () {
    final source = File('lib/main.dart').readAsStringSync();
    final classStart = source.indexOf('class _PinGatePageState');
    final classEnd = source.indexOf('\nclass ', classStart + 1);
    final pinGate = source.substring(
      classStart,
      classEnd == -1 ? source.length : classEnd,
    );

    expect(
      pinGate,
      contains('restoreZkSessionKeys: true'),
      reason: 'refresh PIN unlock must restore MVK/SK for CredentialV2 and MemoryV2',
    );
  });
}
