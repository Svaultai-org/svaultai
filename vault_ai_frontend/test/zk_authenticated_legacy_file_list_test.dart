import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';

void main() {
  setUp(() {
    SessionTermination.instance.resetForTests();
    ZkPinFreeFileSession.instance.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-device');
  });
  tearDown(() {
    ZkPinFreeFileSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
  });

  test('trusted OPAQUE file-list offer uses metadata without a PIN', () async {
    SessionTermination.instance.bindSession('opaque-session');
    ZkPinFreeFileSession.instance.bind(
      sessionToken: 'opaque-session',
      listOffered: true,
      downloadOffered: false,
    );
    final mvk = SecretKey(List<int>.filled(32, 31));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    final name =
        b64urlEncode(await aesGcmWrap(key, utf8.encode('receipt.pdf')));
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        expect(request.headers['authorization'], 'Bearer opaque-session');
        expect(request.url.path, '/vault/files/metadata');
        expect(request.url.queryParameters['require_legacy_complete'], 'true');
        return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': 'synthetic-file',
                  'file_name_ciphertext': name,
                  'file_size': 14,
                  'storage_mode': 'inline',
                  'upload_status': 'complete',
                  'needs_naming': true,
                  'autosaved_secret': false,
                  'has_inline_ciphertext': true,
                  'created_at': '2026-11-06T10:00:00Z',
                },
              ],
              'has_more': false,
            }),
            200);
      }),
    );
    final result = await client.listVaultFiles(
      vaultName: 'synthetic-vault',
      pin: 'raw-pin-marker',
      authToken: 'opaque-session',
    );
    final file = (result['files'] as List).single as Map<String, dynamic>;
    expect(file['file_name'], 'receipt.pdf');
    expect(file['needs_naming'], isTrue);
    expect(paths, <String>['/vault/files/metadata']);
  });

  test('signed list merges private V2 name and folder without exposing either',
      () async {
    const token = 'opaque-session';
    SessionTermination.instance.bindSession(token);
    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: true,
    );
    final mvk = SecretKey(List<int>.filled(32, 31));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'private-photo.jpg',
      relativePath: 'PrivateTrip/Beach/private-photo.jpg',
      bytes: Uint8List.fromList(<int>[1, 2, 3]),
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        if (request.url.path == '/vault/files/metadata') {
          expect(
              request.url.queryParameters['require_legacy_complete'], 'true');
          return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': prepared.fileId,
                    'file_size': 3,
                    'lifecycle_state': 'client_v2_ready',
                    'verification_state': 'client_verified',
                  }
                ],
                'has_more': false,
              }),
              200);
        }
        if (request.url.path == '/vault/file-v2') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'files': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': prepared.fileId,
                    'lifecycle_state': 'client_v2_ready',
                    'verification_state': 'client_verified',
                  }
                ],
              }),
              200);
        }
        if (request.url.path.endsWith('/manifest')) {
          return http.Response(
              jsonEncode(<String, dynamic>{
                ...prepared.toManifestBody(),
                'lifecycle_state': 'client_v2_ready',
                'verification_state': 'client_verified',
              }),
              200);
        }
        fail('Unexpected file-list request: ${request.url}');
      }),
    );
    final result = await client.listVaultFiles(
      vaultName: 'private-vault-name',
      pin: 'raw-pin-marker',
      authToken: token,
    );
    final file = (result['files'] as List).single as Map<String, dynamic>;
    expect(file['file_name'], 'private-photo.jpg');
    expect(file['relative_path'], 'PrivateTrip/Beach/private-photo.jpg');
    expect(file['v2_ready'], isTrue);
    expect(requests, hasLength(3));
    for (final request in requests) {
      expect(request.url.toString(), isNot(contains('PrivateTrip')));
      expect(request.url.toString(), isNot(contains('private-vault-name')));
      expect(request.url.toString(), isNot(contains('raw-pin-marker')));
    }
  });

  test('metadata failure and lock never retry a raw-PIN file list', () async {
    SessionTermination.instance.bindSession('opaque-session');
    ZkPinFreeFileSession.instance.bind(
      sessionToken: 'opaque-session',
      listOffered: true,
      downloadOffered: false,
    );
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 31)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.body, isNot(contains('raw-pin-marker')));
        return http.Response('{}', 404);
      }),
    );
    await expectLater(
      client.listVaultFiles(
        vaultName: 'synthetic-vault',
        pin: 'raw-pin-marker',
        authToken: 'opaque-session',
      ),
      throwsStateError,
    );
    expect(paths, <String>['/vault/files/metadata']);
    paths.clear();
    ZkActiveMvk.clear();
    await expectLater(
      client.listVaultFiles(
        vaultName: 'synthetic-vault',
        pin: 'raw-pin-marker',
        authToken: 'opaque-session',
      ),
      throwsStateError,
    );
    expect(paths, isEmpty);
  });

  test('folder upload after offer asks for one sign-in, without PIN fallback',
      () async {
    SessionTermination.instance.bindSession('opaque-session');
    ZkPinFreeFileSession.instance.bind(
      sessionToken: 'opaque-session',
      listOffered: true,
      downloadOffered: false,
    );
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 31)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.body, isNot(contains('raw-pin-marker')));
        return http.Response('{"detail":"legacy_file_list_changed"}', 409);
      }),
    );
    await expectLater(
      client.listVaultFiles(
        vaultName: 'synthetic-vault',
        pin: 'raw-pin-marker',
        authToken: 'opaque-session',
      ),
      throwsA(isA<ZkLegacyFileListChangedException>()),
    );
    expect(requests, hasLength(1));
    expect(requests.single.url.path, '/vault/files/metadata');
    expect(
        requests.single.url.queryParameters['require_legacy_complete'], 'true');
  });
}
