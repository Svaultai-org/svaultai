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

import 'opaque_client.dart' if (dart.library.io) 'opaque_client_stub.dart';
import 'vault_handle.dart';

const int _mvkBytes = 32;
const int _skVaultBytes = 32;
const int _aesGcmNonceBytes = 12;

/// Legacy PIN-verifier constants.
///
/// The server-side check in ``vault_core.verify_vault_pin`` decrypts
/// ``pin_verifier`` with a PBKDF2-HMAC-SHA256 key derived from
/// (pin, base64decode(pin_salt), kdfIterations) and expects the exact
/// plaintext ``vaultai_pin_ok``. We derive both fields client-side
/// during ZK registration so that endpoints which still cross-check
/// the legacy PIN work for ZK-adopted accounts. The server never
/// sees the plaintext PIN.
const String _pinVerifierPlaintext = 'vaultai_pin_ok';
const int _pinSaltBytes = 16;
const int _pinKdfIterations = 600000;

final Hkdf _hkdf = Hkdf(
  hmac: Hmac.sha256(),
  outputLength: 32,
);

final AesGcm _aesGcm = AesGcm.with256bits();

final Pbkdf2 _pinKdf = Pbkdf2(
  macAlgorithm: Hmac.sha256(),
  iterations: _pinKdfIterations,
  bits: 256,
);

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

  /// Server-authoritative user-chosen vault name (product-facing
  /// identity for both the vault and the AI keeper). Null when
  /// the vaults row is not yet backfilled after migration 0031;
  /// the caller falls back to the user's locally-typed value or,
  /// failing that, the neutral "VaultAI" fallback rendered by
  /// downstream UI + prompt sites.
  final String? vaultName;
  LoginResult({
    required this.vaultId,
    required this.vaultHandle,
    required this.sessionToken,
    required this.mvk,
    required this.skVaultPrivate,
    required this.displayName,
    this.vaultName,
  });
}

class AdoptResult {
  final String newVaultHandle;
  AdoptResult(this.newVaultHandle);
}

const String zkRepairBranchPreserveExistingKey = 'preserve_existing_key';
const String zkRepairBranchRotateNewKey = 'rotate_new_key';

class ZkRepairResult {
  final String vaultId;
  final String vaultHandle;
  final SecretKey mvk;
  final SecretKey skVaultPrivate;
  final Uint8List pkVaultPublic;
  final String branch;
  final bool requiresOwnerReencryption;
  final int reencryptionRequiredCount;

  ZkRepairResult({
    required this.vaultId,
    required this.vaultHandle,
    required this.mvk,
    required this.skVaultPrivate,
    required this.pkVaultPublic,
    required this.branch,
    required this.requiresOwnerReencryption,
    required this.reencryptionRequiredCount,
  });

  bool get preservedExistingKey => branch == zkRepairBranchPreserveExistingKey;
}

/// Callback that POSTs the given ZK auth-endpoint JSON body and
/// returns the parsed JSON. Extracted so widget tests can inject a
/// fake without touching the network.
typedef ZkHttpPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body, {
  String? bearerToken,
});

class ZkClientRegistrationStart {
  final String clientRegistrationState;
  final String registrationRequest;
  const ZkClientRegistrationStart(
    this.clientRegistrationState,
    this.registrationRequest,
  );
}

class ZkClientRegistrationFinish {
  final String registrationRecord;
  final String exportKey;
  final String? serverStaticPublicKey;
  const ZkClientRegistrationFinish(
    this.registrationRecord,
    this.exportKey,
    this.serverStaticPublicKey,
  );
}

class ZkClientLoginStart {
  final String clientLoginState;
  final String startLoginRequest;
  const ZkClientLoginStart(this.clientLoginState, this.startLoginRequest);
}

class ZkClientLoginFinish {
  final String finishLoginRequest;
  final String sessionKey;
  final String exportKey;
  final String? serverStaticPublicKey;
  const ZkClientLoginFinish(
    this.finishLoginRequest,
    this.sessionKey,
    this.exportKey,
    this.serverStaticPublicKey,
  );
}

abstract class ZkOpaqueClient {
  Future<void> ready();
  ZkClientRegistrationStart startRegistration({required String password});
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  });
  ZkClientLoginStart startLogin({required String password});
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  });
}

class DefaultZkOpaqueClient implements ZkOpaqueClient {
  const DefaultZkOpaqueClient();

  @override
  Future<void> ready() => OpaqueClient.ready();

  @override
  ZkClientRegistrationStart startRegistration({required String password}) {
    final start = OpaqueClient.startRegistration(password: password);
    return ZkClientRegistrationStart(
      start.clientRegistrationState,
      start.registrationRequest,
    );
  }

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final finish = OpaqueClient.finishRegistration(
      password: password,
      registrationResponse: registrationResponse,
      clientRegistrationState: clientRegistrationState,
      clientIdentifier: clientIdentifier,
      serverIdentifier: serverIdentifier,
    );
    return ZkClientRegistrationFinish(
      finish.registrationRecord,
      finish.exportKey,
      finish.serverStaticPublicKey,
    );
  }

  @override
  ZkClientLoginStart startLogin({required String password}) {
    final start = OpaqueClient.startLogin(password: password);
    return ZkClientLoginStart(
      start.clientLoginState,
      start.startLoginRequest,
    );
  }

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final finish = OpaqueClient.finishLogin(
      clientLoginState: clientLoginState,
      loginResponse: loginResponse,
      password: password,
      clientIdentifier: clientIdentifier,
      serverIdentifier: serverIdentifier,
    );
    return ZkClientLoginFinish(
      finish.finishLoginRequest,
      finish.sessionKey,
      finish.exportKey,
      finish.serverStaticPublicKey,
    );
  }
}

class ZkAuthService {
  final ZkHttpPost _post;
  final ZkOpaqueClient _opaque;
  ZkAuthService(this._post, {ZkOpaqueClient? opaque})
      : _opaque = opaque ?? const DefaultZkOpaqueClient();

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

  /// Client-side derivation of the legacy PIN-verifier envelope.
  ///
  /// Format matches ``vault_core.encrypt_message``:
  ///   base64(nonce(12) || AES-GCM ciphertext || tag(16))
  /// keyed by ``PBKDF2-HMAC-SHA256(pin, salt, iterations=600_000)``.
  /// The two returned strings map 1:1 to the ``pin_salt`` /
  /// ``pin_verifier`` columns in the ``vaults`` table.
  Future<({String pinSalt, String pinVerifier, int kdfIterations})>
      _deriveLegacyPinVerifier(String pin) async {
    final saltBytes = _randomBytes(_pinSaltBytes);
    final key = await _pinKdf.deriveKey(
      secretKey: SecretKey(utf8.encode(pin)),
      nonce: saltBytes,
    );
    final nonce = _randomBytes(_aesGcmNonceBytes);
    final secretBox = await _aesGcm.encrypt(
      utf8.encode(_pinVerifierPlaintext),
      secretKey: key,
      nonce: nonce,
    );
    final envelope = BytesBuilder();
    envelope.add(nonce);
    envelope.add(secretBox.cipherText);
    envelope.add(secretBox.mac.bytes);
    return (
      pinSalt: base64.encode(saltBytes),
      pinVerifier: base64.encode(envelope.toBytes()),
      kdfIterations: _pinKdfIterations,
    );
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
    required String vaultName,
    required String displayName,
    required String pin,
  }) async {
    await _opaque.ready();

    // Deterministic handle from the vault name. Same vault name on
    // any device -> same handle -> the DB's UNIQUE index on
    // vault_handle rejects duplicates.
    final handleBytes = deriveVaultHandleFromUsername(vaultName);
    final handleDisplay = vaultHandleToDisplay(handleBytes);

    // Client-derived 32-byte lookup identifier. Sent as base64url
    // so the backend can enforce derivation-version-independent
    // uniqueness (partial UNIQUE on vaults.username_lookup_v1).
    // See vault_handle.dart::deriveUsernameLookupV1 and
    // migration 0030.
    final lookupV1 = deriveUsernameLookupV1(vaultName);
    final lookupV1B64 = vaultHandleB64Url(lookupV1);

    final startResult = _opaque.startRegistration(password: pin);

    final initResponse = await _post(
      '/auth/zk-register-init',
      {
        'vault_handle': handleDisplay,
        'ke1': startResult.registrationRequest,
        'username_lookup': lookupV1B64,
      },
    );
    final ke2 = initResponse['ke2'] as String;

    final finishResult = _opaque.finishRegistration(
      password: pin,
      registrationResponse: ke2,
      clientRegistrationState: startResult.clientRegistrationState,
      // No AKE identifiers are passed. RFC 9807 requires client and
      // server to agree on the OPAQUE AKE identifier parameters;
      // our Rust backend calls ServerLoginParameters::default() at
      // login-start and login-finish (both identifiers = None), and
      // the proven-working interop test at
      // test_opaque_wire_interop.py also omits them. The pre-fix
      // build passed the credential-id string as a client-side
      // identifier which baked a mismatch into the OPAQUE envelope
      // and made client.finishLogin silently return undefined on
      // every subsequent login attempt — that is the "Wrong username
      // or PIN" symptom fresh accounts hit on 7bcaf81.
      //
      // The OPAQUE OPRF still binds the account via the SERVER-side
      // credential_identifier (see auth_zk_routes.py's
      // _opaque_credential_id) — that pipe is unchanged and stays
      // tied to the deterministic vault_handle bytes.
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

    final legacyPin = await _deriveLegacyPinVerifier(pin);

    // Send the user-typed vault_name plaintext so the backend can
    // store it authoritatively in vaults.vault_name for LLM prompt
    // injection + /auth/me responses. Server normalizes on
    // receive; no random-hex placeholder is generated anymore.
    // Privacy classification per 2026-07-20 clarification: this
    // value is server-visible product metadata (not a private
    // credential); the private login lookup remains
    // username_lookup (32 opaque bytes).
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
        'pin_salt': legacyPin.pinSalt,
        'pin_verifier': legacyPin.pinVerifier,
        'kdf_iterations': legacyPin.kdfIterations,
        'username_lookup': lookupV1B64,
        'vault_name': vaultName,
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

  /// Log in by username (post-2026-07-19 corrective release) OR by
  /// raw vault handle (legacy path). ``username`` takes precedence.
  ///
  /// Rationale: the deterministic derivation makes ``username`` the
  /// only credential the user needs to type. The ``vaultHandle``
  /// argument stays because a handful of internal call sites still
  /// pass a saved handle (e.g. adopted legacy accounts that persisted
  /// their handle in SharedPreferences).
  ///
  /// [onStep] is a step-completion callback for diagnostic tracing.
  /// After each risky sub-step finishes cleanly, the callback is
  /// invoked with the step name. If the login later throws, the
  /// caller knows the LAST completed step — so the failing step is
  /// (last-completed + 1). No PIN, ciphertext, or session material
  /// ever crosses this boundary; only short static step tags.
  Future<LoginResult> loginVault({
    String? vaultName,
    String? vaultHandle,
    required String pin,
    void Function(String stepDone)? onStep,
  }) async {
    void step(String s) {
      // Always print — this is the ONE place we can rely on to see
      // pre-HTTP progress in a production browser console. Release
      // builds silence ``print`` but ``debugPrint`` fires; the tag
      // ``[zk-login-step]`` is greppable in the DevTools console.
      // ignore: avoid_print
      print('[zk-login-step] $s');
      try {
        onStep?.call(s);
      } catch (_) {
        // Never let a callback error mask the real failure.
      }
    }

    step('begin');
    await _opaque.ready();
    step('opaque_ready');

    final Uint8List handleBytes;
    String? usernameLookupB64;
    if (vaultName != null && vaultName.isNotEmpty) {
      usernameLookupB64 = vaultHandleB64Url(deriveUsernameLookupV1(vaultName));
      handleBytes = deriveVaultHandleFromUsername(vaultName);
    } else if (vaultHandle != null && vaultHandle.isNotEmpty) {
      handleBytes = vaultHandleFromDisplay(vaultHandle);
    } else {
      throw ArgumentError(
        'loginVault requires either vaultName or vaultHandle',
      );
    }
    step('derive_handle');

    final handleDisplay = vaultHandleToDisplay(handleBytes);
    step('handle_encoded');

    Future<({ZkClientLoginFinish finish, String slotId})> finishLoginAttempt({
      String? clientIdentifier,
      required bool legacy,
    }) async {
      final start = _opaque.startLogin(password: pin);
      step(legacy ? 'opaque_legacy_start_login' : 'opaque_start_login');

      // Include ``username_lookup`` (32-byte client-derived id) when
      // we have it: the server uses it as a fallback lookup key when
      // the deterministic handle bytes don't hit a row, and, with
      // conflict detection, opportunistically backfills the
      // username_lookup_v1 column on legacy rows so subsequent
      // duplicate registrations collide on the partial UNIQUE index.
      // The raw username is NEVER sent to the server.
      final initResponse = await _post(
        '/auth/zk-login-init',
        {
          'vault_handle': handleDisplay,
          'ke1': start.startLoginRequest,
          if (usernameLookupB64 != null) 'username_lookup': usernameLookupB64,
        },
      );
      step(legacy ? 'opaque_legacy_post_login_init' : 'post_login_init');

      final ke2 = initResponse['ke2'] as String;
      final slotId = initResponse['slot_id'] as String;

      try {
        final finish = _opaque.finishLogin(
          clientLoginState: start.clientLoginState,
          loginResponse: ke2,
          password: pin,
          clientIdentifier: clientIdentifier,
        );
        step(legacy ? 'opaque_legacy_finish_success' : 'opaque_finish_login');
        return (finish: finish, slotId: slotId);
      } on OpaqueAuthenticationFailed {
        if (legacy) {
          step('opaque_legacy_finish_rejected');
        }
        rethrow;
      }
    }

    late ZkClientLoginFinish finish;
    late String slotId;
    try {
      final modern = await finishLoginAttempt(
        clientIdentifier: null,
        legacy: false,
      );
      finish = modern.finish;
      slotId = modern.slotId;
    } on OpaqueAuthenticationFailed {
      // Compatibility for accounts adopted/registered by the short-lived
      // pre-f4d47a1 frontend: those records were created with
      // identifiers.client = vaultHandleCredentialId(handleBytes). A failed
      // finishLogin may consume the client state, so the retry must start a
      // fresh OPAQUE exchange and obtain a new server slot.
      step('opaque_finish_login_default_rejected');
      step('opaque_legacy_retry_begin');
      final legacy = await finishLoginAttempt(
        clientIdentifier: vaultHandleCredentialId(handleBytes),
        legacy: true,
      );
      finish = legacy.finish;
      slotId = legacy.slotId;
    }

    // Opportunistic backfill: for accounts registered before
    // migration 0031 whose vaults.vault_name was NULLed by the
    // backfill migration (they used to hold a random-hex
    // placeholder), send the user's typed vault_name so the server
    // can populate the column. The server silently skips the write
    // if the row already has a non-NULL value or if the value
    // would collide with another vault — login still succeeds.
    final finalizeResponse = await _post(
      '/auth/zk-login-finalize',
      {
        'slot_id': slotId,
        'ke3': finish.finishLoginRequest,
        if (vaultName != null && vaultName.isNotEmpty) 'vault_name': vaultName,
      },
    );
    step('post_login_finalize');

    final kek = await _deriveKek(finish.exportKey);
    final wrappedMvk = _b64urlDecode(finalizeResponse['wrapped_mvk'] as String);
    final wrappedSkVault =
        _b64urlDecode(finalizeResponse['wrapped_sk_vault'] as String);
    final displayNameCt = _b64urlDecode(
      finalizeResponse['display_name_ciphertext'] as String,
    );
    step('decode_response');

    final mvkBytes = await _unwrap(kek, wrappedMvk);
    final mvk = SecretKey(mvkBytes);
    final skVaultBytes = await _unwrap(kek, wrappedSkVault);
    final skVault = SecretKey(skVaultBytes);
    step('unwrap_mvk');

    final displayNameKey = await _deriveDisplayNameKey(mvk);
    final displayName =
        utf8.decode(await _unwrap(displayNameKey, displayNameCt));
    step('unwrap_display_name');

    final authenticatedHandle =
        finalizeResponse['vault_handle'] as String? ?? handleDisplay;

    return LoginResult(
      vaultId: finalizeResponse['vault_id'] as String,
      vaultHandle: authenticatedHandle,
      sessionToken: finalizeResponse['session_token'] as String,
      mvk: mvk,
      skVaultPrivate: skVault,
      displayName: displayName,
      vaultName: finalizeResponse['vault_name'] as String?,
    );
  }

  Future<ZkRepairResult> repairVaultOpaqueRecord({
    required String vaultHandle,
    required String pin,
    required SecretKey mvk,
    required String displayName,
    required String currentSessionToken,
    SecretKey? existingSkVaultPrivate,
  }) async {
    await _opaque.ready();

    final handleBytes = vaultHandleFromDisplay(vaultHandle);
    final handleDisplay = vaultHandleToDisplay(handleBytes);

    final regStart = _opaque.startRegistration(password: pin);
    final initResponse = await _post(
      '/auth/zk-repair-init',
      {
        'vault_handle': handleDisplay,
        'ke1': regStart.registrationRequest,
      },
      bearerToken: currentSessionToken,
    );

    final regFinish = _opaque.finishRegistration(
      password: pin,
      registrationResponse: initResponse['ke2'] as String,
      clientRegistrationState: regStart.clientRegistrationState,
      // No clientIdentifier: repair writes the modern production format.
    );

    final kek = await _deriveKek(regFinish.exportKey);
    final mvkBytes = Uint8List.fromList(await mvk.extractBytes());
    if (mvkBytes.length != _mvkBytes) {
      throw StateError('repair MVK has invalid length');
    }

    late final Uint8List skVaultBytes;
    late final String branch;
    if (existingSkVaultPrivate != null) {
      skVaultBytes =
          Uint8List.fromList(await existingSkVaultPrivate.extractBytes());
      if (skVaultBytes.length != _skVaultBytes) {
        throw StateError('repair sk_vault has invalid length');
      }
      branch = zkRepairBranchPreserveExistingKey;
    } else {
      skVaultBytes = _randomBytes(_skVaultBytes);
      branch = zkRepairBranchRotateNewKey;
    }
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
      '/auth/zk-repair-finalize',
      {
        'vault_handle': handleDisplay,
        'ke3': regFinish.registrationRecord,
        'wrapped_mvk': _b64urlEncode(wrappedMvk),
        'wrapped_sk_vault': _b64urlEncode(wrappedSkVault),
        'pk_vault_public': _b64urlEncode(pkVaultPublic),
        'display_name_ciphertext': _b64urlEncode(displayNameCiphertext),
        'repair_branch': branch,
      },
      bearerToken: currentSessionToken,
    );

    return ZkRepairResult(
      vaultId: finalizeResponse['vault_id'] as String,
      vaultHandle: finalizeResponse['vault_handle'] as String? ?? handleDisplay,
      mvk: mvk,
      skVaultPrivate: skVault,
      pkVaultPublic: pkVaultPublic,
      branch: finalizeResponse['branch'] as String? ?? branch,
      requiresOwnerReencryption:
          finalizeResponse['requires_owner_reencryption'] == true,
      reencryptionRequiredCount:
          (finalizeResponse['reencryption_required_count'] as num?)?.toInt() ??
              0,
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
    await _opaque.ready();

    final handleBytes = generateVaultHandle();
    final handleDisplay = vaultHandleToDisplay(handleBytes);

    final regStart = _opaque.startRegistration(password: pin);

    final initResponse = await _post(
      '/auth/zk-register-init',
      {
        'vault_handle': handleDisplay,
        'ke1': regStart.registrationRequest,
      },
    );
    final ke2 = initResponse['ke2'] as String;

    final regFinish = _opaque.finishRegistration(
      password: pin,
      registrationResponse: ke2,
      clientRegistrationState: regStart.clientRegistrationState,
      // See registerVault: no identifiers.client in the OPAQUE AKE —
      // must match the backend's ServerLoginParameters::default().
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
