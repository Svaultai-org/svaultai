// ZK auth orchestration.
//
// Wires together:
//   * vault_handle.dart          (Crockford base32 identifier)
//   * opaque_client.dart         (JS interop to WASM OPAQUE)
//   * cryptography package        (AES-GCM to wrap MVK/sk_vault + HKDF)
//   * api_client.dart             (POSTs to /auth/zk-* endpoints)
//
// User-facing API:
//   * registerVault({displayName, pin})
//         -> RegisterResult(vaultHandle, sessionToken, mvk, ...)
//   * loginVault({vaultHandle, pin})
//         -> LoginResult(sessionToken, mvk, displayName, ...)
//   * adoptLegacyVault({legacyDisplayName, pin, currentSessionToken})
//         -> AdoptResult(newVaultHandle)
//
// Key hierarchy (unchanged from Phase 1 design):
//
//   OPAQUE(pin, wasm) → exportKey (32 B, client-only)
//        │
//        ▼   HKDF-SHA-256, info="vaultai.kek.v1"
//   KEK (32 B)
//        │
//        ▼   AES-GCM-256(nonce, MVK)
//   wrappedMvk  ← sent to server
//
// MVK is fresh random per vault at registration. sk_vault_private is
// a random X25519 secret (32 B). display_name is encrypted with a
// subkey derived from MVK (HKDF info="vaultai.display.v1"). The
// server sees only ciphertext.
//
// This file contains no bespoke crypto. All primitives come from the
// audited `cryptography` package and `opaque_client.dart` (which
// wraps opaque-ke via WASM).

import 'dart:convert';
import 'dart:typed_data';
import 'dart:math' show Random;

import 'package:cryptography/cryptography.dart';

import 'opaque_client.dart'
    if (dart.library.io) 'opaque_client_stub.dart';
import 'vault_handle.dart';

const int _mvkBytes = 32;
const int _skVaultBytes = 32;
const int _aesGcmNonceBytes = 12;

final Hkdf _hkdf = Hkdf(
  hmac: Hmac.sha256(),
  outputLength: 32,
);

final AesGcm _aesGcm = AesGcm.with256bits();

class RegisterResult {
  final String vaultId;
  final String vaultHandle;
  final String sessionToken;
  final SecretKey mvk;
  final SecretKey skVaultPrivate;
  final Uint8List pkVaultPublic;
  final String displayName;
  RegisterResult({
    required this.vaultId,
    required this.vaultHandle,
    required this.sessionToken,
    required this.mvk,
    required this.skVaultPrivate,
    required this.pkVaultPublic,
    required this.displayName,
  });
}

class LoginResult {
  final String vaultId;
  final String vaultHandle;
  final String sessionToken;
  final SecretKey mvk;
  final SecretKey skVaultPrivate;
  final String displayName;
  LoginResult({
    required this.vaultId,
    required this.vaultHandle,
    required this.sessionToken,
    required this.mvk,
    required this.skVaultPrivate,
    required this.displayName,
  });
}

class AdoptResult {
  final String newVaultHandle;
  AdoptResult(this.newVaultHandle);
}

/// Callback that POSTs the given ZK auth-endpoint JSON body and
/// returns the parsed JSON. Extracted so widget tests can inject a
/// fake without touching the network.
typedef ZkHttpPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body, {
  String? bearerToken,
});

class ZkAuthService {
  final ZkHttpPost _post;
  ZkAuthService(this._post);

  Future<SecretKey> _deriveKek(String exportKeyB64) async {
    final exportKeyBytes = _b64urlDecode(exportKeyB64);
    return _hkdf.deriveKey(
      secretKey: SecretKey(exportKeyBytes),
      nonce: const [],
      info: utf8.encode('vaultai.kek.v1'),
    );
  }

  Future<SecretKey> _deriveDisplayNameKey(SecretKey mvk) async {
    final mvkBytes = await mvk.extractBytes();
    return _hkdf.deriveKey(
      secretKey: SecretKey(mvkBytes),
      nonce: const [],
      info: utf8.encode('vaultai.display.v1'),
    );
  }

  Future<Uint8List> _wrap(SecretKey key, Uint8List plaintext) async {
    final nonce = _randomBytes(_aesGcmNonceBytes);
    final secretBox = await _aesGcm.encrypt(
      plaintext,
      secretKey: key,
      nonce: nonce,
    );
    // Envelope: version(0x01) || nonce(12) || ciphertext || tag(16)
    final ct = secretBox.cipherText;
    final tag = secretBox.mac.bytes;
    final out = BytesBuilder();
    out.addByte(0x01);
    out.add(nonce);
    out.add(ct);
    out.add(tag);
    return out.toBytes();
  }

  Future<Uint8List> _unwrap(SecretKey key, Uint8List envelope) async {
    if (envelope.isEmpty || envelope[0] != 0x01) {
      throw StateError('unwrapped envelope: unknown version byte');
    }
    final nonce = envelope.sublist(1, 1 + _aesGcmNonceBytes);
    final tagStart = envelope.length - 16;
    final ct = envelope.sublist(1 + _aesGcmNonceBytes, tagStart);
    final tag = envelope.sublist(tagStart);
    final secretBox = SecretBox(ct, nonce: nonce, mac: Mac(tag));
    final clear = await _aesGcm.decrypt(secretBox, secretKey: key);
    return Uint8List.fromList(clear);
  }

  Uint8List _randomBytes(int len) {
    final rng = Random.secure();
    final out = Uint8List(len);
    for (var i = 0; i < len; i++) {
      out[i] = rng.nextInt(256);
    }
    return out;
  }

  String _b64urlEncode(Uint8List raw) => vaultHandleB64Url(raw);

  Uint8List _b64urlDecode(String s) {
    var padded = s;
    while (padded.length % 4 != 0) {
      padded += '=';
    }
    return Uint8List.fromList(base64Url.decode(padded));
  }

  Future<Uint8List> _x25519PublicFromSecret(Uint8List sk) async {
    final algo = X25519();
    // cryptography's X25519 requires KeyPair construction from a seed;
    // to keep this file free of ad-hoc curve arithmetic we let the
    // library generate the keypair and export both halves consistently.
    // The `sk` bytes we passed in are used verbatim as the KeyPair seed.
    final pair = await algo.newKeyPairFromSeed(sk);
    final pk = await pair.extractPublicKey();
    return Uint8List.fromList(pk.bytes);
  }

  Future<RegisterResult> registerVault({
    required String displayName,
    required String pin,
  }) async {
    await OpaqueClient.ready();

    final handleBytes = generateVaultHandle();
    final handleDisplay = vaultHandleToDisplay(handleBytes);
    final credentialId = vaultHandleCredentialId(handleBytes);

    final startResult = OpaqueClient.startRegistration(password: pin);

    final initResponse = await _post(
      '/auth/zk-register-init',
      {
        'vault_handle': handleDisplay,
        'ke1': startResult.registrationRequest,
      },
    );
    final ke2 = initResponse['ke2'] as String;

    final finishResult = OpaqueClient.finishRegistration(
      password: pin,
      registrationResponse: ke2,
      clientRegistrationState: startResult.clientRegistrationState,
      clientIdentifier: credentialId,
    );

    final kek = await _deriveKek(finishResult.exportKey);

    final mvkBytes = _randomBytes(_mvkBytes);
    final mvk = SecretKey(mvkBytes);

    final skVaultBytes = _randomBytes(_skVaultBytes);
    final skVault = SecretKey(skVaultBytes);
    final pkVaultPublic = await _x25519PublicFromSecret(skVaultBytes);

    final wrappedMvk = await _wrap(kek, mvkBytes);
    final wrappedSkVault = await _wrap(kek, skVaultBytes);

    final displayNameKey = await _deriveDisplayNameKey(mvk);
    final displayNameCiphertext = await _wrap(
      displayNameKey,
      Uint8List.fromList(utf8.encode(displayName)),
    );

    final finalizeResponse = await _post(
      '/auth/zk-register-finalize',
      {
        'vault_handle': handleDisplay,
        'ke3': finishResult.registrationRecord,
        'wrapped_mvk': _b64urlEncode(wrappedMvk),
        'wrapped_sk_vault': _b64urlEncode(wrappedSkVault),
        'pk_vault_public': _b64urlEncode(pkVaultPublic),
        'display_name_ciphertext': _b64urlEncode(displayNameCiphertext),
        'acknowledged_irrecoverable': true,
      },
    );

    return RegisterResult(
      vaultId: finalizeResponse['vault_id'] as String,
      vaultHandle: handleDisplay,
      sessionToken: finalizeResponse['session_token'] as String,
      mvk: mvk,
      skVaultPrivate: skVault,
      pkVaultPublic: pkVaultPublic,
      displayName: displayName,
    );
  }

  Future<LoginResult> loginVault({
    required String vaultHandle,
    required String pin,
  }) async {
    await OpaqueClient.ready();

    final handleBytes = vaultHandleFromDisplay(vaultHandle);
    final handleDisplay = vaultHandleToDisplay(handleBytes);
    final credentialId = vaultHandleCredentialId(handleBytes);

    final start = OpaqueClient.startLogin(password: pin);

    final initResponse = await _post(
      '/auth/zk-login-init',
      {
        'vault_handle': handleDisplay,
        'ke1': start.startLoginRequest,
      },
    );
    final ke2 = initResponse['ke2'] as String;
    final slotId = initResponse['slot_id'] as String;

    final finish = OpaqueClient.finishLogin(
      clientLoginState: start.clientLoginState,
      loginResponse: ke2,
      password: pin,
      clientIdentifier: credentialId,
    );

    final finalizeResponse = await _post(
      '/auth/zk-login-finalize',
      {
        'slot_id': slotId,
        'ke3': finish.finishLoginRequest,
      },
    );

    final kek = await _deriveKek(finish.exportKey);
    final wrappedMvk =
        _b64urlDecode(finalizeResponse['wrapped_mvk'] as String);
    final wrappedSkVault =
        _b64urlDecode(finalizeResponse['wrapped_sk_vault'] as String);
    final displayNameCt = _b64urlDecode(
      finalizeResponse['display_name_ciphertext'] as String,
    );

    final mvkBytes = await _unwrap(kek, wrappedMvk);
    final mvk = SecretKey(mvkBytes);
    final skVaultBytes = await _unwrap(kek, wrappedSkVault);
    final skVault = SecretKey(skVaultBytes);

    final displayNameKey = await _deriveDisplayNameKey(mvk);
    final displayName = utf8.decode(await _unwrap(displayNameKey, displayNameCt));

    return LoginResult(
      vaultId: finalizeResponse['vault_id'] as String,
      vaultHandle: handleDisplay,
      sessionToken: finalizeResponse['session_token'] as String,
      mvk: mvk,
      skVaultPrivate: skVault,
      displayName: displayName,
    );
  }

  /// Transparent legacy adoption. Called AFTER the legacy /auth/login
  /// has issued a session token and the client has the legacy
  /// vault_key in memory. Mints the ZK state, uploads it, and the
  /// server atomically clears the legacy pin_salt/pin_verifier.
  ///
  /// legacyVaultKeyBytes is the raw 32 bytes derived by legacy PBKDF2
  /// on the client; we ADOPT it as MVK so nothing needs re-encryption.
  Future<AdoptResult> adoptLegacyVault({
    required String legacyDisplayName,
    required String pin,
    required Uint8List legacyVaultKeyBytes,
    required String currentSessionToken,
  }) async {
    await OpaqueClient.ready();

    final handleBytes = generateVaultHandle();
    final handleDisplay = vaultHandleToDisplay(handleBytes);
    final credentialId = vaultHandleCredentialId(handleBytes);

    final regStart = OpaqueClient.startRegistration(password: pin);

    final initResponse = await _post(
      '/auth/zk-register-init',
      {
        'vault_handle': handleDisplay,
        'ke1': regStart.registrationRequest,
      },
    );
    final ke2 = initResponse['ke2'] as String;

    final regFinish = OpaqueClient.finishRegistration(
      password: pin,
      registrationResponse: ke2,
      clientRegistrationState: regStart.clientRegistrationState,
      clientIdentifier: credentialId,
    );

    final kek = await _deriveKek(regFinish.exportKey);

    // Adopt the LEGACY vault_key as MVK — zero data re-encryption.
    final mvk = SecretKey(legacyVaultKeyBytes);

    final skVaultBytes = _randomBytes(_skVaultBytes);
    final pkVaultPublic = await _x25519PublicFromSecret(skVaultBytes);

    final wrappedMvk = await _wrap(kek, legacyVaultKeyBytes);
    final wrappedSkVault = await _wrap(kek, skVaultBytes);

    final displayNameKey = await _deriveDisplayNameKey(mvk);
    final displayNameCiphertext = await _wrap(
      displayNameKey,
      Uint8List.fromList(utf8.encode(legacyDisplayName)),
    );

    await _post(
      '/auth/zk-adopt',
      {
        'vault_handle': handleDisplay,
        'opaque_registration_record': regFinish.registrationRecord,
        'wrapped_mvk': _b64urlEncode(wrappedMvk),
        'wrapped_sk_vault': _b64urlEncode(wrappedSkVault),
        'pk_vault_public': _b64urlEncode(pkVaultPublic),
        'display_name_ciphertext': _b64urlEncode(displayNameCiphertext),
      },
      bearerToken: currentSessionToken,
    );

    return AdoptResult(handleDisplay);
  }
}
