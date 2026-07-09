
class CacheEntry<T> {
  final T value;
  final DateTime storedAt;
  final Duration ttl;

  CacheEntry({
    required this.value,
    required this.storedAt,
    required this.ttl,
  });

  bool isFresh(DateTime now) => now.difference(storedAt) < ttl;

  bool isExpired(DateTime now) => !isFresh(now);
}


bool _looksLikeSensitiveKey(String key) {
  final k = key.toLowerCase();
  const banned = <String>[
    'pin',
    'password',
    'seed',
    'mnemonic',
    'private_key',
    'privatekey',
    'spend_key',
    'view_key',
    'auth_token',
    'authtoken',
    'bearer',
    'api_key',
    'apikey',
    'encrypted_data',
    'encrypteddata',
    'session_token',
    'sessiontoken',
    'pin_verifier',
  ];
  for (final b in banned) {
    if (k.contains(b)) return true;
  }
  return false;
}


bool _looksLikeSensitiveValue(Object? value) {
  if (value == null) return false;
  final s = value.toString().toLowerCase();
  if (s.length > 800) return false;
  const banned = <String>[
    'seed phrase',
    'mnemonic',
    'private key',
    'spend key',
    'view key',
    'pin_verifier',
    'encrypted_data',
    '-----begin ',
  ];
  for (final b in banned) {
    if (s.contains(b)) return true;
  }
  return false;
}



class SensitiveDataCachedException implements Exception {
  final String key;
  const SensitiveDataCachedException(this.key);
  @override
  String toString() =>
      'SensitiveDataCachedException: refused to cache "$key" — '
      'key or value looks like it contains a secret';
}


class FrontendCache {
  FrontendCache._();

  static final FrontendCache instance = FrontendCache._();

  final Map<String, CacheEntry<Object?>> _entries = {};

  DateTime Function() nowClock = () => DateTime.now();

  T? get<T>(String key) {
    final entry = _entries[key];
    if (entry == null) return null;
    if (entry.isExpired(nowClock())) {
      _entries.remove(key);
      return null;
    }
    final v = entry.value;
    if (v is T) return v;
    return null;
  }

  bool has(String key) {
    final e = _entries[key];
    if (e == null) return false;
    if (e.isExpired(nowClock())) {
      _entries.remove(key);
      return false;
    }
    return true;
  }

  void put<T>(
    String key,
    T value, {
    Duration ttl = const Duration(seconds: 60),
  }) {
    if (_looksLikeSensitiveKey(key)) {
      throw SensitiveDataCachedException(key);
    }
    if (_looksLikeSensitiveValue(value)) {
      throw SensitiveDataCachedException(key);
    }
    _entries[key] = CacheEntry<Object?>(
      value: value,
      storedAt: nowClock(),
      ttl: ttl,
    );
  }

  int size() => _entries.length;

  void invalidateAll() {
    _entries.clear();
  }

  void invalidatePrefix(String prefix) {
    final drop = <String>[];
    for (final k in _entries.keys) {
      if (k.startsWith(prefix)) drop.add(k);
    }
    for (final k in drop) {
      _entries.remove(k);
    }
  }

  Set<String> keys() => _entries.keys.toSet();
}



const String kCacheBucketCryptoBalance   = 'crypto:balance:';
const String kCacheBucketCryptoActivity  = 'crypto:activity:';
const String kCacheBucketVaultOverview   = 'vault:overview:';
const String kCacheBucketStorageQuota    = 'storage:quota:';
const String kCacheBucketBillingStatus   = 'billing:status:';
const String kCacheBucketFaqEnvelope     = 'faq:envelope:';
const String kCacheBucketLoginList       = 'logins:list:';
const String kCacheBucketSecureItemList  = 'secureitems:list:';
const String kCacheBucketIdDocumentList  = 'ids:list:';
const String kCacheBucketDeleteStatus    = 'vaultdelete:status:';
const String kCacheBucketSettingsProfile = 'settings:profile:';



const Duration kCacheTtlShort   = Duration(seconds: 15);
const Duration kCacheTtlMedium  = Duration(seconds: 60);
const Duration kCacheTtlLong    = Duration(minutes: 5);



void clearCacheOnLogout() {
  FrontendCache.instance.invalidateAll();
}


void clearCacheOnVaultSwitch(
  String? previousVaultId,
  String? newVaultId,
) {
  if (previousVaultId == newVaultId) return;
  FrontendCache.instance.invalidateAll();
}
