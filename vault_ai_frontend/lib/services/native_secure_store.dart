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

  // Web auth is session-only: identifiers and bearer tokens must not survive
  // a refresh in localStorage (the web SharedPreferences backend). Native
  // platforms still use their secure store and retain PIN-only return.
  static const _webSessionOnlyKeys = <String>{
    'session_token',
    'session_signed_out_code',
    'last_vault_name',
    'last_vault_handle',
    'last_display_name',
    'last_display_username',
    'last_canonical_username',
    'last_vault_ai_name',
    'vaultai.zk.vault_handle',
  };

  /// Remove credentials and identifiers left by older web releases. This
  /// touches only auth keys, not vault data or unrelated preferences.
  static Future<void> clearPreviouslySavedWebAuth() async {
    if (!kIsWeb) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    for (final key in _webSessionOnlyKeys) {
      await prefs.remove(key);
    }
  }

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
    'session_signed_out_code',
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
    if (kIsWeb) {
      if (_webSessionOnlyKeys.contains(key)) {
        await prefs.remove(key);
        return null;
      }
      return prefs.getString(key);
    }
    if (useSharedPreferencesForTesting) return prefs.getString(key);

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
    if (kIsWeb && _webSessionOnlyKeys.contains(key)) {
      await prefs.remove(key);
      return;
    }
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
