// Non-Web fallback for OpaqueClient. Phase 1 gates Flutter mobile
// release on adopting a Flutter-native OPAQUE plugin, so any attempt
// to run these on Android/iOS/desktop is a bug.

import 'dart:async';

class OpaqueUnavailable implements Exception {
  final String reason;
  OpaqueUnavailable(this.reason);
  @override
  String toString() => 'OpaqueUnavailable: $reason';
}

/// Stub-side mirror of the Web-only OpaqueAuthenticationFailed.
/// Non-Web platforms don't run OPAQUE at all, but the exception
/// class must be exported from both conditional imports so
/// ``main.dart`` can ``on OpaqueAuthenticationFailed catch`` without
/// a per-platform ``if (kIsWeb)`` guard.
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

class OpaqueClient {
  static Future<void> ready() {
    throw UnsupportedError(
      'OPAQUE client not available on this platform. VaultAI\'s ZK auth '
      'ships on Flutter Web only for now; mobile/desktop release is '
      'gated on a Flutter-native OPAQUE plugin.',
    );
  }

  static String? vendorVersion() => null;

  static ClientRegistrationStart startRegistration(
      {required String password}) {
    throw UnsupportedError('non-web platform');
  }

  static ClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    throw UnsupportedError('non-web platform');
  }

  static ClientLoginStart startLogin({required String password}) {
    throw UnsupportedError('non-web platform');
  }

  static ClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    throw UnsupportedError('non-web platform');
  }
}
