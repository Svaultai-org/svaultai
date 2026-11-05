import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/vault_handle.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';


class _SyntheticOpaque implements ZkOpaqueClient {
  @override
  Future<void> ready() async {}

  @override
  ZkClientLoginStart startLogin({required String password}) {
    expect(password, 'synthetic-pin-only');
    return const ZkClientLoginStart('local-state', 'synthetic-ke1');
  }

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    expect(password, 'synthetic-pin-only');
    expect(clientLoginState, 'local-state');
    expect(loginResponse, 'synthetic-ke2');
    return const ZkClientLoginFinish(
        'synthetic-ke3', 'synthetic-session-key', 'synthetic-export-key', null);
  }

  @override
  ZkClientRegistrationStart startRegistration({required String password}) =>
      throw UnimplementedError();

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) => throw UnimplementedError();
}


void main() {
  test('pending OPAQUE exchange sends only ke1/ke3 and bearer', () async {
    final paths = <String>[];
    final handle = vaultHandleToDisplay(
        Uint8List.fromList(List<int>.filled(15, 7)));
    Future<Map<String, dynamic>> post(
      String path,
      Map<String, dynamic> body, {
      String? bearerToken,
    }) async {
      paths.add(path);
      expect(bearerToken, 'synthetic-bearer');
      expect(body.containsKey('pin'), isFalse);
      expect(jsonEncode(body), isNot(contains('synthetic-pin-only')));
      if (path == '/auth/zk-pending-verify-init') {
        expect(body.keys.toSet(), {'vault_handle', 'ke1'});
        expect(body['vault_handle'], handle);
        return {'slot_id': 'synthetic-slot', 'ke2': 'synthetic-ke2'};
      }
      expect(path, '/auth/zk-pending-verify-finalize');
      expect(body.keys.toSet(), {'slot_id', 'ke3'});
      return {
        'verified': true,
        'proof_token': 'synthetic-pending-proof',
        'proof_expires_at': '2030-01-01T00:00:00Z',
      };
    }

    final proof = await ZkAuthService(
      post,
      opaque: _SyntheticOpaque(),
    ).verifyPendingDeviceProof(
      vaultHandle: handle,
      pin: 'synthetic-pin-only',
      sessionToken: 'synthetic-bearer',
    );
    expect(proof.token, 'synthetic-pending-proof');
    expect(paths, [
      '/auth/zk-pending-verify-init',
      '/auth/zk-pending-verify-finalize',
    ]);
  });

  test('self-approval proof bodies omit PIN and legacy name field', () async {
    final sent = <http.Request>[];
    setApiClientDeviceId('synthetic_pending_device_1234');
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{"status":"cooldown"}', 200);
      }),
    );
    await client.requestSelfApproval(
      authToken: 'synthetic-bearer',
      zkProofToken: 'synthetic-proof-one',
    );
    await client.finalizeSelfApproval(
      authToken: 'synthetic-bearer',
      zkProofToken: 'synthetic-proof-two',
    );
    expect(sent.length, 2);
    for (final request in sent) {
      expect(request.headers['X-Device-Id'],
          'synthetic_pending_device_1234');
      expect(request.headers['Authorization'],
          'Bearer synthetic-bearer');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body.keys.toSet(), {'zk_proof_token'});
      expect(body.containsKey('pin'), isFalse);
      expect(request.body, isNot(contains('synthetic-pin-only')));
    }
    expect(sent.first.url.path, '/devices/request-self-approval');
    expect(sent.last.url.path, '/devices/finalize-self-approval');
    setApiClientDeviceId('');
  });

  test('pending OPAQUE HTTP adapter keeps device and bearer scope', () async {
    setApiClientDeviceId('synthetic_pending_device_1234');
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{"slot_id":"synthetic-slot","ke2":"synthetic-ke2"}', 200);
      }),
    );
    final response = await client.postPendingDeviceOpaque(
      '/auth/zk-pending-verify-init',
      {'vault_handle': 'synthetic-handle', 'ke1': 'synthetic-ke1'},
      authToken: 'synthetic-bearer',
    );
    expect(response['slot_id'], 'synthetic-slot');
    expect(sent.single.url.path, '/auth/zk-pending-verify-init');
    expect(sent.single.headers['X-Device-Id'],
        'synthetic_pending_device_1234');
    expect(sent.single.headers['Authorization'], 'Bearer synthetic-bearer');
    expect(jsonDecode(sent.single.body), {
      'vault_handle': 'synthetic-handle',
      'ke1': 'synthetic-ke1',
    });
    expect(sent.single.body, isNot(contains('synthetic-pin-only')));
    expect(() => client.postPendingDeviceOpaque(
      '/auth/zk-login-finalize',
      {'ke3': 'synthetic-ke3'},
      authToken: 'synthetic-bearer',
    ), throwsArgumentError);
    setApiClientDeviceId('');
  });

  test('legacy self-approval still uses PIN when explicitly selected', () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{"status":"cooldown"}', 200);
      }),
    );
    await client.requestSelfApproval(
      authToken: 'synthetic-bearer',
      pin: 'synthetic-legacy-pin',
    );
    final body = jsonDecode(sent.single.body) as Map<String, dynamic>;
    expect(body, {'pin': 'synthetic-legacy-pin'});
    expect(body.containsKey('vault_name'), isFalse);
    expect(() => client.requestSelfApproval(
      authToken: 'synthetic-bearer',
      pin: 'synthetic-legacy-pin',
      zkProofToken: 'synthetic-proof',
    ), throwsArgumentError);
  });
}
