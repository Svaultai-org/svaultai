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

  test('dashboard lists both ciphertext items and pre-fix legacy chat saves',
      () {
    final source = File('lib/api_client.dart').readAsStringSync();
    final start = source.indexOf('listVaultSecureItems({');
    final end = source.indexOf('_listZkVaultItems({', start);
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final body = source.substring(start, end);
    expect(body, contains('_listLegacyVaultSecureItems('));
    expect(body, contains("item['storage_engine'] = 'legacy_compatibility'"));
    expect(body, contains("'ciphertext_with_legacy_compatibility'"));
  });

  test('generated-login card saves directly to ciphertext inventory', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf("if (action == 'generated_login_save')");
    final end =
        source.indexOf("if (action == 'generated_login_cancel')", start);
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final actionBody = source.substring(start, end);
    expect(actionBody, contains('_saveGeneratedLoginDraftFromCard'));
    expect(actionBody, isNot(contains("_sendQuickPrompt('save it')")));
    expect(source, contains('.saveGeneratedLoginDraftCiphertext('));
    expect(source, contains('await _reloadVaultLoginsAfterMutation();'));
  });
}
