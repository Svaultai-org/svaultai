// Native Android OPAQUE client wrapper.
//
// This file calls libvaultai_opaque_client.so, a small Rust FFI shim
// over the same opaque-ke ciphersuite used by the backend and web
// WASM bundle. No browser APIs, WebView, plaintext PIN fallback, or
// backend-side PIN authentication are used here.

import 'dart:convert';
import 'dart:ffi';
import 'dart:io' show Platform;
import 'dart:isolate';

import 'package:ffi/ffi.dart';

class OpaqueUnavailable implements Exception {
  final String reason;
  OpaqueUnavailable(this.reason);
  @override
  String toString() => 'OpaqueUnavailable: $reason';
}

class OpaqueAuthenticationFailed implements Exception {
  final String stage;
  OpaqueAuthenticationFailed(this.stage);
  @override
  String toString() =>
      'OpaqueAuthenticationFailed: stage=$stage (wrong PIN or bad server response)';
}

class ClientRegistrationStart {
  final String clientRegistrationState;
  final String registrationRequest;
  const ClientRegistrationStart(
      this.clientRegistrationState, this.registrationRequest);
}

class ClientRegistrationFinish {
  final String registrationRecord;
  final String exportKey;
  final String? serverStaticPublicKey;
  const ClientRegistrationFinish(
      this.registrationRecord, this.exportKey, this.serverStaticPublicKey);
}

class ClientLoginStart {
  final String clientLoginState;
  final String startLoginRequest;
  const ClientLoginStart(this.clientLoginState, this.startLoginRequest);
}

class ClientLoginFinish {
  final String finishLoginRequest;
  final String sessionKey;
  final String exportKey;
  final String? serverStaticPublicKey;
  const ClientLoginFinish(
    this.finishLoginRequest,
    this.sessionKey,
    this.exportKey,
    this.serverStaticPublicKey,
  );
}

typedef _StartRegistrationNative = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _FinishRegistrationNative = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
);
typedef _StartLoginNative = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _FinishLoginNative = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
);
typedef _FreeNative = Void Function(Pointer<Utf8>);

typedef _StartRegistrationDart = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _FinishRegistrationDart = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
);
typedef _StartLoginDart = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _FinishLoginDart = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Pointer<Utf8>,
);
typedef _FreeDart = void Function(Pointer<Utf8>);

class _NativeOpaqueBindings {
  _NativeOpaqueBindings._(DynamicLibrary lib)
      : startRegistration = lib
            .lookupFunction<_StartRegistrationNative, _StartRegistrationDart>(
          'vaultai_opaque_client_start_registration',
        ),
        finishRegistration = lib
            .lookupFunction<_FinishRegistrationNative, _FinishRegistrationDart>(
          'vaultai_opaque_client_finish_registration',
        ),
        startLogin = lib.lookupFunction<_StartLoginNative, _StartLoginDart>(
          'vaultai_opaque_client_start_login',
        ),
        finishLogin = lib.lookupFunction<_FinishLoginNative, _FinishLoginDart>(
          'vaultai_opaque_client_finish_login',
        ),
        freeString = lib.lookupFunction<_FreeNative, _FreeDart>(
          'vaultai_opaque_client_free_string',
        );

  final _StartRegistrationDart startRegistration;
  final _FinishRegistrationDart finishRegistration;
  final _StartLoginDart startLogin;
  final _FinishLoginDart finishLogin;
  final _FreeDart freeString;

  static _NativeOpaqueBindings? _instance;

  static _NativeOpaqueBindings get instance {
    final cached = _instance;
    if (cached != null) return cached;
    if (!Platform.isAndroid) {
      throw OpaqueUnavailable(
        'native OPAQUE client is currently packaged for Android only',
      );
    }
    try {
      final loaded = _NativeOpaqueBindings._(
        DynamicLibrary.open('libvaultai_opaque_client.so'),
      );
      _instance = loaded;
      return loaded;
    } on Object {
      throw OpaqueUnavailable(
        'native OPAQUE client library is not available on this device',
      );
    }
  }
}

Map<String, dynamic> _decodeNativeResult(
  Pointer<Utf8> resultPtr, {
  required _NativeOpaqueBindings bindings,
  required String operation,
}) {
  if (resultPtr == nullptr) {
    throw OpaqueUnavailable('native OPAQUE $operation returned no result');
  }
  late final String resultText;
  try {
    resultText = resultPtr.toDartString();
  } finally {
    bindings.freeString(resultPtr);
  }
  final decoded = jsonDecode(resultText);
  if (decoded is! Map<String, dynamic>) {
    throw OpaqueUnavailable('native OPAQUE $operation returned invalid JSON');
  }
  if (decoded['ok'] == true) return decoded;
  final error = decoded['error']?.toString() ?? 'unknown';
  if (operation == 'finish_login' && error == 'auth_failed') {
    throw OpaqueAuthenticationFailed('finish_login');
  }
  throw OpaqueUnavailable('native OPAQUE $operation failed: $error');
}

class _NativeUtf8Allocation {
  _NativeUtf8Allocation._(this.pointer, this.byteLength);

  final Pointer<Uint8> pointer;
  final int byteLength;

  Pointer<Utf8> get utf8Pointer => pointer.cast<Utf8>();

  static _NativeUtf8Allocation fromString(String? value) {
    final bytes = utf8.encode(value ?? '');
    final pointer = calloc<Uint8>(bytes.length + 1);
    for (var i = 0; i < bytes.length; i++) {
      pointer[i] = bytes[i];
    }
    pointer[bytes.length] = 0;
    return _NativeUtf8Allocation._(pointer, bytes.length);
  }

  void clearAndFree() {
    for (var i = 0; i <= byteLength; i++) {
      pointer[i] = 0;
    }
    calloc.free(pointer);
  }
}

T _withUtf8<T>(List<String?> values, T Function(List<Pointer<Utf8>>) body) {
  final allocations = <_NativeUtf8Allocation>[];
  try {
    for (final value in values) {
      allocations.add(_NativeUtf8Allocation.fromString(value));
    }
    return body(allocations.map((a) => a.utf8Pointer).toList(growable: false));
  } finally {
    for (final allocation in allocations) {
      allocation.clearAndFree();
    }
  }
}

class OpaqueClient {
  static Future<void> ready() async {
    _NativeOpaqueBindings.instance;
  }

  static String? vendorVersion() => 'opaque-ke-native-4.x';

  static ClientRegistrationStart startRegistration({
    required String password,
  }) {
    final bindings = _NativeOpaqueBindings.instance;
    final result = _withUtf8([password], (args) {
      return _decodeNativeResult(
        bindings.startRegistration(args[0]),
        bindings: bindings,
        operation: 'start_registration',
      );
    });
    return ClientRegistrationStart(
      result['clientRegistrationState'] as String,
      result['registrationRequest'] as String,
    );
  }

  static Future<ClientRegistrationFinish> finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    return Isolate.run(
      () => _finishRegistrationSync(
        password: password,
        registrationResponse: registrationResponse,
        clientRegistrationState: clientRegistrationState,
        clientIdentifier: clientIdentifier,
        serverIdentifier: serverIdentifier,
      ),
    );
  }

  static ClientRegistrationFinish _finishRegistrationSync({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final bindings = _NativeOpaqueBindings.instance;
    final result = _withUtf8(
      [
        password,
        registrationResponse,
        clientRegistrationState,
        clientIdentifier,
        serverIdentifier,
      ],
      (args) => _decodeNativeResult(
        bindings.finishRegistration(
          args[0],
          args[1],
          args[2],
          args[3],
          args[4],
        ),
        bindings: bindings,
        operation: 'finish_registration',
      ),
    );
    return ClientRegistrationFinish(
      result['registrationRecord'] as String,
      result['exportKey'] as String,
      result['serverStaticPublicKey'] as String?,
    );
  }

  static ClientLoginStart startLogin({required String password}) {
    final bindings = _NativeOpaqueBindings.instance;
    final result = _withUtf8([password], (args) {
      return _decodeNativeResult(
        bindings.startLogin(args[0]),
        bindings: bindings,
        operation: 'start_login',
      );
    });
    return ClientLoginStart(
      result['clientLoginState'] as String,
      result['startLoginRequest'] as String,
    );
  }

  static Future<ClientLoginFinish> finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    return Isolate.run(
      () => _finishLoginSync(
        clientLoginState: clientLoginState,
        loginResponse: loginResponse,
        password: password,
        clientIdentifier: clientIdentifier,
        serverIdentifier: serverIdentifier,
      ),
    );
  }

  static ClientLoginFinish _finishLoginSync({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final bindings = _NativeOpaqueBindings.instance;
    final result = _withUtf8(
      [
        clientLoginState,
        loginResponse,
        password,
        clientIdentifier,
        serverIdentifier,
      ],
      (args) => _decodeNativeResult(
        bindings.finishLogin(
          args[0],
          args[1],
          args[2],
          args[3],
          args[4],
        ),
        bindings: bindings,
        operation: 'finish_login',
      ),
    );
    return ClientLoginFinish(
      result['finishLoginRequest'] as String,
      result['sessionKey'] as String,
      result['exportKey'] as String,
      result['serverStaticPublicKey'] as String?,
    );
  }
}
