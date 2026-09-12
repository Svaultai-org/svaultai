import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('saved logins force a fresh read after an active inventory request', () {
    final source = File('lib/main.dart').readAsStringSync();
    final helperStart =
        source.indexOf('Future<void> _reloadVaultLoginsAfterMutation()');
    final helperEnd = source.indexOf(
      'Future<void> _loadVaultLoginsOnce()',
      helperStart,
    );

    expect(helperStart, greaterThanOrEqualTo(0));
    expect(helperEnd, greaterThan(helperStart));
    final helper = source.substring(helperStart, helperEnd);
    expect(helper, contains('final active = _vaultLoginsLoadFuture'));
    expect(helper, contains('if (active != null) await active'));
    expect(helper, contains('await _loadVaultLogins()'));
    expect(source, contains('await _reloadVaultLoginsAfterMutation();'));
  });

  test('inventory responses stay bound to their original login session', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('app.sessionToken != requestToken'));
    expect(source, contains('app.vaultName != requestVaultName'));
    expect(source, contains('_vaultLoginsLoadToken == token'));
    expect(source, contains('_vaultLoginsLoadVault == vaultName'));
  });
}
