import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';

final SecretKey _mvk = SecretKey(List<int>.filled(32, 37));

Future<String> _wrap(SecretKey key, String value) async =>
    b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));

Future<Map<String, dynamic>> _fileManifest({
  required String id,
  required String name,
  required String mime,
  required int size,
  String? extractedText,
}) async {
  final key = await VaultKeyHierarchy(_mvk).metadataKey();
  final metadata = <String, String>{
    'file_name_ciphertext': await _wrap(key, name),
    'content_type_ciphertext': await _wrap(key, mime),
  };
  final body = <String, dynamic>{
    'schema': extractedText == null
        ? 'vaultai.file.migrated.v1'
        : 'vaultai.file.migrated.v2',
    'file_id': id,
    'file_size': size,
    'content_type': mime,
    'chunk_size': size == 0 ? 1 : size,
    'chunk_count': size == 0 ? 0 : 1,
    'encrypted_metadata': metadata,
    if (extractedText != null)
      'legacy_extra': {
        'relative_path': null,
        'extracted_text': extractedText,
      },
  };
  return <String, dynamic>{
    'file_id': id,
    'crypto_version': 'client_mvk_v2',
    'manifest_ciphertext': await _wrap(key, jsonEncode(body)),
    if (extractedText != null) 'migration_metadata_version': 2,
    'total_bytes': size,
    'chunk_size': body['chunk_size'],
    'chunk_count': body['chunk_count'],
  };
}

Future<Map<String, Object?>> _fixture() async {
  final metadataKey = await VaultKeyHierarchy(_mvk).metadataKey();
  final contentKey = await VaultKeyHierarchy(_mvk).fileContentKey();
  const text = 'A quiet walk along the beach at sunset.';
  final files = <String, Map<String, dynamic>>{
    'photo-1': await _fileManifest(
      id: 'photo-1',
      name: 'red-cloth-black-shoes.jpg',
      mime: 'image/jpeg',
      size: 0,
    ),
    'video-1': await _fileManifest(
      id: 'video-1',
      name: 'standing-at-the-beach.mp4',
      mime: 'video/mp4',
      size: 0,
    ),
    'audio-1': await _fileManifest(
      id: 'audio-1',
      name: 'my-voice-saying-hello.m4a',
      mime: 'audio/mp4',
      size: 0,
    ),
    'text-1': await _fileManifest(
      id: 'text-1',
      name: 'travel-notes.txt',
      mime: 'text/plain',
      size: utf8.encode(text).length,
    ),
  };
  final items = <Map<String, dynamic>>[
    <String, dynamic>{
      'item_id': 7,
      'item_type_ciphertext': await _wrap(metadataKey, 'login'),
      'service_ciphertext': await _wrap(metadataKey, 'GitHub account'),
      'payload_ciphertext': await _wrap(
          metadataKey,
          jsonEncode({
            'notes': 'Work account for code hosting',
            'fields': {
              'username': 'synthetic-user',
              'password': 'synthetic-password-must-not-index',
            },
          })),
    },
  ];
  return {
    'files': files,
    'items': items,
    'textChunk': b64urlEncode(await aesGcmWrap(contentKey, utf8.encode(text))),
  };
}

void main() {
  test('MVK decrypts media labels and bounded text only on client', () async {
    final fixture = await _fixture();
    final files = fixture['files'] as Map<String, Map<String, dynamic>>;
    final requested = <String>[];
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      get: (path) async {
        requested.add(path);
        if (path == '/vault/ciphertext/vault-items') return fixture['items'];
        if (path == '/vault/file-v2') {
          return {
            'files': [
              for (final id in files.keys)
                {
                  'file_id': id,
                  'verification_state': 'client_verified',
                  'lifecycle_state': id == 'text-1'
                      ? 'client_v2_ready'
                      : 'legacy_migration_retired'
                },
              {
                'file_id': 'staged-1',
                'verification_state': 'pending',
                'lifecycle_state': 'active'
              },
            ]
          };
        }
        if (path.endsWith('/manifest')) {
          return files[path.split('/')[3]];
        }
        if (path == '/vault/file-v2/text-1/chunk/0') {
          return {
            'file_id': 'text-1',
            'chunk_index': 0,
            'ciphertext': fixture['textChunk']
          };
        }
        fail('Unexpected private GET: $path');
      },
    );
    final index = await loader.load();
    expect(index.incomplete, isTrue); // Staged record was omitted.
    expect(index.savedItems, hasLength(1));
    expect(index.files, hasLength(4));
    expect(index.files.any((record) => record.id == 'staged-1'), isFalse);
    expect(requested.any((path) => path.contains('/staged-1/')), isFalse);
    expect(index.savedItems.single.searchText,
        isNot(contains('synthetic-password-must-not-index')));
    expect(requested.where((path) => path.contains('/chunk/')),
        ['/vault/file-v2/text-1/chunk/0']);
    expect(requested.any((path) => path.contains('pin')), isFalse);

    final photo = ZkLocalChatRouter.resolve(
      prompt: 'Find the photo of me in red cloth and black shoes',
      savedItems: index.savedItems,
      files: index.files,
    );
    expect(photo.selection?.id, 'photo-1');
    expect(photo.maySendToGeneralAi, isFalse);

    final video = ZkLocalChatRouter.resolve(
      prompt: 'Find my video standing at the beach',
      savedItems: index.savedItems,
      files: index.files,
    );
    expect(video.selection?.id, 'video-1');

    final audio = ZkLocalChatRouter.resolve(
      prompt: 'Find the audio recording of me saying hello',
      savedItems: index.savedItems,
      files: index.files,
    );
    expect(audio.selection?.id, 'audio-1');

    final document = ZkLocalChatRouter.resolve(
      prompt: 'Find my notes about a quiet walk at sunset',
      savedItems: index.savedItems,
      files: index.files,
    );
    expect(document.selection?.id, 'text-1');

    final followUp = ZkLocalChatRouter.resolve(
      prompt: 'play it',
      savedItems: index.savedItems,
      files: index.files,
      previousSelection: audio.selection,
    );
    expect(followUp.selection?.id, 'audio-1');
  });

  test('retired V2 extras support local content lookup across media', () async {
    final files = <String, Map<String, dynamic>>{
      'photo-1': await _fileManifest(
        id: 'photo-1',
        name: 'image.jpg',
        mime: 'image/jpeg',
        size: 0,
        extractedText: 'red cloth and black shoes',
      ),
      'video-1': await _fileManifest(
        id: 'video-1',
        name: 'clip.mp4',
        mime: 'video/mp4',
        size: 0,
        extractedText: 'standing at the beach at sunset',
      ),
      'audio-1': await _fileManifest(
        id: 'audio-1',
        name: 'voice.m4a',
        mime: 'audio/mp4',
        size: 0,
        extractedText: 'launch complete at noon',
      ),
      'document-1': await _fileManifest(
        id: 'document-1',
        name: 'notes.pdf',
        mime: 'application/pdf',
        size: 0,
        extractedText: 'rainforest butterflies',
      ),
    };
    final requested = <String>[];
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      get: (path) async {
        requested.add(path);
        if (path == '/vault/ciphertext/vault-items') return [];
        if (path == '/vault/file-v2') {
          return {
            'files': [
              for (final id in files.keys)
                {
                  'file_id': id,
                  'verification_state': 'client_verified',
                  'lifecycle_state': 'legacy_migration_retired',
                },
            ],
          };
        }
        if (path.endsWith('/manifest')) {
          return files[path.split('/')[3]];
        }
        fail('Unexpected private GET: $path');
      },
    );
    final index = await loader.load();
    expect(index.incomplete, isFalse);
    expect(requested.every((path) => !path.contains('/chunk/')), isTrue);
    expect(requested.join(' '), isNot(contains('red cloth')));
    for (final (prompt, id) in [
      ('Find my photo wearing red cloth and black shoes', 'photo-1'),
      ('Find my video standing at the beach', 'video-1'),
      ('Find my recording saying launch complete', 'audio-1'),
      ('Find my document about rainforest butterflies', 'document-1'),
    ]) {
      final result = ZkLocalChatRouter.resolve(
        prompt: prompt,
        savedItems: index.savedItems,
        files: index.files,
      );
      expect(result.selection?.id, id, reason: prompt);
      expect(result.maySendToGeneralAi, isFalse);
    }
  });

  test('older media names join private search only with a proof reader',
      () async {
    final ready = await _fileManifest(
      id: 'ready-photo', name: 'ready-photo.jpg',
      mime: 'image/jpeg', size: 0,
    );
    final requested = <String>[];
    var inventoryCalls = 0;
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      fileLimit: 3,
      get: (path) async {
        requested.add(path);
        if (path == '/vault/ciphertext/vault-items') return [];
        if (path == '/vault/file-v2') {
          return {
            'files': [
              {
                'file_id': 'ready-photo',
                'verification_state': 'client_verified',
                'lifecycle_state': 'client_v2_ready',
              }
            ]
          };
        }
        if (path == '/vault/file-v2/ready-photo/manifest') return ready;
        fail('Unexpected private GET: $path');
      },
      legacyFileInventory: () async {
        inventoryCalls++;
        return {
          'files': [
            {
              'id': 'ready-photo', 'upload_status': 'complete',
              'v2_ready': true, 'file_name': 'ready-photo.jpg',
              'content_type': 'image/jpeg', 'storage_mode': 'inline',
            },
            {
              'id': 'older-photo', 'upload_status': 'complete',
              'v2_ready': false, 'v2_retired': false,
              'file_name': 'red-cloth-black-shoes.jpg',
              'content_type': 'image/jpeg', 'storage_mode': 'inline',
            },
            {
              'id': 'older-video', 'upload_status': 'complete',
              'v2_ready': false, 'v2_retired': false,
              'file_name': 'standing-at-the-beach.mp4',
              'content_type': 'video/mp4', 'storage_mode': 'chunked',
            },
            {
              'id': 'bad-name', 'upload_status': 'complete',
              'file_name': '', 'content_type': 'image/jpeg',
              'storage_mode': 'inline',
            },
          ],
        };
      },
    );
    final index = await loader.load();
    expect(inventoryCalls, 1);
    expect(index.incomplete, isTrue); // Malformed older label was omitted.
    expect(index.files.map((f) => f.id),
        ['ready-photo', 'older-photo', 'older-video']);
    expect(index.files.first.legacyProofRequired, isFalse);
    expect(index.files[1].legacyProofRequired, isTrue);
    expect(index.files[2].legacyProofRequired, isTrue);
    expect(requested.every((path) => path.startsWith('/vault/')), isTrue);
    expect(requested.join(' '), isNot(contains('red-cloth')));
    final selected = ZkLocalChatRouter.resolve(
      prompt: 'Find my video at the beach',
      savedItems: index.savedItems,
      files: index.files,
    );
    expect(selected.selection?.id, 'older-video');
    expect(selected.maySendToGeneralAi, isFalse);
  });

  test('older media adapter stays inside the existing file cap', () async {
    final ready = await _fileManifest(
      id: 'ready-photo', name: 'ready-photo.jpg',
      mime: 'image/jpeg', size: 0,
    );
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      fileLimit: 1,
      get: (path) async {
        if (path == '/vault/ciphertext/vault-items') return [];
        if (path == '/vault/file-v2') {
          return {
            'files': [
              {
                'file_id': 'ready-photo',
                'verification_state': 'client_verified',
                'lifecycle_state': 'client_v2_ready',
              }
            ]
          };
        }
        if (path == '/vault/file-v2/ready-photo/manifest') return ready;
        fail('Unexpected private GET: $path');
      },
      legacyFileInventory: () async => {
        'files': [
          {
            'id': 'older-video', 'upload_status': 'complete',
            'file_name': 'standing-at-the-beach.mp4',
            'content_type': 'video/mp4', 'storage_mode': 'chunked',
          }
        ],
      },
    );
    final index = await loader.load();
    expect(index.files.map((f) => f.id), ['ready-photo']);
    expect(index.incomplete, isTrue);
  });

  test('private search stops if the vault locks during a fetch', () async {
    var current = true;
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => current,
      get: (_) async {
        current = false;
        return const <Map<String, dynamic>>[];
      },
    );
    await expectLater(loader.load(), throwsStateError);
  });

  test('description not present in encrypted metadata is not invented', () {
    const photo = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'photo-1',
      title: 'holiday.jpg',
      mediaKind: ZkLocalMediaKind.photo,
    );
    final result = ZkLocalChatRouter.resolve(
      prompt: 'Find my photo wearing a red coat',
      savedItems: const [],
      files: const [photo],
    );
    expect(result.disposition, ZkLocalChatDisposition.needsPrivateIndex);
    expect(result.maySendToGeneralAi, isFalse);
  });
}
