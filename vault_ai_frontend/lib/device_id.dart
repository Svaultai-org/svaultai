import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart'
    show TargetPlatform, debugPrint, defaultTargetPlatform, kIsWeb, kReleaseMode;
import 'package:shared_preferences/shared_preferences.dart';

import 'services/native_secure_store.dart';


const _kDeviceIdKey = 'vaultai_device_id_v1';


const String deviceIdStorageKey = _kDeviceIdKey;
String? _cachedDeviceId;

void _vlog(String tag, [Map<String, Object?>? data]) {
  if (kReleaseMode) return;
  final payload = data == null
      ? ''
      : data.entries.map((e) => '${e.key}=${e.value}').join(' ');
  
  debugPrint('[vault-debug] $tag $payload');
}

String _idPrefix(String id) {
  
  
  if (id.length <= 8) return id;
  return id.substring(0, 8);
}


Future<String> getOrCreateDeviceId() async {
  if (_cachedDeviceId != null) {
    _vlog('device-id.load', {
      'source': 'memory',
      'id_prefix': _idPrefix(_cachedDeviceId!),
    });
    return _cachedDeviceId!;
  }
  final sp = await SharedPreferences.getInstance();
  // Preserve Android/web behavior. On iOS the device-bound identifier is
  // sensitive session metadata and belongs in Keychain, with one-time
  // migration handled by NativeSecureStore.
  final useIosKeychain = !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;
  var id = useIosKeychain
      ? await NativeSecureStore.readString(_kDeviceIdKey)
      : sp.getString(_kDeviceIdKey);
  final created = id == null || id.isEmpty;
  if (created) {
    final r = Random.secure();
    final bytes = List<int>.generate(32, (_) => r.nextInt(256));
    id = base64Url.encode(bytes).replaceAll('=', '');
    if (useIosKeychain) {
      await NativeSecureStore.writeString(_kDeviceIdKey, id);
    } else {
      await sp.setString(_kDeviceIdKey, id);
    }
    _vlog('device-id.persisted', {
      'key': _kDeviceIdKey,
      'id_prefix': _idPrefix(id),
    });
  }
  _vlog('device-id.load', {
    'source': created ? 'created' : 'existing',
    'id_prefix': _idPrefix(id),
  });
  _cachedDeviceId = id;
  return id;
}


String? currentDeviceId() => _cachedDeviceId;


String currentDeviceLabel() {
  if (kIsWeb) return 'Web browser';
  return 'Native app';
}
