import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

class _SyntheticOpaque implements ZkOpaqueClient {
  @override
  Future<void> ready() async {}

  @override
  ZkClientRegistrationStart startRegistration({required String password}) =>
      const ZkClientRegistrationStart('synthetic-state', 'synthetic-ke1');

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) => ZkClientRegistrationFinish(
        'synthetic-ke3',
        base64Url.encode(List<int>.filled(32, 7)).replaceAll('=', ''),
        null,
      );

  @override
  ZkClientLoginStart startLogin({required String password}) =>
      throw UnimplementedError();

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) => throw UnimplementedError();
}

void main() {
  test('ZK registration request matches the verifier-free build flag', () async {
    final bodies = <String, Map<String, dynamic>>{};
    final service = ZkAuthService(
      (path, body, {bearerToken}) async {
        bodies[path] = Map<String, dynamic>.from(body);
        if (path == '/auth/zk-register-init') {
          return <String, dynamic>{'ke2': 'synthetic-ke2'};
        }
        if (path == '/auth/zk-register-finalize') {
          return <String, dynamic>{
            'vault_id': 'synthetic-vault-id',
            'session_token': 'synthetic-session',
          };
        }
        throw StateError('Unexpected request');
      },
      opaque: _SyntheticOpaque(),
    );

    await service.registerVault(
      vaultName: 'Synthetic QA Vault',
      displayName: 'Synthetic QA',
      pin: '123456',
    );

    final init = bodies['/auth/zk-register-init']!;
    final finalize = bodies['/auth/zk-register-finalize']!;
    expect(init.containsKey('pin'), isFalse);
    expect(finalize.containsKey('pin'), isFalse);
    for (final body in [init, finalize]) {
      expect(body.containsKey('vault_name'), isFalse);
      expect(jsonEncode(body), isNot(contains('Synthetic QA Vault')));
    }
    expect(finalize['pin_salt'], isA<String>());
    expect(finalize['kdf_iterations'], 600000);
    if (kVerifierFreeZkRegistration) {
      expect(finalize.containsKey('pin_verifier'), isFalse);
    } else {
      expect(finalize['pin_verifier'], isA<String>());
    }
  });
}
