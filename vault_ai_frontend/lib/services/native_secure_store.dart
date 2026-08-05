import 'package:flutter/foundation.dart'
    show
        TargetPlatform,
        defaultTargetPlatform,
        kIsWeb,
        kReleaseMode,
        visibleForTesting;
import 'package:flutter/widgets.dart' show WidgetsFlutterBinding;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class NativeSecureStore {
  NativeSecureStore._();

  static const AndroidOptions _androidOptions = AndroidOptions(
    encryptedSharedPreferences: true,
  );

  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage(
    aOptions: _androidOptions,
  );

  @visibleForTesting
  static bool useSharedPreferencesForTesting = false;

  static bool get _failClosedOnSecureStorageError => kReleaseMode && !kIsWeb;

  static const _iosInstallMarker = 'vaultai_ios_install_marker_v1';
  static const _iosReinstallSensitiveKeys = <String>[
    'session_token',
    'last_vault_name',
    'last_display_name',
    'last_vault_handle',
    'vaultai_device_id_v1',
  ];

  /// Keychain records can survive uninstall while UserDefaults cannot. On a
  /// fresh iOS install, discard records left by a previous installation before
  /// hydrate can reuse a stale session or device identity.
  static Future<void> purgeIosKeychainAfterReinstallIfNeeded() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.iOS) return;
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_iosInstallMarker) == true) return;
    for (final key in _iosReinstallSensitiveKeys) {
      await _trySecureDelete(key);
      await prefs.remove(key);
    }
    await prefs.setBool(_iosInstallMarker, true);
  }

  static Future<String?> _trySecureRead(String key) async {
    try {
      WidgetsFlutterBinding.ensureInitialized();
      return await _secureStorage.read(
        key: key,
        aOptions: _androidOptions,
      );
    } catch (_) {
      if (_failClosedOnSecureStorageError) rethrow;
      return null;
    }
  }

  static Future<bool> _trySecureWrite(String key, String value) async {
    try {
      WidgetsFlutterBinding.ensureInitialized();
      await _secureStorage.write(
        key: key,
        value: value,
        aOptions: _androidOptions,
      );
      return true;
    } catch (_) {
      if (_failClosedOnSecureStorageError) rethrow;
      return false;
    }
  }

  static Future<bool> _trySecureDelete(String key) async {
    try {
      WidgetsFlutterBinding.ensureInitialized();
      await _secureStorage.delete(
        key: key,
        aOptions: _androidOptions,
      );
      return true;
    } catch (_) {
      if (_failClosedOnSecureStorageError) rethrow;
      return false;
    }
  }

  static Future<String?> readString(String key) async {
    final prefs = await SharedPreferences.getInstance();
    if (kIsWeb || useSharedPreferencesForTesting) return prefs.getString(key);

    final secureValue = await _trySecureRead(key);
    if (secureValue != null && secureValue.isNotEmpty) {
      return secureValue;
    }

    final legacyValue = prefs.getString(key);
    if (legacyValue != null && legacyValue.isNotEmpty) {
      final migrated = await _trySecureWrite(key, legacyValue);
      if (migrated) {
        await prefs.remove(key);
      }
    }
    return legacyValue;
  }

  static Future<void> writeString(String key, String value) async {
    final prefs = await SharedPreferences.getInstance();
    if (kIsWeb || useSharedPreferencesForTesting) {
      await prefs.setString(key, value);
      return;
    }
    final secureWritten = await _trySecureWrite(key, value);
    if (secureWritten) {
      await prefs.remove(key);
    } else {
      await prefs.setString(key, value);
    }
  }

  static Future<void> deleteString(String key) async {
    final prefs = await SharedPreferences.getInstance();
    if (!kIsWeb && !useSharedPreferencesForTesting) {
      await _trySecureDelete(key);
    }
    await prefs.remove(key);
  }
}
