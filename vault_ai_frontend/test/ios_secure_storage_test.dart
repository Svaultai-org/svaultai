import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late FlutterSecureStoragePlatform originalPlatform;
  late Map<String, String> keychain;

  setUp(() {
    originalPlatform = FlutterSecureStoragePlatform.instance;
    keychain = <String, String>{};
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform(keychain);
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    NativeSecureStore.useSharedPreferencesForTesting = false;
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  tearDown(() {
    FlutterSecureStoragePlatform.instance = originalPlatform;
    debugDefaultTargetPlatformOverride = null;
  });

  test('first install clears stale session, identity, and device records',
      () async {
    keychain.addAll({
      'session_token': 'stale-token',
      'last_vault_name': 'stale-vault',
      'last_display_name': 'stale-name',
      'last_vault_handle': 'stale-handle',
      'vaultai_device_id_v1': 'stale-device',
      'unrelated_key': 'keep-me',
    });

    await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();

    expect(keychain, equals({'unrelated_key': 'keep-me'}));
    expect(
      (await SharedPreferences.getInstance())
          .getBool('vaultai_ios_install_marker_v1'),
      isTrue,
    );
  });

  test('normal launch preserves current Keychain records', () async {
    SharedPreferences.setMockInitialValues({
      'vaultai_ios_install_marker_v1': true,
    });
    keychain['session_token'] = 'current-token';
    await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();
    expect(keychain['session_token'], 'current-token');
  });

  test('app update preserves records because UserDefaults marker survives',
      () async {
    SharedPreferences.setMockInitialValues({
      'vaultai_ios_install_marker_v1': true,
    });
    keychain['vaultai_device_id_v1'] = 'trusted-device';
    await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();
    expect(keychain['vaultai_device_id_v1'], 'trusted-device');
  });

  test('logout then login replaces the session record', () async {
    await NativeSecureStore.writeString('session_token', 'account-a');
    await NativeSecureStore.deleteString('session_token');
    expect(await NativeSecureStore.readString('session_token'), isNull);
    await NativeSecureStore.writeString('session_token', 'account-b');
    expect(await NativeSecureStore.readString('session_token'), 'account-b');
  });

  test('reinstall simulation removes an authenticated session', () async {
    keychain['session_token'] = 'authenticated-before-uninstall';
    SharedPreferences.setMockInitialValues(<String, Object>{});
    await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();
    expect(await NativeSecureStore.readString('session_token'), isNull);
  });

  test('account switch source clears account-bound crypto and identity', () {
    final source = File('lib/main.dart').readAsStringSync();
    final clear = source.substring(
      source.indexOf('Future<void> clearSession'),
      source.indexOf('void markUnlocked'),
    );
    expect(clear, contains('ZkActiveMvk.clear()'));
    expect(clear, contains('ZkActiveSkVault.clear()'));
    expect(clear, contains("deleteString('last_vault_handle')"));
    expect(clear, contains("deleteString('last_display_name')"));
  });

  test('stale Keychain record cannot survive a missing install marker',
      () async {
    keychain['last_vault_handle'] = 'old-account';
    await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();
    expect(keychain, isNot(contains('last_vault_handle')));
  });

  test('corrupted session is rejected and deleted after authMe failure', () {
    final source = File('lib/main.dart').readAsStringSync();
    final hydrate = source.substring(
      source.indexOf('Future<void> hydrate()'),
      source.indexOf('Future<void> setSession'),
    );
    expect(hydrate, contains('await client.authMe(authToken: sessionToken!)'));
    expect(hydrate, contains("deleteString('session_token')"));
    expect(hydrate.indexOf('sessionToken = null'),
        lessThan(hydrate.indexOf("deleteString('session_token')")));
  });

  test('startup guard runs before device and session reads', () {
    final source = File('lib/main.dart').readAsStringSync();
    final guard = source.indexOf('purgeIosKeychainAfterReinstallIfNeeded');
    expect(guard, lessThan(source.indexOf('getOrCreateDeviceId()')));
    expect(guard, lessThan(source.indexOf("readString('session_token')")));
  });

  test('vault secrets are not persisted through SharedPreferences', () {
    final files = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'));
    final forbidden = RegExp(
      r'\.setString\([^\n]*(?:pin|mvk|vault_secret|session_token)',
      caseSensitive: false,
    );
    final offenders = <String>[];
    for (final file in files) {
      if (forbidden.hasMatch(file.readAsStringSync())) offenders.add(file.path);
    }
    expect(offenders, isEmpty);
  });
}
