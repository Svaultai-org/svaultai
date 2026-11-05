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
}) async {
  final key = await VaultKeyHierarchy(_mvk).metadataKey();
  final metadata = <String, String>{
    'file_name_ciphertext': await _wrap(key, name),
    'content_type_ciphertext': await _wrap(key, mime),
  };
  final body = <String, dynamic>{
    'schema': 'vaultai.file.migrated.v1',
    'file_id': id,
    'file_size': size,
    'content_type': mime,
    'chunk_size': size == 0 ? 1 : size,
    'chunk_count': size == 0 ? 0 : 1,
    'encrypted_metadata': metadata,
  };
  return <String, dynamic>{
    'file_id': id,
    'crypto_version': 'client_mvk_v2',
    'manifest_ciphertext': await _wrap(key, jsonEncode(body)),
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
                  'lifecycle_state': 'legacy_migration_retired'
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
