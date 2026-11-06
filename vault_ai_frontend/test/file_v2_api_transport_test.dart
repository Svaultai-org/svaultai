import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

Future<String> _legacyEncrypt(List<int> plain, SecretKey key) async {
  final box = await AesGcm.with256bits().encrypt(
    plain,
    secretKey: key,
    nonce: List<int>.generate(12, (i) => i + 1),
  );
  return base64.encode(<int>[
    ...box.nonce,
    ...box.cipherText,
    ...box.mac.bytes,
  ]);
}

void main() {
  test('disabled V2 route is ignored only for an offered older-file read',
      () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 63)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    setApiClientDeviceId('synthetic-device');
    var status = 404;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/vault/file-v2');
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.bodyBytes, isEmpty);
        return http.Response('{"detail":"not_found"}', status);
      }),
    );
    expect(
      await client.isAvailableV2File(
        authToken: 'synthetic-session',
        fileId: 'synthetic-older-file',
        allowDisabledRoute: true,
      ),
      isFalse,
    );
    await expectLater(
      client.isAvailableV2File(
        authToken: 'synthetic-session',
        fileId: 'synthetic-older-file',
      ),
      throwsA(isA<FileV2ReadException>()),
    );
    status = 500;
    await expectLater(
      client.isAvailableV2File(
        authToken: 'synthetic-session',
        fileId: 'synthetic-older-file',
        allowDisabledRoute: true,
      ),
      throwsA(isA<FileV2ReadException>()),
    );
  });

  test('retired V2 list/open/delete uses session and proof without raw PIN',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 63));
    final legacyKey = SecretKey(List<int>.filled(32, 71));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    setApiClientDeviceId('synthetic-device');
    addTearDown(ZkActiveMvk.clear);

    final bytes = List<int>.generate(300, (i) => (i * 5) & 255);
    final metaKey = await VaultKeyHierarchy(mvk).metadataKey();
    final nameCt = b64urlEncode(
      await aesGcmWrap(metaKey, utf8.encode('synthetic-file.bin')),
    );
    final staged = await LegacyCiphertextMigrationCodec(
      legacyKey: legacyKey,
      mvk: mvk,
    ).stageFile(
      fileId: 'synthetic-file-1',
      legacyCiphertext: await _legacyEncrypt(bytes, legacyKey),
      declaredFileSize: bytes.length,
      contentType: 'application/octet-stream',
      encryptedMetadata: <String, String?>{
        'file_name_ciphertext': nameCt,
      },
      chunkSize: 64,
    );
    final seen = <http.Request>[];
    final mock = MockClient((request) async {
      seen.add(request);
      expect(request.headers['authorization'], 'Bearer synthetic-session');
      expect(request.headers['x-device-id'], 'synthetic-device');
      expect(request.url.path, isNot(contains('download-file')));
      if (request.url.path == '/vault/files/metadata') {
        expect(request.url.queryParameters['limit'], '100');
        return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': staged.fileId,
                  'file_size': bytes.length,
                  'file_name_ciphertext': nameCt,
                  'lifecycle_state': 'legacy_migration_retired',
                  'verification_state': 'client_verified',
                },
                <String, dynamic>{
                  'file_id': 'synthetic-legacy-file',
                  'file_size': 3,
                  'file_name_ciphertext': nameCt,
                  'has_inline_ciphertext': true,
                },
              ],
              'has_more': false,
              'next_after_file_id': 'synthetic-legacy-file',
            }),
            200);
      }
      if (request.url.path == '/vault/file-v2') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'files': <Map<String, dynamic>>[
                <String, dynamic>{
                  'file_id': staged.fileId,
                  'lifecycle_state': 'legacy_migration_retired',
                  'verification_state': 'client_verified',
                },
                <String, dynamic>{
                  'file_id': 'synthetic-incomplete',
                  'lifecycle_state': 'file_v2_written',
                  'verification_state': 'unverified',
                },
              ],
            }),
            200);
      }
      if (request.url.path.endsWith('/manifest')) {
        return http.Response(
            jsonEncode(<String, dynamic>{
              ...staged.toManifestBody(),
              'lifecycle_state': 'legacy_migration_retired',
              'verification_state': 'client_verified',
            }),
            200);
      }
      if (request.url.path.contains('/chunk/')) {
        final index = int.parse(request.url.path.split('/').last);
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': staged.fileId,
              'chunk_index': index,
              'ciphertext': staged.chunkCiphertexts[index],
            }),
            200);
      }
      if (request.url.path.endsWith('/delete-confirm')) {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body.keys.toSet(), <String>{'zk_proof_token', 'confirm'});
        expect(body['zk_proof_token'], 'synthetic-one-use-proof');
        expect(body['confirm'], isTrue);
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': staged.fileId,
              'deleted': true,
            }),
            200);
      }
      fail('Unexpected file V2 route');
    });
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: mock,
    );
    final list = await client.listRetiredV2Files(
      authToken: 'synthetic-session',
    );
    expect(list, hasLength(1));
    expect(list.single['id'], staged.fileId);
    expect(list.single['file_name'], 'synthetic-file.bin');
    expect(list.single['v2_retired'], isTrue);
    final merged = await client.listZkVaultFilesWithRetiredV2(
      authToken: 'synthetic-session',
    );
    final mergedFiles = merged['files'] as List;
    expect(mergedFiles, hasLength(2));
    expect((mergedFiles.first as Map)['v2_retired'], isTrue);
    expect((mergedFiles.last as Map)['file_name'], 'synthetic-file.bin');
    expect((mergedFiles.last as Map)['v2_retired'], isFalse);
    expect(
        await client.isRetiredV2File(
          authToken: 'synthetic-session',
          fileId: staged.fileId,
        ),
        isTrue);
    expect(
        await client.isRetiredV2File(
          authToken: 'synthetic-session',
          fileId: 'synthetic-incomplete',
        ),
        isFalse);
    final downloaded = await client.downloadRetiredV2File(
      authToken: 'synthetic-session',
      fileId: staged.fileId,
    );
    expect(downloaded.bytes, bytes);
    // A fresh client and newly unwrapped MVK must reopen the same server copy.
    ZkActiveMvk.clear();
    ZkActiveMvk.set(
      mvk: SecretKey(await mvk.extractBytes()),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final reopenedClient = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: mock,
    );
    expect(
        (await reopenedClient.listRetiredV2Files(
          authToken: 'synthetic-session',
        ))
            .single['file_name'],
        'synthetic-file.bin');
    expect(
        (await reopenedClient.downloadRetiredV2File(
          authToken: 'synthetic-session',
          fileId: staged.fileId,
        ))
            .bytes,
        bytes);
    await reopenedClient.deleteRetiredV2File(
      authToken: 'synthetic-session',
      fileId: staged.fileId,
      zkProofToken: 'synthetic-one-use-proof',
    );
    expect(seen.any((request) => request.body.contains('"pin"')), isFalse);
  });
}
