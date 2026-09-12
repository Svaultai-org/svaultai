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

  test('chat dispatch and generated-login actions are parent-owned one-shot',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('bool _sendDispatchInFlight = false;'));
    expect(source, contains('if (_sendDispatchInFlight || sending) return;'));
    expect(source, contains('_sendDispatchInFlight = true;'));
    expect(source, contains('await _sendOnce();'));
    expect(source, contains('_sendDispatchInFlight = false;'));
    expect(source,
        contains('final composerBusy = sending || _sendDispatchInFlight;'));
    expect(source, contains('_generatedLoginDraftActionsInFlight'));
    expect(source, contains('_resolvedGeneratedLoginDrafts'));
    expect(source,
        contains("_setGeneratedLoginDraftActionState(msg, payload, 'saved')"));

    final router =
        File('lib/services/vault_chat_router.dart').readAsStringSync();
    expect(router, contains("'action_state',"));
    final cards = File('lib/ui/vault_chat_cards.dart').readAsStringSync();
    expect(cards, contains("actionState == 'saved'"));
    expect(cards, contains('vault_chat_card_generated_login_resolved'));
  });
}
