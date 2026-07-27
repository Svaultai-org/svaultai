import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/opaque_client_stub.dart'
    show OpaqueAuthenticationFailed;
import 'package:vault_ai_frontend/services/vault_handle.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

const String _goodPin = '123456';
const String _vaultId = 'vault-beneficiary';

final Uint8List _exportKeyBytes =
    Uint8List.fromList(List<int>.generate(32, (i) => i + 1));
final String _exportKeyB64 = vaultHandleB64Url(_exportKeyBytes);

class _RepairOpaqueClient implements ZkOpaqueClient {
  final List<String> calls = <String>[];
  String? finishClientIdentifier;

  @override
  Future<void> ready() async {
    calls.add('ready');
  }

  @override
  ZkClientRegistrationStart startRegistration({required String password}) {
    calls.add('startRegistration:$password');
    return const ZkClientRegistrationStart('reg-state', 'ke1-repair');
  }

  @override
  ZkClientRegistrationFinish finishRegistration({
    required String password,
    required String registrationResponse,
    required String clientRegistrationState,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    calls.add('finishRegistration:$registrationResponse');
    finishClientIdentifier = clientIdentifier;
    if (password != _goodPin) {
      throw OpaqueAuthenticationFailed('finish_registration');
    }
    return ZkClientRegistrationFinish(
      'registration-record',
      _exportKeyB64,
      null,
    );
  }

  @override
  ZkClientLoginStart startLogin({required String password}) {
    throw UnsupportedError('login is outside repair tests');
  }

  @override
  ZkClientLoginFinish finishLogin({
    required String clientLoginState,
    required String loginResponse,
    required String password,
    String? clientIdentifier,
    String? serverIdentifier,
  }) {
    throw UnsupportedError('login is outside repair tests');
  }
}

class _RepairHttpHarness {
  _RepairHttpHarness({required this.vaultHandle});

  final String vaultHandle;
  final List<String> calls = <String>[];
  final List<String?> bearerTokens = <String?>[];
  final List<Map<String, dynamic>> finalizeBodies = <Map<String, dynamic>>[];

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body, {
    String? bearerToken,
  }) async {
    calls.add(path);
    bearerTokens.add(bearerToken);
    if (path == '/auth/zk-repair-init') {
      expect(body['vault_handle'], vaultHandle);
      expect(body['ke1'], 'ke1-repair');
      return {'ke2': 'ke2-repair'};
    }
    if (path == '/auth/zk-repair-finalize') {
      finalizeBodies.add(Map<String, dynamic>.from(body));
      final branch = body['repair_branch'] as String;
      return {
        'repaired': true,
        'vault_id': _vaultId,
        'vault_handle': vaultHandle,
        'branch': branch,
        'pk_rotated': branch == zkRepairBranchRotateNewKey,
        'requires_owner_reencryption': branch == zkRepairBranchRotateNewKey,
        'reencryption_required_count':
            branch == zkRepairBranchRotateNewKey ? 2 : 0,
      };
    }
    throw StateError('unexpected path $path');
  }
}

SecretKey _key(int marker) {
  final bytes = Uint8List.fromList(List<int>.filled(32, marker));
  return SecretKey(bytes);
}

void main() {
  group('ZkAuthService repairVaultOpaqueRecord', () {
    late String vaultHandle;

    setUp(() {
      vaultHandle = vaultHandleToDisplay(Uint8List.fromList(
        List<int>.generate(15, (i) => i + 3),
      ));
    });

    test(
        'preserves an existing sk_vault with modern no-identifier registration',
        () async {
      final opaque = _RepairOpaqueClient();
      final http = _RepairHttpHarness(vaultHandle: vaultHandle);

      final result = await ZkAuthService(
        http.post,
        opaque: opaque,
      ).repairVaultOpaqueRecord(
        vaultHandle: vaultHandle,
        pin: _goodPin,
        mvk: _key(7),
        displayName: 'Beneficiary',
        currentSessionToken: 'fresh-session',
        existingSkVaultPrivate: _key(9),
      );

      expect(result.branch, zkRepairBranchPreserveExistingKey);
      expect(result.requiresOwnerReencryption, isFalse);
      expect(opaque.finishClientIdentifier, isNull);
      expect(http.calls, [
        '/auth/zk-repair-init',
        '/auth/zk-repair-finalize',
      ]);
      expect(http.bearerTokens, ['fresh-session', 'fresh-session']);
      final body = http.finalizeBodies.single;
      expect(body['repair_branch'], zkRepairBranchPreserveExistingKey);
      expect(body['ke3'], 'registration-record');
      expect(body['wrapped_mvk'], isA<String>());
      expect(body['wrapped_sk_vault'], isA<String>());
      expect(body['display_name_ciphertext'], isA<String>());
    });

    test('rotates when no trusted local sk_vault exists', () async {
      final opaque = _RepairOpaqueClient();
      final http = _RepairHttpHarness(vaultHandle: vaultHandle);

      final result = await ZkAuthService(
        http.post,
        opaque: opaque,
      ).repairVaultOpaqueRecord(
        vaultHandle: vaultHandle,
        pin: _goodPin,
        mvk: _key(7),
        displayName: 'Beneficiary',
        currentSessionToken: 'fresh-session',
      );

      expect(result.branch, zkRepairBranchRotateNewKey);
      expect(result.requiresOwnerReencryption, isTrue);
      expect(result.reencryptionRequiredCount, 2);
      expect(http.finalizeBodies.single['repair_branch'],
          zkRepairBranchRotateNewKey);
    });

    test('wrong PIN fails before repair finalize', () async {
      final opaque = _RepairOpaqueClient();
      final http = _RepairHttpHarness(vaultHandle: vaultHandle);

      await expectLater(
        ZkAuthService(http.post, opaque: opaque).repairVaultOpaqueRecord(
          vaultHandle: vaultHandle,
          pin: '000000',
          mvk: _key(7),
          displayName: 'Beneficiary',
          currentSessionToken: 'fresh-session',
        ),
        throwsA(isA<OpaqueAuthenticationFailed>()),
      );

      expect(http.calls, ['/auth/zk-repair-init']);
      expect(http.finalizeBodies, isEmpty);
    });
  });
}
