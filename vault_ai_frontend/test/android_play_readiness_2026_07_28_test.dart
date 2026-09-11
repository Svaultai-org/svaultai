import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('Android Play readiness hardening', () {
    test('package id and Play SDK levels are explicit', () {
      final gradle = _read('android/app/build.gradle.kts');

      expect(gradle, contains('namespace = "com.svaultai.app"'));
      expect(gradle, contains('applicationId = "com.svaultai.app"'));
      expect(gradle, contains('compileSdk = 36'));
      expect(gradle, contains('targetSdk = 36'));
      expect(gradle, contains('minSdk = 24'));
    });

    test('manifest blocks cleartext traffic and Android backups', () {
      final manifest = _read('android/app/src/main/AndroidManifest.xml');

      expect(manifest, contains('android:allowBackup="false"'));
      expect(manifest, contains('android:usesCleartextTraffic="false"'));
      expect(
        manifest,
        contains(
            'android:networkSecurityConfig="@xml/network_security_config"'),
      );
      expect(
        manifest,
        contains('android:dataExtractionRules="@xml/data_extraction_rules"'),
      );
      expect(
          manifest, contains('android:fullBackupContent="@xml/backup_rules"'));
    });

    test('network security config is HTTPS-only for Svaultai domains', () {
      final config =
          _read('android/app/src/main/res/xml/network_security_config.xml');

      expect(config, contains('cleartextTrafficPermitted="false"'));
      expect(config, contains('api.svaultai.com'));
      expect(config, contains('app.svaultai.com'));
      expect(config, contains('svaultai.com'));
      expect(config, isNot(contains('localhost')));
      expect(config, isNot(contains('127.0.0.1')));
    });

    test('backup and device-transfer rules exclude local vault state', () {
      final backup = _read('android/app/src/main/res/xml/backup_rules.xml');
      final extraction =
          _read('android/app/src/main/res/xml/data_extraction_rules.xml');

      for (final domain in ['file', 'database', 'sharedpref', 'external']) {
        expect(backup, contains('domain="$domain"'));
        expect(extraction, contains('domain="$domain"'));
      }
    });

    test('release builds prevent screenshots and recents thumbnails', () {
      final activity = _read(
        'android/app/src/main/kotlin/com/svaultai/app/MainActivity.kt',
      );

      expect(activity, contains('ApplicationInfo.FLAG_DEBUGGABLE'));
      expect(activity, contains('WindowManager.LayoutParams.FLAG_SECURE'));
      expect(activity, contains('setRecentsScreenshotEnabled(false)'));
    });

    test('native auth identity storage uses Android Keystore-backed storage',
        () {
      final store = _read('lib/services/native_secure_store.dart');
      final app = _read('lib/main.dart');
      final adoption = _read('lib/services/legacy_adoption.dart');

      expect(store, contains('FlutterSecureStorage'));
      expect(store, contains('AndroidOptions'));
      expect(store, contains('encryptedSharedPreferences: true'));
      expect(app, contains('NativeSecureStore.readString(\'session_token\')'));
      expect(app, contains('NativeSecureStore.writeString(\'session_token\''));
      expect(
          app, contains('NativeSecureStore.deleteString(\'session_token\')'));
      expect(adoption, contains('NativeSecureStore.writeString'));
    });

    test('release signing fails closed without upload-key config', () {
      final gradle = _read('android/app/build.gradle.kts');

      expect(gradle, contains('releaseSigningFailureMessage'));
      expect(
        gradle,
        contains('Release APK/AAB builds must never fall back to debug signing'),
      );
      expect(gradle, isNot(contains('signingConfigs.getByName("debug")')));
      expect(gradle, isNot(contains('DEBUG-SIGNED')));
    });

    test('no unverified Android app links are declared yet', () {
      final manifest = _read('android/app/src/main/AndroidManifest.xml');

      expect(manifest, isNot(contains('android:autoVerify="true"')));
      expect(manifest, isNot(contains('android.intent.category.BROWSABLE')));
    });
  });
}
