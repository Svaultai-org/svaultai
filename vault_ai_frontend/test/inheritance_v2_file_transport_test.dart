import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_stage.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_stream_transfer.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  test('HTTP transfer sends only ciphertext and publishes after readback',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 81));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 91));
    ZkActiveMvk.set(
      mvk: beneficiaryMvk,
      vaultId: 'synthetic-beneficiary',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    setApiClientDeviceId('synthetic-device');
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final privateKey = SecretKey(await pair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 37,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    ))
        .toRequestBody(37);
    final source = await FileV2Writer(ownerMvk).prepare(
      fileId: FileV2Writer.newFileId(),
      fileName: 'private-name.txt',
      bytes: Uint8List.fromList(utf8.encode('private-content')),
    );
    final targetId = await inheritedTargetFileId(
      linkId: 37,
      ownerVaultId: 'synthetic-owner',
      sourceFileId: source.fileId,
      beneficiaryMvk: beneficiaryMvk,
    );
    Map<String, dynamic>? targetManifest;
    final targetChunks = <int, String>{};
    var published = false;
    var publishCalls = 0;
    var rejectStaleRevision = false;
    final writes = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        expect(request.body, isNot(contains('private-name.txt')));
        expect(request.body, isNot(contains('private-content')));
        expect(request.body, isNot(contains('"pin"')));
        final path = request.url.path;
        if (request.method != 'GET') writes.add(request);
        if (path == '/inheritance/v2/37/files/${source.fileId}/manifest') {
          return http.Response(
            jsonEncode(<String, dynamic>{
              'beneficiary_link_id': 37,
              'owner_vault_id': 'synthetic-owner',
              'source_revision': List.filled(64, 'a').join(),
              ...source.toManifestBody(),
              'lifecycle_state': 'client_v2_ready',
              'verification_state': 'client_verified',
              'name_version': 0,
              'migration_metadata_version': 1,
              'saved_name_override_ciphertext': null,
            }),
            200,
          );
        }
        if (path == '/inheritance/v2/37/files/${source.fileId}/chunk/0') {
          return http.Response(
            jsonEncode(<String, dynamic>{
              'beneficiary_link_id': 37,
              'owner_vault_id': 'synthetic-owner',
              'file_id': source.fileId,
              'chunk_index': 0,
              'ciphertext': source.chunkCiphertexts.single,
            }),
            200,
          );
        }
        if (path == '/vault/file-v2/$targetId/manifest' &&
            request.method == 'GET') {
          return targetManifest == null
              ? http.Response('{"detail":"missing"}', 404)
              : http.Response(
                  jsonEncode(<String, dynamic>{
                    ...targetManifest!,
                    'lifecycle_state':
                        published ? 'client_v2_ready' : 'file_v2_written',
                    'verification_state':
                        published ? 'client_verified' : 'not_verified',
                    'name_version': 0,
                    'migration_metadata_version': 1,
                    'saved_name_override_ciphertext': null,
                  }),
                  200,
                );
        }
        if (path == '/vault/file-v2/manifest' && request.method == 'POST') {
          targetManifest = jsonDecode(request.body) as Map<String, dynamic>;
          expect(targetManifest!['file_id'], targetId);
          return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': targetId,
              'crypto_version': 'client_mvk_v2',
            }),
            200,
          );
        }
        if (path == '/vault/file-v2/$targetId/chunk/0' &&
            request.method == 'GET') {
          return targetChunks.containsKey(0)
              ? http.Response(
                  jsonEncode(<String, dynamic>{
                    'file_id': targetId,
                    'chunk_index': 0,
                    'ciphertext': targetChunks[0],
                  }),
                  200,
                )
              : http.Response('{"detail":"missing"}', 404);
        }
        if (path == '/vault/file-v2/chunk' && request.method == 'PUT') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          targetChunks[body['chunk_index'] as int] =
              body['ciphertext'] as String;
          return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': targetId,
              'chunk_index': body['chunk_index'],
            }),
            200,
          );
        }
        if (path == '/vault/file-v2/$targetId/publish-new' &&
            request.method == 'POST') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['confirm'], true);
          expect(body['inheritance_link_id'], 37);
          expect(body['inheritance_source_file_id'], source.fileId);
          expect(body['inheritance_source_revision'],
              List.filled(64, 'a').join());
          expect(body['zk_proof_token'], 'synthetic-opaque-proof');
          expect(body['content_token'],
              matches(RegExp(r'^[A-Za-z0-9_-]{43}$')));
          expect(body['name_tokens'], hasLength(1));
          expect(body['duplicate_action'], 'keep_both');
          expect(targetChunks.length, 1);
          publishCalls++;
          if (rejectStaleRevision) {
            return http.Response('{"detail":"inherited_source_changed"}', 409);
          }
          published = true;
          return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': targetId,
              'status': 'published',
            }),
            200,
          );
        }
        fail('Unexpected transfer route $path');
      }),
    );
    final result = await client.transferInheritedV2File(
      authToken: 'synthetic-session',
      linkId: 37,
      sourceFileId: source.fileId,
      freshBeneficiaryProof: () async => 'synthetic-opaque-proof',
      beneficiaryPrivateKey: privateKey,
      beneficiaryMvk: beneficiaryMvk,
      releasedPackage: package,
    );
    expect(result['status'], 'published');
    expect(publishCalls, 1);
    expect(writes.map((request) => request.url.path), <String>[
      '/vault/file-v2/manifest',
      '/vault/file-v2/chunk',
      '/vault/file-v2/$targetId/publish-new',
    ]);
    expect(writes.any((request) => request.url.path.contains('download-file')),
        isFalse);

    // A revision can change after client readback but before the final server
    // transaction. The already-published retry must surface it without
    // staging a second target or consuming another successful publication.
    rejectStaleRevision = true;
    await expectLater(
      client.transferInheritedV2File(
        authToken: 'synthetic-session',
        linkId: 37,
        sourceFileId: source.fileId,
        freshBeneficiaryProof: () async => 'synthetic-opaque-proof',
        beneficiaryPrivateKey: privateKey,
        beneficiaryMvk: beneficiaryMvk,
        releasedPackage: package,
      ),
      throwsA(isA<InheritedV2SourceChangedException>()),
    );
    expect(publishCalls, 2);
    expect(writes.where((request) =>
        request.url.path == '/vault/file-v2/manifest'), hasLength(1));
    expect(writes.where((request) =>
        request.url.path == '/vault/file-v2/chunk'), hasLength(1));
  });

  test('batch adapter verifies the released owner and rechecks empty inventory',
      () async {
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 99));
    ZkActiveMvk.set(
      mvk: beneficiaryMvk,
      vaultId: 'synthetic-beneficiary',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 41,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: SecretKey(List<int>.filled(32, 88)),
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    )).toRequestBody(41);
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        expect(request.method, 'GET');
        expect(request.url.path, '/inheritance/v2/41/files');
        expect(request.url.queryParameters['after_file_id'], '');
        expect(request.url.queryParameters['limit'], '100');
        expect(request.body, isEmpty);
        return http.Response(jsonEncode({
          'owner_vault_id': 'synthetic-owner',
          'beneficiary_link_id': 41,
          'files': <Map<String, dynamic>>[],
          'next_after_file_id': null,
        }), 200);
      }),
    );
    final result = await client.transferInheritedV2Files(
      authToken: 'synthetic-session',
      linkId: 41,
      freshBeneficiaryProof: () async => fail('No file to publish'),
      beneficiaryPrivateKey: SecretKey(await pair.extractPrivateKeyBytes()),
      beneficiaryMvk: beneficiaryMvk,
      releasedPackage: package,
      responseIsCurrent: () => true,
    );
    expect(result.copiedFiles, 0);
    expect(result.copiedBytes, 0);
    expect(sent, hasLength(2));
  });
}
