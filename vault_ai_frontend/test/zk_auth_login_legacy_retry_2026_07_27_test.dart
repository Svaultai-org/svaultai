import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/opaque_client_native.dart'
    show OpaqueAuthenticationFailed;
import 'package:vault_ai_frontend/services/vault_handle.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

const String _goodPin = '123456';
const String _vaultId = 'vault-beneficiary';

final Uint8List _exportKeyBytes =
    Uint8List.fromList(List<int>.generate(32, (i) => i + 1));
final String _exportKeyB64 = vaultHandleB64Url(_exportKeyBytes);

String _b64url(Uint8List raw) => vaultHandleB64Url(raw);

Future<SecretKey> _deriveKek() {
  return Hkdf(
    hmac: Hmac.sha256(),
    outputLength: 32,
  ).deriveKey(
    secretKey: SecretKey(_exportKeyBytes),
    nonce: const [],
    info: utf8.encode('vaultai.kek.v1'),
  );
}

Future<SecretKey> _deriveDisplayNameKey(SecretKey mvk) async {
  final mvkBytes = await mvk.extractBytes();
  return Hkdf(
    hmac: Hmac.sha256(),
    outputLength: 32,
  ).deriveKey(
    secretKey: SecretKey(mvkBytes),
    nonce: const [],
    info: utf8.encode('vaultai.display.v1'),
  );
}

Future<Uint8List> _wrap(SecretKey key, List<int> plaintext) async {
  final nonce = Uint8List(12);
  final box = await AesGcm.with256bits().encrypt(
    plaintext,
    secretKey: key,
    nonce: nonce,
  );
  final out = BytesBuilder()
    ..addByte(0x01)
    ..add(nonce)
    ..add(box.cipherText)
    ..add(box.mac.bytes);
  return out.toBytes();
}

Future<Map<String, dynamic>> _finalizeResponse(String vaultHandle) async {
  final mvkBytes = Uint8List.fromList(List<int>.filled(32, 7));
  final skBytes = Uint8List.fromList(List<int>.filled(32, 9));
  final kek = await _deriveKek();
  final mvk = SecretKey(mvkBytes);
  final displayKey = await _deriveDisplayNameKey(mvk);
  return {
    'vault_id': _vaultId,
    'vault_handle': vaultHandle,
    'session_token': 'session-token',
    'wrapped_mvk': _b64url(await _wrap(kek, mvkBytes)),
    'wrapped_sk_vault': _b64url(await _wrap(kek, skBytes)),
    'display_name_ciphertext': _b64url(
      await _wrap(displayKey, utf8.encode('Beneficiary')),
    ),
    'vault_name': 'beneficiary',
  };
}

class _StatefulOpaqueClient implements ZkOpaqueClient {
  _StatefulOpaqueClient({
    required this.modernSucceeds,
    required this.legacySucceeds,
    required this.expectedLegacyIdentifier,
  });

  final bool modernSucceeds;
  final bool legacySucceeds;
  final String expectedLegacyIdentifier;
  final List<String> calls = <String>[];
  final Set<String> consumedStates = <String>{};
  int startCount = 0;

  @override
  Future<void> ready() async {
    calls.add('ready');
  }

  @override
  ZkClientLoginStart startLogin({required String password}) {
    startCount += 1;
    calls.add('start:$startCount');
    return ZkClientLoginStart('state-$startCount', 'ke1-$startCount');
  }

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    final mode = clientIdentifier == null ? 'modern' : 'legacy';
    calls.add('finish:$mode:$clientLoginState:$loginResponse');

    if (password != _goodPin) {
      consumedStates.add(clientLoginState);
      throw OpaqueAuthenticationFailed('finish_login');
    }
    if (consumedStates.contains(clientLoginState)) {
      throw OpaqueAuthenticationFailed('finish_login');
    }
    if (clientIdentifier == null) {
      if (modernSucceeds) {
        return ZkClientLoginFinish(
            'ke3-modern', 'session-key', _exportKeyB64, null);
      }
      consumedStates.add(clientLoginState);
      throw OpaqueAuthenticationFailed('finish_login');
    }
    expect(clientIdentifier, expectedLegacyIdentifier);
    if (!legacySucceeds) {
      consumedStates.add(clientLoginState);
      throw OpaqueAuthenticationFailed('finish_login');
    }
    return ZkClientLoginFinish(
        'ke3-legacy', 'session-key', _exportKeyB64, null);
  }

  @override
  ZkClientRegistrationStart startRegistration({required String password}) {
    throw UnsupportedError('registration is outside this login retry test');
  }

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    throw UnsupportedError('registration is outside this login retry test');
  }
}

class _ZkHttpHarness {
  _ZkHttpHarness({required this.vaultHandle});

  final String vaultHandle;
  final List<String> calls = <String>[];
  final List<Map<String, dynamic>> finalizeBodies = <Map<String, dynamic>>[];
  int initCount = 0;

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body, {
    String? bearerToken,
  }) async {
    calls.add(path);
    if (path == '/auth/zk-login-init') {
      initCount += 1;
      return {
        'slot_id': 'slot-$initCount',
        'ke2': 'ke2-$initCount',
      };
    }
    if (path == '/auth/zk-login-finalize') {
      finalizeBodies.add(Map<String, dynamic>.from(body));
      return _finalizeResponse(vaultHandle);
    }
    throw StateError('unexpected path $path');
  }
}

void main() {
  group('ZkAuthService legacy OPAQUE login compatibility', () {
    late String vaultHandle;
    late String legacyIdentifier;

    setUp(() {
      final handleBytes = Uint8List.fromList(List<int>.filled(15, 5));
      vaultHandle = vaultHandleToDisplay(handleBytes);
      legacyIdentifier = vaultHandleCredentialId(handleBytes);
    });

    test('legacy records use a fresh second OPAQUE exchange before finalize',
        () async {
      final opaque = _StatefulOpaqueClient(
        modernSucceeds: false,
        legacySucceeds: true,
        expectedLegacyIdentifier: legacyIdentifier,
      );
      final http = _ZkHttpHarness(vaultHandle: vaultHandle);
      final steps = <String>[];

      final result = await ZkAuthService(
        http.post,
        opaque: opaque,
      ).loginVault(
        vaultHandle: vaultHandle,
        pin: _goodPin,
        onStep: steps.add,
      );

      expect(result.vaultId, _vaultId);
      expect(opaque.calls, [
        'ready',
        'start:1',
        'finish:modern:state-1:ke2-1',
        'start:2',
        'finish:legacy:state-2:ke2-2',
      ]);
      expect(http.calls, [
        '/auth/zk-login-init',
        '/auth/zk-login-init',
        '/auth/zk-login-finalize',
      ]);
      expect(http.finalizeBodies.single['slot_id'], 'slot-2');
      expect(http.finalizeBodies.single['ke3'], 'ke3-legacy');
      expect(
          steps,
          containsAllInOrder([
            'opaque_start_login',
            'post_login_init',
            'opaque_finish_login_default_rejected',
            'opaque_legacy_retry_begin',
            'opaque_legacy_start_login',
            'opaque_legacy_post_login_init',
            'opaque_legacy_finish_success',
            'post_login_finalize',
          ]));
    });

    test('modern records do not use the legacy retry', () async {
      final opaque = _StatefulOpaqueClient(
        modernSucceeds: true,
        legacySucceeds: true,
        expectedLegacyIdentifier: legacyIdentifier,
      );
      final http = _ZkHttpHarness(vaultHandle: vaultHandle);
      final steps = <String>[];

      final result = await ZkAuthService(
        http.post,
        opaque: opaque,
      ).loginVault(
        vaultHandle: vaultHandle,
        pin: _goodPin,
        onStep: steps.add,
      );

      expect(result.vaultId, _vaultId);
      expect(opaque.calls, [
        'ready',
        'start:1',
        'finish:modern:state-1:ke2-1',
      ]);
      expect(http.finalizeBodies.single['slot_id'], 'slot-1');
      expect(steps, isNot(contains('opaque_legacy_retry_begin')));
    });

    test('wrong PIN never finalizes', () async {
      final opaque = _StatefulOpaqueClient(
        modernSucceeds: false,
        legacySucceeds: true,
        expectedLegacyIdentifier: legacyIdentifier,
      );
      final http = _ZkHttpHarness(vaultHandle: vaultHandle);

      await expectLater(
        ZkAuthService(http.post, opaque: opaque).loginVault(
          vaultHandle: vaultHandle,
          pin: '000000',
        ),
        throwsA(isA<OpaqueAuthenticationFailed>()),
      );

      expect(http.finalizeBodies, isEmpty);
      expect(http.calls, [
        '/auth/zk-login-init',
        '/auth/zk-login-init',
      ]);
    });
  });
}
