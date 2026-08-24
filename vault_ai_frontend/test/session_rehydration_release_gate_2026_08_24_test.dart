import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  late String source;

  setUpAll(() {
    source = File('lib/main.dart').readAsStringSync();
  });

  test('logout clears local secrets but never deletes server vault data', () {
    final start = source.indexOf(
      'Future<void> clearSession({bool keepLastVaultName = true})',
    );
    final end = source.indexOf('void markUnlocked()', start);
    final clearSession = source.substring(start, end);

    expect(clearSession, contains('ZkActiveMvk.clear()'));
    expect(clearSession, contains("deleteString('session_token')"));
    expect(clearSession, isNot(contains('deleteVaultSecureItem')));
    expect(clearSession, isNot(contains('deleteFileV2')));
    expect(clearSession, isNot(contains('deleteMemory')));
  });

  test('login restores authoritative vault identity and MVK before chat', () {
    final loginStart = source.indexOf('class _LoginPageState');
    final signupStart = source.indexOf('class SignupPage', loginStart);
    final login = source.substring(loginStart, signupStart);

    final setSession = login.indexOf('await app.setSession(');
    final mvk = login.indexOf('zk_mvk_store.ZkActiveMvk.set(', setSession);
    final unlock = login.indexOf('app.markUnlocked()', mvk);
    final navigate = login.indexOf(
        "Navigator.pushReplacementNamed(context, '/chat')", unlock);
    expect(setSession, greaterThanOrEqualTo(0));
    expect(mvk, greaterThan(setSession));
    expect(unlock, greaterThan(mvk));
    expect(navigate, greaterThan(unlock));
  });

  test('credential and file reads await session-local single flights', () {
    expect(source, contains('Future<void>? _vaultLoginsLoadFuture'));
    expect(source, contains('Future<void>? _vaultFilesLoadFuture'));
    expect(source, contains('if (active != null) return active'));
    expect(source, isNot(contains('vaultLogins.isEmpty && !loadingLogins')));
    expect(source, isNot(contains('vaultFiles.isEmpty && !loadingFiles')));
  });

  test('memory reads capture and verify authenticated session ownership', () {
    final start = source.indexOf(
      'Future<bool> _tryLocalMemoryV2LookupReply',
    );
    final end = source.indexOf(
      'Future<bool> _tryLocalMemoryV2ContextSave',
      start,
    );
    final lookup = source.substring(start, end);
    expect(lookup, contains('app.sessionToken == null'));
    expect(lookup, contains('MemoryV2Repository('));
    expect(lookup, contains('authToken: lookupToken'));
    expect(lookup, contains('.listDecrypted()'));
    expect(lookup, contains('app.ownsSessionLoad('));
  });
}
