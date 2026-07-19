// Dart JS-interop wrapper around the vendored @serenity-kit/opaque
// ESM bundle. The WASM implementation is the audited RFC 9807
// opaque-ke Rust crate; nothing here does cryptography.
//
// Runtime contract:
//   * vaultai-opaque-init.js (loaded from index.html) sets
//     ``globalThis.vaultaiOpaqueReady`` and, once WASM has
//     instantiated, ``globalThis.vaultaiOpaqueClient``.
//   * Every call in this file first awaits ``ready()``.
//
// Non-web platforms (Flutter mobile/desktop) throw
// ``UnsupportedError`` — Phase 1's directive gates mobile release on
// a Flutter-native OPAQUE plugin.

import 'dart:async';
import 'dart:js_interop';

@JS('vaultaiOpaqueReady')
external JSPromise<JSAny?>? get _vaultaiOpaqueReady;

@JS('vaultaiOpaqueClient')
external JSObject? get _vaultaiOpaqueClient;

@JS('vaultaiOpaqueVendorVersion')
external String? get _vaultaiOpaqueVendorVersion;

extension type _OpaqueClientJs(JSObject _) implements JSObject {
  // Returns are declared nullable because @serenity-kit/opaque
  // returns ``undefined`` on OPAQUE-protocol authentication failure
  // (RFC 9807: the client cannot tell the server that login failed,
  // so it silently returns nothing). Reading a getter on an undefined
  // return throws a raw JavaScript TypeError; each wrapper below
  // null-checks and converts to a typed Dart exception instead.
  external JSObject? startRegistration(JSObject params);
  external JSObject? finishRegistration(JSObject params);
  external JSObject? startLogin(JSObject params);
  external JSObject? finishLogin(JSObject params);
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

/// Raised when @serenity-kit/opaque's ``client.*`` returns
/// ``undefined``.
///
/// Per RFC 9807 the OPAQUE client cannot tell the server that the
/// login failed — the protocol silently returns no payload when the
/// PIN is wrong, when the server response cannot be unwrapped with
/// the registration record, or when the credential identifiers do
/// not agree.
///
/// The wrappers in [OpaqueClient] detect the missing return and throw
/// this exception instead of letting a raw JavaScript TypeError
/// bubble up as "Null check operator used on a null value". Callers
/// catching this must map it to a user-facing "Wrong username or
/// PIN" message and MUST NOT retry with the legacy /auth/login path —
/// re-attempting would only expose the same wrong PIN to an
/// enumerable timing oracle.
class OpaqueAuthenticationFailed implements Exception {
  final String stage;
  OpaqueAuthenticationFailed(this.stage);
  @override
  String toString() =>
      'OpaqueAuthenticationFailed: stage=$stage (wrong PIN or bad server response)';
}

class OpaqueClient {
  /// Await this before any client call. Idempotent.
  static Future<void> ready() async {
    final promise = _vaultaiOpaqueReady;
    if (promise == null) {
      throw OpaqueUnavailable(
        'vaultaiOpaqueReady is missing on window. The '
        '<script type="module" src="assets/opaque/vaultai-opaque-init.js">'
        ' tag in index.html did not load, or a browser CSP is blocking '
        'the vendored WASM module.',
      );
    }
    await promise.toDart;
    if (_vaultaiOpaqueClient == null) {
      throw OpaqueUnavailable(
        'vaultaiOpaqueClient was not attached to globalThis after '
        'vaultaiOpaqueReady resolved; the WASM init did not complete.',
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
    if (result == null) {
      // startRegistration should NEVER return undefined for a valid
      // password input. If it does, the vendored bundle is broken;
      // OpaqueUnavailable is the correct signal.
      throw OpaqueUnavailable(
        'client.startRegistration returned undefined',
      );
    }
    return ClientRegistrationStart._(_RegStart(result));
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
    if (result == null) {
      // finishRegistration returning undefined during a signup means
      // the server-side registration response was malformed. Treat
      // as an unavailable-module signal rather than an auth failure
      // — a wrong PIN cannot cause this on the registration path
      // (there is no verifier yet).
      throw OpaqueUnavailable(
        'client.finishRegistration returned undefined',
      );
    }
    return ClientRegistrationFinish._(_RegFinish(result));
  }

  static ClientLoginStart startLogin({required String password}) {
    final params = _obj({'password': password}.jsify()!);
    final result = _client.startLogin(params);
    if (result == null) {
      throw OpaqueUnavailable(
        'client.startLogin returned undefined',
      );
    }
    return ClientLoginStart._(_LoginStart(result));
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
    if (result == null) {
      // This is the ROOT CAUSE of the a084794 production diagnostic
      // "Cannot read properties of undefined (reading 'finishLoginRequest')".
      //
      // @serenity-kit/opaque's client.finishLogin returns undefined
      // when the OPAQUE protocol says authentication failed. Per RFC
      // 9807 the client cannot report failure to the server — it
      // silently returns no payload. Wrong PIN is the overwhelming
      // real-world cause; a mismatched credential identifier
      // between register and login would also trigger it.
      throw OpaqueAuthenticationFailed('finish_login');
    }
    return ClientLoginFinish._(_LoginFinish(result));
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
