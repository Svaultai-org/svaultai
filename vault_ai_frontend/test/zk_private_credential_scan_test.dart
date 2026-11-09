import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';
import 'package:vault_ai_frontend/services/zk_private_credential_scan.dart';

final SecretKey _mvk = SecretKey(List<int>.filled(32, 71));

Future<Map<String, dynamic>> _manifest({
  required String id,
  required String name,
  required String mime,
  String? extractedText,
  int migrationMetadataVersion = 2,
}) async {
  final key = await VaultKeyHierarchy(_mvk).metadataKey();
  Future<String> wrap(String clear) async =>
      b64urlEncode(await aesGcmWrap(key, utf8.encode(clear)));
  return {
    'file_id': id,
    'crypto_version': 'client_mvk_v2',
    'manifest_ciphertext': await wrap(jsonEncode({
      'schema': extractedText == null
          ? 'vaultai.file.migrated.v1'
          : 'vaultai.file.migrated.v$migrationMetadataVersion',
      'file_id': id,
      'file_size': 0,
      'content_type': mime,
      'chunk_size': 1,
      'chunk_count': 0,
      'encrypted_metadata': {
        'file_name_ciphertext': await wrap(name),
        'content_type_ciphertext': await wrap(mime),
      },
      if (extractedText != null)
        'legacy_extra': {
          'relative_path': null,
          'extracted_text': extractedText,
        },
    })),
    if (extractedText != null)
      'migration_metadata_version': migrationMetadataVersion,
    'total_bytes': 0,
    'chunk_size': 1,
    'chunk_count': 0,
  };
}

void main() {
  test('only explicit private credential scans take the local scan path', () {
    expect(
      ZkPrivateCredentialScan.isExplicitRequest(
        'Scan my vault for credentials',
      ),
      isTrue,
    );
    expect(
      ZkPrivateCredentialScan.isExplicitRequest(
        'Check my saved files for passwords',
      ),
      isTrue,
    );
    expect(
      ZkPrivateCredentialScan.isExplicitRequest(
          'How do password managers work?'),
      isFalse,
    );
    expect(
      ZkPrivateCredentialScan.isExplicitRequest('Scan this public website'),
      isFalse,
    );
  });

  test('default staged release does not intercept its existing scan route', () {
    const request = 'Scan my vault for credentials';
    expect(
      ZkPrivateCredentialScan.shouldRouteLocally(
        request,
        privateChatEnabled: false,
        signedPrivateChatOffer: false,
      ),
      isFalse,
    );
    expect(
      ZkPrivateCredentialScan.shouldRouteLocally(
        request,
        privateChatEnabled: true,
        signedPrivateChatOffer: false,
      ),
      isTrue,
    );
    expect(
      ZkPrivateCredentialScan.shouldRouteLocally(
        request,
        privateChatEnabled: false,
        signedPrivateChatOffer: true,
      ),
      isTrue,
    );
    expect(
      ZkPrivateCredentialScan.shouldRouteLocally(
        request,
        privateChatEnabled: false,
        signedPrivateChatOffer: false,
        localDeepScanEnabled: true,
      ),
      isTrue,
    );
    expect(
      ZkPrivateCredentialScan.shouldRouteLocally(
        'How do password managers work?',
        privateChatEnabled: false,
        signedPrivateChatOffer: false,
        localDeepScanEnabled: true,
      ),
      isFalse,
    );
  });

  test('private scan uses ready V2 names and local text without a PIN route',
      () async {
    final manifests = {
      'title': await _manifest(
        id: 'title',
        name: 'github-recovery-codes.txt',
        mime: 'text/plain',
      ),
      'content': await _manifest(
        id: 'content',
        name: 'notes.pdf',
        mime: 'application/pdf',
        extractedText: 'password: SYNTHETIC-SECRET-DO-NOT-RETURN',
      ),
      'photo': await _manifest(
        id: 'photo',
        name: 'summer.jpg',
        mime: 'image/jpeg',
      ),
    };
    final paths = <String>[];
    final index = await ZkPrivateChatIndexLoader(
      mvk: _mvk,
      includeSavedItems: false,
      accessIsCurrent: () => true,
      get: (path) async {
        paths.add(path);
        if (path == '/vault/file-v2') {
          return {
            'files': [
              for (final id in manifests.keys)
                {
                  'file_id': id,
                  'verification_state': 'client_verified',
                  'lifecycle_state': 'legacy_migration_retired',
                },
              {
                'file_id': 'staged',
                'verification_state': 'pending',
                'lifecycle_state': 'active',
              },
            ],
          };
        }
        if (path.endsWith('/manifest')) {
          return manifests[path.split('/')[3]];
        }
        fail('Unexpected request: $path');
      },
    ).load();
    final scan = ZkPrivateCredentialScan.scan(index);
    expect(scan.matches.map((file) => file.id), ['title', 'content']);
    expect(scan.readyFilesChecked, 3);
    expect(scan.textFilesChecked, 2);
    expect(scan.listedFiles, 4);
    expect(scan.incomplete, isTrue);
    expect(scan.summary, contains('partial scan'));
    expect(scan.summary, isNot(contains('SYNTHETIC-SECRET')));
    expect(paths, isNot(contains('/vault/ciphertext/vault-items')));
    expect(paths.any((path) => path.contains('pin')), isFalse);
    expect(paths.any((path) => path.contains('staged')), isFalse);
  });

  test('explicit scan limits report omitted files instead of claiming coverage',
      () async {
    final manifests = {
      for (final id in ['a', 'b', 'c'])
        id: await _manifest(id: id, name: '$id.jpg', mime: 'image/jpeg'),
    };
    final paths = <String>[];
    final index = await ZkPrivateChatIndexLoader(
      mvk: _mvk,
      includeSavedItems: false,
      fileLimit: 2,
      textFileLimit: 0,
      allowPartialFileListing: true,
      accessIsCurrent: () => true,
      get: (path) async {
        paths.add(path);
        if (path == '/vault/file-v2') {
          return {
            'files': [
              for (final id in manifests.keys)
                {
                  'file_id': id,
                  'verification_state': 'client_verified',
                  'lifecycle_state': 'client_v2_ready',
                },
            ],
          };
        }
        if (path.endsWith('/manifest')) {
          return manifests[path.split('/')[3]];
        }
        fail('Unexpected request: $path');
      },
    ).load();
    final scan = ZkPrivateCredentialScan.scan(index);
    expect(scan.matches, isEmpty);
    expect(scan.readyFilesChecked, 2);
    expect(scan.listedFiles, 3);
    expect(scan.summary, contains('1 other listed file was not checked'));
    expect(paths.any((path) => path.contains('/c/')), isFalse);
  });

  test('ordinary private index keeps its existing extracted-text allowance',
      () async {
    final manifest = await _manifest(
      id: 'large',
      name: 'notes.pdf',
      mime: 'application/pdf',
      extractedText: 'password: ${List.filled(200 * 1024, 'x').join()}',
      migrationMetadataVersion: 3,
    );
    Future<Object?> get(String path) async {
      if (path == '/vault/file-v2') {
        return {
          'files': [
            {
              'file_id': 'large',
              'verification_state': 'client_verified',
              'lifecycle_state': 'legacy_migration_retired',
            },
          ],
        };
      }
      if (path == '/vault/file-v2/large/manifest') return manifest;
      fail('Unexpected request: $path');
    }

    final ordinary = await ZkPrivateChatIndexLoader(
      mvk: _mvk,
      includeSavedItems: false,
      accessIsCurrent: () => true,
      get: get,
    ).load();
    expect(ordinary.contentIndexedFiles, 1);
    expect(ZkPrivateCredentialScan.scan(ordinary).matches, hasLength(1));

    final bounded = await ZkPrivateChatIndexLoader(
      mvk: _mvk,
      includeSavedItems: false,
      extractedTextByteLimit: 128 * 1024,
      accessIsCurrent: () => true,
      get: get,
    ).load();
    expect(bounded.contentIndexedFiles, 0);
    expect(bounded.incomplete, isTrue);
    expect(ZkPrivateCredentialScan.scan(bounded).matches, isEmpty);
  });
}
