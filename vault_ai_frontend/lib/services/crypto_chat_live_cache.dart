


import 'dart:async';

import 'crypto_vault_chat_control.dart'
    show kCvcForbiddenDataKeys;




const String kCryptoChatCacheRequestBalance  = 'balance';
const String kCryptoChatCacheRequestActivity = 'activity';




Map<String, dynamic> _stripForbiddenForCache(Map<String, dynamic> raw) {
  final out = <String, dynamic>{};
  for (final entry in raw.entries) {
    final k = entry.key;
    if (kCvcForbiddenDataKeys.contains(k)) continue;
    final v = entry.value;
    if (v is Map<String, dynamic>) {
      out[k] = _stripForbiddenForCache(v);
    } else if (v is Map) {
      out[k] = _stripForbiddenForCache(v.cast<String, dynamic>());
    } else if (v is List) {
      out[k] = _stripForbiddenListForCache(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}


List<dynamic> _stripForbiddenListForCache(List<dynamic> raw) {
  return raw.map((e) {
    if (e is Map<String, dynamic>) {
      return _stripForbiddenForCache(e);
    }
    if (e is Map) {
      return _stripForbiddenForCache(e.cast<String, dynamic>());
    }
    if (e is List) return _stripForbiddenListForCache(e);
    return e;
  }).toList();
}




class _CachedEnvelope {
  final Map<String, dynamic> data;
  final DateTime expiresAt;
  _CachedEnvelope({required this.data, required this.expiresAt});
}




class CryptoChatLiveCache {


  static const Duration defaultTtl = Duration(seconds: 45);


  static final CryptoChatLiveCache instance = CryptoChatLiveCache();


  final Duration ttl;


  final DateTime Function() _clock;


  final Map<String, _CachedEnvelope> _cache =
      <String, _CachedEnvelope>{};


  final Map<String, Future<Map<String, dynamic>>> _inFlight =
      <String, Future<Map<String, dynamic>>>{};

  CryptoChatLiveCache({
    this.ttl = defaultTtl,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;


  String _key(String type, String asset, String address) =>
      '$type|$asset|$address';


  bool hasFresh({
    required String type,
    required String asset,
    required String address,
  }) {
    if (asset == 'XMR') return false;
    final e = _cache[_key(type, asset, address)];
    if (e == null) return false;
    return _clock().isBefore(e.expiresAt);
  }


  Map<String, dynamic>? peek({
    required String type,
    required String asset,
    required String address,
  }) {
    if (asset == 'XMR') return null;
    if (asset.isEmpty || address.isEmpty) return null;
    final e = _cache[_key(type, asset, address)];
    if (e == null) return null;
    if (!_clock().isBefore(e.expiresAt)) return null;
    return e.data;
  }


  bool isInFlight({
    required String type,
    required String asset,
    required String address,
  }) {
    if (asset == 'XMR') return false;
    return _inFlight.containsKey(_key(type, asset, address));
  }


  Future<Map<String, dynamic>> fetch({
    required String type,
    required String asset,
    required String address,
    required Future<Map<String, dynamic>> Function() run,
  }) {


    if (asset == 'XMR') {
      return run();
    }
    if (asset.isEmpty || address.isEmpty) {
      return run();
    }
    final key = _key(type, asset, address);


    final cached = _cache[key];
    if (cached != null && _clock().isBefore(cached.expiresAt)) {
      return Future.value(cached.data);
    }


    final existing = _inFlight[key];
    if (existing != null) return existing;


    late Future<Map<String, dynamic>> future;
    future = () async {
      try {
        final result = await run();


        if (result is Map<String, dynamic>) {
          final safe = _stripForbiddenForCache(result);
          final status = (safe['balanceStatus']
              ?? safe['activityStatus']
              ?? '').toString();


          if (status == 'unavailable') {

          } else {
            _cache[key] = _CachedEnvelope(
              data: safe,
              expiresAt: _clock().add(ttl),
            );
          }
        }
        return result;
      } finally {
        _inFlight.remove(key);
      }
    }();
    _inFlight[key] = future;
    return future;
  }


  void invalidate({
    required String type,
    required String asset,
    required String address,
  }) {
    if (asset.isEmpty || address.isEmpty) return;
    _cache.remove(_key(type, asset, address));
  }


  void clear() {
    _cache.clear();
    _inFlight.clear();
  }


  int get cacheSize    => _cache.length;
  int get inFlightSize => _inFlight.length;


  bool containsCacheKey(String type, String asset, String address) =>
      _cache.containsKey(_key(type, asset, address));
}
