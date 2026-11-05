import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/zk_action_proof_prompt.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(() => PrivateZkPinTransportSession.clear());
  tearDown(() {
    PrivateZkPinTransportSession.clear();
    ZkActiveMvk.clear();
  });

  test('beneficiary and V2 rename UI both use private proof prompting', () {
    final source = File('lib/main.dart').readAsStringSync();
    final beneficiary = source.substring(
      source.indexOf('Future<({String? pin, String? zkProofToken})?> '
          '_beneficiaryCredential('),
      source.indexOf('// Requires backend VAULTAI_ZK_NEW_FILE_V2_ENABLED'),
    );
    final rename = source.substring(
      source.indexOf('Future<SavedFileRenameOutcome> _commitSavedFileRename('),
      source.indexOf('Future<void> _openSavedFileRename('),
    );
    for (final flow in [beneficiary, rename]) {
      expect(flow, contains('resolveZkActionProof('));
      expect(flow, contains('promptForPrivateSession: kPrivateOnlyUnlockEnabled'));
      expect(flow, contains('cachedPin: _VaultCrypto.currentPinOrThrow'));
      expect(flow, contains('verifyPin:'));
    }
    expect(beneficiary, contains('if (proofToken == null) return null;'));
    expect(rename, contains('if (proofToken == null) throw const '
        '_ZkActionPromptCancelled();'));
  });

  test('private beneficiary proof prompts, bypasses cache and sends no PIN',
      () async {
    var cacheReads = 0;
    var prompts = 0;
    final proof = await resolveZkActionProof(
      promptForPrivateSession: true,
      promptPin: () async {
        prompts++;
        return '123456';
      },
      cachedPin: () async {
        cacheReads++;
        throw StateError('private unlock has no PIN cache');
      },
      verifyPin: (pin) async {
        expect(pin, '123456');
        return 'synthetic-opaque-proof';
      },
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      }),
    );
    await client.listBeneficiaries(
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-session',
      zkProofToken: proof,
    );
    expect(prompts, 1);
    expect(cacheReads, 0);
    expect(requests, hasLength(1));
    expect(requests.single.url.path, '/beneficiary/list-mine');
    expect(jsonDecode(requests.single.body), {
      'zk_proof_token': 'synthetic-opaque-proof',
    });
  });

  test('private file rename prompts, bypasses cache and sends only proof',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 47));
    final fileId = FileV2Writer.newFileId();
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: fileId,
      fileName: 'before.txt',
      bytes: Uint8List.fromList(const [1, 2, 3]),
    );
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
    addTearDown(() => setApiClientDeviceId(''));

    var cacheReads = 0;
    final proof = await resolveZkActionProof(
      promptForPrivateSession: true,
      promptPin: () async => '123456',
      cachedPin: () async {
        cacheReads++;
        throw StateError('private unlock has no PIN cache');
      },
      verifyPin: (pin) async {
        expect(pin, '123456');
        return 'synthetic-opaque-proof';
      },
    );
    final manifest = <String, dynamic>{
      ...prepared.toManifestBody(),
      'lifecycle_state': 'client_v2_ready',
      'verification_state': 'client_verified',
      'name_version': 0,
      'saved_name_override_ciphertext': null,
    };
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        if (request.method == 'GET') {
          return http.Response(jsonEncode(manifest), 200);
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['zk_proof_token'], 'synthetic-opaque-proof');
        expect(body.containsKey('pin'), isFalse);
        expect(request.body, isNot(contains('new name')));
        manifest['saved_name_override_ciphertext'] =
            body['saved_name_ciphertext'];
        manifest['name_version'] = 1;
        return http.Response(
          jsonEncode({'file_id': fileId, 'name_version': 1, 'renamed': true}),
          200,
        );
      }),
    );
    await client.renameAvailableV2File(
      authToken: 'synthetic-session',
      fileId: fileId,
      savedName: 'new name',
      zkProofToken: proof!,
    );
    expect(cacheReads, 0);
    expect(requests.where((request) => request.method == 'POST'), hasLength(1));
    for (final request in requests) {
      expect(request.body.contains('123456'), isFalse);
      expect(request.body.contains('"pin"'), isFalse);
    }
  });

  test('cancelled prompt performs no verification or request', () async {
    var verified = false;
    var cacheRead = false;
    final proof = await resolveZkActionProof(
      promptForPrivateSession: true,
      promptPin: () async => null,
      cachedPin: () async {
        cacheRead = true;
        return 'unused';
      },
      verifyPin: (_) async {
        verified = true;
        return 'unused';
      },
    );
    expect(proof, isNull);
    expect(verified, isFalse);
    expect(cacheRead, isFalse);
  });

  test('default legacy-compatible path keeps cached PIN behavior', () async {
    var prompted = false;
    final proof = await resolveZkActionProof(
      promptForPrivateSession: false,
      promptPin: () async {
        prompted = true;
        return null;
      },
      cachedPin: () async => 'synthetic-legacy-pin',
      verifyPin: (pin) async {
        expect(pin, 'synthetic-legacy-pin');
        return 'synthetic-proof';
      },
    );
    expect(proof, 'synthetic-proof');
    expect(prompted, isFalse);
  });
}
