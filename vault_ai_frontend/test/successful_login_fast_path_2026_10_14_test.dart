import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart'
    show debugDefaultTargetPlatformOverride, TargetPlatform;
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show VaultCryptoContext, VaultCryptoRegistry, deriveAndInstallCryptoContext;
import 'package:vault_ai_frontend/services/vault_handle.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

const _vaultId = 'synthetic-login-vault';
final _salt = base64Encode(List<int>.filled(16, 7));
final _exportKey = Uint8List.fromList(List<int>.filled(32, 9));

Map<String, dynamic> _metadata() => {
      'vault_id': _vaultId,
      'vault_name': null,
      'pin_salt': _salt,
      'kdf_iterations': 600000,
      'total_bytes': 0,
      'created_at': '2026-10-14T00:00:00Z',
    };

LoginResult _login({bool trust = false, Object? metadata}) => LoginResult(
      vaultId: _vaultId,
      vaultHandle: vaultHandleToDisplay(Uint8List(15)),
      sessionToken: 'synthetic-session',
      mvk: SecretKey(List<int>.filled(32, 1)),
      skVaultPrivate: SecretKey(List<int>.filled(32, 2)),
      displayName: 'Synthetic',
      deviceTrustComplete: trust,
      vaultMeta: LoginVaultMeta.fromResponse(
        metadata,
        expectedVaultId: _vaultId,
      ),
    );

Future<LoginVaultMeta> _resolve(LoginResult login, List<String> requests,
        {Object? freshMetadata}) =>
    resolveLoginVaultMeta(
      loginResult: login,
      registerDevice: () async => requests.add('/devices/register'),
      afterDeviceReady: () async => requests.add('inheritance-ready'),
      fetchVaultMeta: () async {
        requests.add('/vault-meta');
        return Map<String, dynamic>.from(freshMetadata as Map? ?? _metadata());
      },
    );

class _Opaque implements ZkOpaqueClient {
  @override
  Future<void> ready() async {}

  @override
  ZkClientLoginStart startLogin({required String password}) =>
      const ZkClientLoginStart('synthetic-client-state', 'synthetic-ke1');

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) =>
      ZkClientLoginFinish('synthetic-ke3', 'synthetic-session-key',
          vaultHandleB64Url(_exportKey), null);

  @override
  ZkClientRegistrationStart startRegistration({required String password}) =>
      throw UnsupportedError('not a registration fixture');

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) =>
      throw UnsupportedError('not a registration fixture');
}

Future<Uint8List> _wrap(SecretKey key, List<int> plaintext) async {
  final box = await AesGcm.with256bits().encrypt(
    plaintext,
    secretKey: key,
    nonce: List<int>.filled(12, 0),
  );
  return (BytesBuilder()
        ..addByte(1)
        ..add(box.nonce)
        ..add(box.cipherText)
        ..add(box.mac.bytes))
      .toBytes();
}

Future<Map<String, dynamic>> _finalize() async {
  final hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
  final kek = await hkdf.deriveKey(
    secretKey: SecretKey(_exportKey),
    nonce: const [],
    info: utf8.encode('vaultai.kek.v1'),
  );
  final mvk = List<int>.filled(32, 1);
  final displayKey = await hkdf.deriveKey(
    secretKey: SecretKey(mvk),
    nonce: const [],
    info: utf8.encode('vaultai.display.v1'),
  );
  return {
    'vault_id': _vaultId,
    'vault_handle': vaultHandleToDisplay(Uint8List(15)),
    'session_token': 'synthetic-session',
    'wrapped_mvk': vaultHandleB64Url(await _wrap(kek, mvk)),
    'wrapped_sk_vault':
        vaultHandleB64Url(await _wrap(kek, List<int>.filled(32, 2))),
    'display_name_ciphertext':
        vaultHandleB64Url(await _wrap(displayKey, utf8.encode('Synthetic'))),
  };
}

void main() {
  group('Production web login request origin', () {
    for (final path in ['/auth/zk-login-init', '/auth/zk-login-finalize']) {
      test('$path uses the exact existing /api proxy prefix', () {
        final uri = zkLoginRequestUri(
          backendBaseUrl: 'https://api.svaultai.com',
          path: path,
          isWeb: true,
          pageUri: Uri.parse('https://app.svaultai.com/#/login'),
        );
        expect(uri.toString(), 'https://app.svaultai.com/api$path');
        expect(uri.path, '/api$path');
      });
    }

    test('native login retains the configured API host', () {
      expect(zkLoginRequestUri(
        backendBaseUrl: 'https://api.svaultai.com',
        path: '/auth/zk-login-init',
        isWeb: false,
        pageUri: Uri.parse('https://app.svaultai.com'),
      ).toString(), 'https://api.svaultai.com/auth/zk-login-init');
    });

    for (final origin in [
      'http://app.svaultai.com',
      'https://app.svaultai.com:444',
      'https://app.svaultai.com.attacker.example',
      'https://localhost',
      'https://custom.example',
      'https://user@app.svaultai.com',
    ]) {
      test('$origin retains the configured API host', () {
        expect(zkLoginRequestUri(
          backendBaseUrl: 'https://api.svaultai.com',
          path: '/auth/zk-login-init',
          isWeb: true,
          pageUri: Uri.parse(origin),
        ).toString(), 'https://api.svaultai.com/auth/zk-login-init');
      });
    }

    for (final backend in [
      'http://api.svaultai.com',
      'https://api.svaultai.com/',
      'https://api.svaultai.com:444',
      'https://api.svaultai.com.attacker.example',
      'http://localhost:8000',
      'https://custom.example',
    ]) {
      test('backend $backend retains its exact configured URL', () {
        expect(zkLoginRequestUri(
          backendBaseUrl: backend,
          path: '/auth/zk-login-init',
          isWeb: true,
          pageUri: Uri.parse('https://app.svaultai.com'),
        ).toString(), '$backend/auth/zk-login-init');
      });
    }

    for (final path in [
      '/auth/zk-register-init',
      '/auth/zk-register-finalize',
      '/auth/zk-repair-init',
      '/auth/zk-adopt',
      '/auth/login',
      '/auth/zk-login-init?alternate=true',
      '/auth/zk-login-init/',
    ]) {
      test('$path is outside the same-origin allowlist', () {
        expect(zkLoginRequestUri(
          backendBaseUrl: 'https://api.svaultai.com',
          path: path,
          isWeb: true,
          pageUri: Uri.parse('https://app.svaultai.com'),
        ).toString(), 'https://api.svaultai.com$path');
      });
    }
  });

  test('confirmed finalization removes two requests while retaining key unwrap',
      () async {
    final response = await _finalize()
      ..['device_trust_complete'] = true
      ..['vault_meta'] = _metadata();
    final requests = <String>[];
    final service = ZkAuthService(
      (path, body, {bearerToken}) async {
        requests.add(path);
        return path == '/auth/zk-login-init'
            ? {'slot_id': 'synthetic-slot', 'ke2': 'synthetic-ke2'}
            : response;
      },
      opaque: _Opaque(),
    );
    final login =
        await service.loginVault(vaultName: 'Synthetic', pin: '123456');
    final metadata = await _resolve(login, requests);
    expect(requests, [
      '/auth/zk-login-init',
      '/auth/zk-login-finalize',
      'inheritance-ready',
    ]);
    expect(metadata.pinSaltBase64, _salt);
    expect(metadata.kdfIterations, 600000);
    expect(await login.mvk.extractBytes(), List<int>.filled(32, 1));
    expect(await login.skVaultPrivate.extractBytes(), List<int>.filled(32, 2));
    expect(login.displayName, 'Synthetic');
  });

  for (final scenario in [
    'old-server',
    'unconfirmed-device',
    'missing-metadata'
  ]) {
    test('$scenario keeps registration and fresh metadata requests', () async {
      final requests = <String>[];
      final login = _login(
        trust: scenario == 'missing-metadata',
        metadata: scenario == 'unconfirmed-device' ? _metadata() : null,
      );
      final fresh = _metadata()
        ..['pin_salt'] = base64Encode(List<int>.filled(16, 8))
        ..['kdf_iterations'] = 100000;
      final metadata = await _resolve(login, requests, freshMetadata: fresh);
      expect(
          requests, ['/devices/register', 'inheritance-ready', '/vault-meta']);
      expect(metadata.pinSaltBase64, fresh['pin_salt']);
      expect(metadata.kdfIterations, 100000);
    });
  }

  test('unexpected trust types are never confirmation', () async {
    for (final trust in ['true', 1, null, false]) {
      final response = await _finalize()
        ..['device_trust_complete'] = trust
        ..['vault_meta'] = _metadata();
      final requests = <String>[];
      final service = ZkAuthService(
        (path, body, {bearerToken}) async => path == '/auth/zk-login-init'
            ? {'slot_id': 'synthetic-slot', 'ke2': 'synthetic-ke2'}
            : response,
        opaque: _Opaque(),
      );
      final login =
          await service.loginVault(vaultName: 'Synthetic', pin: '123456');
      await _resolve(login, requests);
      expect(
          requests, ['/devices/register', 'inheritance-ready', '/vault-meta']);
    }
  });

  test('invalid inline metadata falls back instead of becoming key parameters',
      () async {
    final invalid = <Object?>[
      null,
      [],
      'metadata',
      {},
      _metadata()..['vault_id'] = 'another-vault',
      _metadata()..remove('pin_salt'),
      _metadata()..['pin_salt'] = 123,
      _metadata()..['pin_salt'] = 'not-valid-base64!',
      _metadata()..['pin_salt'] = base64Encode([1]),
      _metadata()..['kdf_iterations'] = '600000',
      _metadata()..['kdf_iterations'] = 600000.5,
      _metadata()..['kdf_iterations'] = true,
      _metadata()..['kdf_iterations'] = 99999,
      _metadata()..['kdf_iterations'] = 2000001,
    ];
    for (final candidate in invalid) {
      final requests = <String>[];
      final meta =
          await _resolve(_login(trust: true, metadata: candidate), requests);
      expect(
          requests, ['/devices/register', 'inheritance-ready', '/vault-meta']);
      expect(meta.kdfIterations, 600000);
    }
  });

  test('invalid fallback data stops preparation before any context install',
      () async {
    var installed = false;
    final invalid = _metadata()..['vault_id'] = 'another-vault';
    final preparation = _resolve(_login(), [], freshMetadata: invalid)
        .then((_) => installed = true);
    await expectLater(preparation, throwsStateError);
    expect(installed, isFalse);
  });

  test('a session changed during derivation cannot overwrite its current key',
      () async {
    final previousPlatform = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.macOS;
    addTearDown(() => debugDefaultTargetPlatformOverride = previousPlatform);
    VaultCryptoRegistry.clear(reason: 'synthetic test');
    final existing = VaultCryptoContext(
      vaultId: 'current-vault',
      vaultName: 'Current',
      key: SecretKey(List<int>.filled(32, 4)),
      pin: '123456',
      saltBase64: _salt,
      iterations: 1000,
      generation: VaultCryptoRegistry.nextGeneration(),
      source: 'synthetic fixture',
    );
    expect(
        VaultCryptoRegistry.install(
          operationId: VaultCryptoRegistry.nextOperationId(),
          context: existing,
        ),
        isTrue);
    var stillCurrent = true;
    final pending = deriveAndInstallCryptoContext(
      vaultId: _vaultId,
      vaultName: 'Former',
      pin: '123456',
      pinSaltBase64: _salt,
      iterations: 1000,
      source: 'synthetic former session',
      canInstall: () => stillCurrent,
    );
    stillCurrent = false;
    expect(await pending, isNull);
    expect(VaultCryptoRegistry.current, same(existing));
    VaultCryptoRegistry.clear(reason: 'synthetic test complete');
  });
}
