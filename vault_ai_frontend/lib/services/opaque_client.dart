// Dart JS-interop wrapper around the vendored @serenity-kit/opaque
// ESM bundle. The WASM implementation is the audited RFC 9807
// opaque-ke Rust crate; nothing here does cryptography.
//
// Runtime contract (Round 15 — lazy loader):
//   * index.html exposes ``globalThis.vaultaiEnsureOpaqueReady()`` —
//     an idempotent, dynamic-import-backed loader that triggers the
//     ESM + WASM fetch only the FIRST time it's called (i.e. only
//     when an auth flow actually needs OPAQUE) and returns the same
//     cached Promise on every subsequent call.
//   * Once that dynamic import evaluates, ``vaultai-opaque-init.js``
//     sets ``globalThis.vaultaiOpaqueReady`` and, when WASM has
//     instantiated, ``globalThis.vaultaiOpaqueClient`` — same shape
//     as the pre-Round-15 eager path, so the downstream JS interop
//     is unchanged.
//   * Every call in this file first awaits ``ready()``, which
//     invokes ``vaultaiEnsureOpaqueReady`` on first use.
//
// Non-web platforms (Flutter mobile/desktop) throw
// ``UnsupportedError`` — Phase 1's directive gates mobile release on
// a Flutter-native OPAQUE plugin.

import 'dart:async';
import 'dart:js_interop';

@JS('vaultaiEnsureOpaqueReady')
external JSFunction? get _vaultaiEnsureOpaqueReadyFn;

@JS('vaultaiOpaqueReady')
external JSPromise<JSAny?>? get _vaultaiOpaqueReady;

@JS('vaultaiOpaqueClient')
external JSObject? get _vaultaiOpaqueClient;

@JS('vaultaiOpaqueVendorVersion')
external String? get _vaultaiOpaqueVendorVersion;

extension type _OpaqueClientJs(JSObject _) implements JSObject {
  external _RegStart startRegistration(JSObject params);
  external _RegFinish finishRegistration(JSObject params);
  external _LoginStart startLogin(JSObject params);
  external _LoginFinish finishLogin(JSObject params);
}

extension type _RegStart(JSObject _) implements JSObject {
  external String get clientRegistrationState;
  external String get registrationRequest;
}

extension type _RegFinish(JSObject _) implements JSObject {
  external String get registrationRecord;
  external String get exportKey;
  external String? get serverStaticPublicKey;
}

extension type _LoginStart(JSObject _) implements JSObject {
  external String get clientLoginState;
  external String get startLoginRequest;
}

extension type _LoginFinish(JSObject _) implements JSObject {
  external String get finishLoginRequest;
  external String get sessionKey;
  external String get exportKey;
  external String? get serverStaticPublicKey;
}

class OpaqueUnavailable implements Exception {
  final String reason;
  OpaqueUnavailable(this.reason);
  @override
  String toString() => 'OpaqueUnavailable: $reason';
}

class OpaqueClient {
  /// Await this before any client call. Idempotent.
  ///
  /// Round 15 (lazy loader): calls ``vaultaiEnsureOpaqueReady()`` on
  /// first invocation, which dynamic-imports the vendored ESM + WASM
  /// bundle. Subsequent calls return the same cached Promise, so the
  /// module is fetched, parsed, and WASM-instantiated exactly once
  /// per page. If the lazy shim is missing (e.g. cached pre-Round-15
  /// index.html), fall back to the eager ``vaultaiOpaqueReady``
  /// global so already-deployed clients keep working.
  static Future<void> ready() async {
    JSPromise<JSAny?>? promise;
    final ensure = _vaultaiEnsureOpaqueReadyFn;
    if (ensure != null) {
      final result = ensure.callAsFunction();
      if (result == null) {
        throw OpaqueUnavailable(
          'vaultaiEnsureOpaqueReady() returned null; expected a '
          'Promise resolving once WASM instantiation completes.',
        );
      }
      promise = result as JSPromise<JSAny?>;
    } else {
      promise = _vaultaiOpaqueReady;
    }
    if (promise == null) {
      throw OpaqueUnavailable(
        'Neither vaultaiEnsureOpaqueReady nor vaultaiOpaqueReady is '
        'defined on globalThis. The Round-15 lazy OPAQUE loader block '
        'in index.html did not run, or a browser CSP is blocking the '
        'vendored WASM module.',
      );
    }
    await promise.toDart;
    if (_vaultaiOpaqueClient == null) {
      throw OpaqueUnavailable(
        'vaultaiOpaqueClient was not attached to globalThis after '
        'the OPAQUE ready Promise resolved; the WASM init did not '
        'complete.',
      );
    }
  }

  static _OpaqueClientJs get _client {
    final c = _vaultaiOpaqueClient;
    if (c == null) {
      throw OpaqueUnavailable('OpaqueClient.ready() has not resolved yet');
    }
    return _OpaqueClientJs(c);
  }

  static String? vendorVersion() => _vaultaiOpaqueVendorVersion;

  static ClientRegistrationStart startRegistration({
    required String password,
  }) {
    final params = _obj({'password': password}.jsify()!);
    final result = _client.startRegistration(params);
    return ClientRegistrationStart._(result);
  }

  static ClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final map = <String, dynamic>{
      'password': password,
      'registrationResponse': registrationResponse,
      'clientRegistrationState': clientRegistrationState,
    };
    if (clientIdentifier != null || serverIdentifier != null) {
      map['identifiers'] = {
        if (clientIdentifier != null) 'client': clientIdentifier,
        if (serverIdentifier != null) 'server': serverIdentifier,
      };
    }
    final result = _client.finishRegistration(_obj(map.jsify()!));
    return ClientRegistrationFinish._(result);
  }

  static ClientLoginStart startLogin({required String password}) {
    final params = _obj({'password': password}.jsify()!);
    final result = _client.startLogin(params);
    return ClientLoginStart._(result);
  }

  static ClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final map = <String, dynamic>{
      'clientLoginState': clientLoginState,
      'loginResponse': loginResponse,
      'password': password,
    };
    if (clientIdentifier != null || serverIdentifier != null) {
      map['identifiers'] = {
        if (clientIdentifier != null) 'client': clientIdentifier,
        if (serverIdentifier != null) 'server': serverIdentifier,
      };
    }
    final result = _client.finishLogin(_obj(map.jsify()!));
    return ClientLoginFinish._(result);
  }
}

JSObject _obj(JSAny value) => value as JSObject;

class ClientRegistrationStart {
  final String clientRegistrationState;
  final String registrationRequest;
  ClientRegistrationStart._(_RegStart o)
      : clientRegistrationState = o.clientRegistrationState,
        registrationRequest = o.registrationRequest;
}

class ClientRegistrationFinish {
  final String registrationRecord;
  final String exportKey;
  final String? serverStaticPublicKey;
  ClientRegistrationFinish._(_RegFinish o)
      : registrationRecord = o.registrationRecord,
        exportKey = o.exportKey,
        serverStaticPublicKey = o.serverStaticPublicKey;
}

class ClientLoginStart {
  final String clientLoginState;
  final String startLoginRequest;
  ClientLoginStart._(_LoginStart o)
      : clientLoginState = o.clientLoginState,
        startLoginRequest = o.startLoginRequest;
}

class ClientLoginFinish {
  final String finishLoginRequest;
  final String sessionKey;
  final String exportKey;
  final String? serverStaticPublicKey;
  ClientLoginFinish._(_LoginFinish o)
      : finishLoginRequest = o.finishLoginRequest,
        sessionKey = o.sessionKey,
        exportKey = o.exportKey,
        serverStaticPublicKey = o.serverStaticPublicKey;
}
