import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  test('API rename sends authenticated ciphertext and verifies readback',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 52));
    final fileId = FileV2Writer.newFileId();
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: fileId,
      fileName: 'synthetic-photo.jpg',
      bytes: Uint8List.fromList(const <int>[1, 2, 3]),
    );
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
    addTearDown(() {
      ZkActiveMvk.clear();
      setApiClientDeviceId('');
    });
    final manifest = <String, dynamic>{
      ...prepared.toManifestBody(),
      'lifecycle_state': 'client_v2_ready',
      'verification_state': 'client_verified',
      'name_version': 0,
      'saved_name_override_ciphertext': null,
    };
    final requests = <http.Request>[];
    final mock = MockClient((request) async {
      requests.add(request);
      expect(request.headers['authorization'], 'Bearer synthetic-session');
      expect(request.headers['x-device-id'], 'synthetic-device');
      if (request.method == 'GET' &&
          request.url.path == '/vault/file-v2/$fileId/manifest') {
        return http.Response(jsonEncode(manifest), 200);
      }
      if (request.method == 'POST' &&
          request.url.path == '/vault/file-v2/$fileId/rename') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body.keys.toSet(), <String>{
          'zk_proof_token',
          'expected_name_version',
          'saved_name_ciphertext',
        });
        expect(body['zk_proof_token'], 'synthetic-proof');
        expect(body['expected_name_version'], 0);
        expect(request.body, isNot(contains('new private name')));
        expect(request.body, isNot(contains('"pin"')));
        final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
        final clear = await aesGcmUnwrap(
          metadataKey,
          b64urlDecode(body['saved_name_ciphertext'] as String),
        );
        expect(utf8.decode(clear), 'new private name');
        manifest['saved_name_override_ciphertext'] =
            body['saved_name_ciphertext'];
        manifest['name_version'] = 1;
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': fileId,
              'name_version': 1,
              'renamed': true,
            }),
            200);
      }
      fail('Unexpected route ${request.method} ${request.url.path}');
    });
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: mock,
    );
    final renamed = await client.renameAvailableV2File(
      authToken: 'synthetic-session',
      fileId: fileId,
      savedName: 'new private name',
      zkProofToken: 'synthetic-proof',
    );
    expect(renamed.savedName, 'new private name');
    expect(renamed.nameVersion, 1);
    expect(requests.where((r) => r.method == 'POST'), hasLength(1));
  });
}
