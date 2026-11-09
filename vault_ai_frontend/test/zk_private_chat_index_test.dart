import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/private_content_pin_guard.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_flow.dart';
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
  String? relativePath,
}) async {
  final key = await VaultKeyHierarchy(_mvk).metadataKey();
  final metadata = <String, String>{
    'file_name_ciphertext': await _wrap(key, name),
    'content_type_ciphertext': await _wrap(key, mime),
  };
  final body = <String, dynamic>{
    'schema': extractedText == null && relativePath == null
        ? 'vaultai.file.migrated.v1'
        : 'vaultai.file.migrated.v2',
    'file_id': id,
    'file_size': size,
    'content_type': mime,
    'chunk_size': size == 0 ? 1 : size,
    'chunk_count': size == 0 ? 0 : 1,
    'encrypted_metadata': metadata,
    if (extractedText != null || relativePath != null)
      'legacy_extra': {
        'relative_path': relativePath,
        'extracted_text': extractedText,
      },
  };
  return <String, dynamic>{
    'file_id': id,
    'crypto_version': 'client_mvk_v2',
    'manifest_ciphertext': await _wrap(key, jsonEncode(body)),
    if (extractedText != null || relativePath != null)
      'migration_metadata_version': 2,
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
        }),
      ),
    },
  ];
  return {
    'files': files,
    'items': items,
    'textChunk': b64urlEncode(await aesGcmWrap(contentKey, utf8.encode(text))),
  };
}

void main() {
  test('related-file lookup uses only client-decrypted V2 names', () async {
    final manifests = <String, Map<String, dynamic>>{
      'front': await _fileManifest(
        id: 'front', name: 'holiday-front.jpg', mime: 'image/jpeg', size: 0,
      ),
      'back': await _fileManifest(
        id: 'back', name: 'holiday-back.jpg', mime: 'image/jpeg', size: 0,
      ),
      'note': await _fileManifest(
        id: 'note', name: 'tax-note.txt', mime: 'text/plain', size: 32,
      ),
    };
    final requested = <String>[];
    Future<Object?> get(String path) async {
      requested.add(path);
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
    }

    final envelope = await loadZkLocalRelatedFilesEnvelope(
      fileId: 'front', mvk: _mvk, get: get, accessIsCurrent: () => true,
    );
    final relationships = envelope['relationships'] as List;
    expect(relationships, hasLength(1));
    expect((relationships.single['file'] as Map)['file_id'], 'back');
    expect(envelope['is_complete'], true);
    expect(requested, [
      '/vault/file-v2',
      '/vault/file-v2/front/manifest',
      '/vault/file-v2/back/manifest',
      '/vault/file-v2/note/manifest',
    ]);
    expect(requested.join(' '), isNot(contains('holiday')));
    expect(requested.every((path) => !path.contains('/chunk/')), isTrue);
  });

  test('unverified file cannot fall back to a PIN-based relation', () async {
    final requested = <String>[];
    await expectLater(
      loadZkLocalRelatedFilesEnvelope(
        fileId: 'pending',
        mvk: _mvk,
        accessIsCurrent: () => true,
        get: (path) async {
          requested.add(path);
          if (path == '/vault/file-v2') {
            return {
              'files': [
                {
                  'file_id': 'pending',
                  'verification_state': 'pending',
                  'lifecycle_state': 'active',
                },
              ],
            };
          }
          fail('Unexpected request: $path');
        },
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    expect(requested, ['/vault/file-v2']);
  });

  test('encrypted media index and chat follow-ups stay on device', () async {
    final fixture = await _fixture();
    final manifests = fixture['files'] as Map<String, Map<String, dynamic>>;
    final requests = <String>[];
    final generalPrompts = <String>[];
    final flow = ZkPrivateChatFlow(
      vaultName: 'Synthetic Vault',
      accessIsCurrent: () => true,
      loadIndex: () => ZkPrivateChatIndexLoader(
        mvk: _mvk,
        accessIsCurrent: () => true,
        get: (path) async {
          requests.add(path);
          if (path == '/vault/ciphertext/vault-items') return fixture['items'];
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
          if (path.endsWith('/manifest')) return manifests[path.split('/')[3]];
          if (path == '/vault/file-v2/text-1/chunk/0') {
            return {
              'file_id': 'text-1',
              'chunk_index': 0,
              'ciphertext': fixture['textChunk'],
            };
          }
          fail('Unexpected ciphertext request: $path');
        },
      ).load(),
      sendGeneral: (prompt, _) async {
        generalPrompts.add(prompt);
        return 'General answer';
      },
    );

    for (final (prompt, expectedId, followUp, expectedAction) in [
      (
        'Find my photo in red cloth and black shoes',
        'photo-1',
        'open it',
        ZkLocalChatAction.open,
      ),
      (
        'Find my video standing at the beach',
        'video-1',
        'play it',
        ZkLocalChatAction.open,
      ),
      (
        'Find my audio recording saying hello',
        'audio-1',
        'download it',
        ZkLocalChatAction.download,
      ),
    ]) {
      final found = await flow.run(prompt);
      expect(found.local.selection?.id, expectedId, reason: prompt);
      final next = await flow.run(followUp);
      expect(next.local.selection?.id, expectedId, reason: followUp);
      expect(next.local.action, expectedAction);
    }
    expect(generalPrompts, isEmpty);
    expect(requests.join(' '), isNot(contains('Synthetic Vault')));
    expect(requests.join(' '), isNot(contains('black shoes')));
    final generic = await flow.run('What is encryption?');
    expect(generic.generalReply, 'General answer');
    expect(generalPrompts, ['What is encryption?']);
  });

  test(
    'root-level VTT captions search an older video without opening it',
    () async {
      const caption = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n'
          'We reached the beach at sunrise.\n';
      final bytes = utf8.encode(caption);
      final contentKey = await VaultKeyHierarchy(_mvk).fileContentKey();
      final captionManifest = await _fileManifest(
        id: 'caption-v2',
        name: 'holiday.vtt',
        mime: 'text/vtt',
        size: bytes.length,
      );
      final requests = <String>[];
      final index = await ZkPrivateChatIndexLoader(
        mvk: _mvk,
        accessIsCurrent: () => true,
        get: (path) async {
          requests.add(path);
          if (path == '/vault/ciphertext/vault-items') return [];
          if (path == '/vault/file-v2') {
            return {
              'files': [
                {
                  'file_id': 'caption-v2',
                  'verification_state': 'client_verified',
                  'lifecycle_state': 'client_v2_ready',
                },
              ],
            };
          }
          if (path == '/vault/file-v2/caption-v2/manifest') {
            return captionManifest;
          }
          if (path == '/vault/file-v2/caption-v2/chunk/0') {
            return {
              'file_id': 'caption-v2',
              'chunk_index': 0,
              'ciphertext': b64urlEncode(await aesGcmWrap(contentKey, bytes)),
            };
          }
          fail('Unexpected private GET: $path');
        },
        legacyFileInventory: () async => {
          'files': [
            {
              'id': 'older-video',
              'upload_status': 'complete',
              'v2_ready': false,
              'v2_retired': false,
              'file_name': 'holiday.mp4',
              'content_type': 'video/mp4',
              'storage_mode': 'inline',
            },
          ],
        },
      ).load();
      final video = index.files.singleWhere((file) => file.id == 'older-video');
      expect(video.legacyProofRequired, isTrue);
      expect(video.searchText, contains('beach at sunrise'));
      expect(video.searchText, isNot(contains('00:00:01')));
      expect(requests.where((path) => path.contains('/chunk/')), [
        '/vault/file-v2/caption-v2/chunk/0',
      ]);
      expect(requests.join(' '), isNot(contains('older-video')));
      expect(requests.join(' '), isNot(contains('pin')));
      final match = ZkLocalChatRouter.resolve(
        prompt: 'Find my video at sunrise',
        savedItems: index.savedItems,
        files: index.files,
      );
      expect(match.selection?.id, 'older-video');
      expect(match.maySendToGeneralAi, isFalse);
    },
  );

  test('folder caption pairs only with the same private folder', () async {
    const caption = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n'
        'orchids beside the promenade\n';
    final bytes = utf8.encode(caption);
    final contentKey = await VaultKeyHierarchy(_mvk).fileContentKey();
    final manifests = <String, Map<String, dynamic>>{
      'caption': await _fileManifest(
        id: 'caption', name: 'holiday.vtt', mime: 'text/vtt',
        size: bytes.length, relativePath: 'Trips/holiday.vtt',
      ),
      'folder-video': await _fileManifest(
        id: 'folder-video', name: 'holiday.mp4', mime: 'video/mp4',
        size: 0, relativePath: 'Trips/holiday.mp4',
      ),
      'root-video': await _fileManifest(
        id: 'root-video', name: 'holiday.mp4', mime: 'video/mp4', size: 0,
      ),
    };
    final requests = <String>[];
    Future<ZkPrivateChatIndex> load({bool older = false}) =>
        ZkPrivateChatIndexLoader(
          mvk: _mvk,
          accessIsCurrent: () => true,
          get: (path) async {
            requests.add(path);
            if (path == '/vault/ciphertext/vault-items') return [];
            if (path == '/vault/file-v2') {
              return {
                'files': [
                  for (final id in older
                      ? const ['caption']
                      : manifests.keys)
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
            if (path == '/vault/file-v2/caption/chunk/0') {
              return {
                'file_id': 'caption',
                'chunk_index': 0,
                'ciphertext': b64urlEncode(await aesGcmWrap(contentKey, bytes)),
              };
            }
            fail('Unexpected private GET: $path');
          },
          legacyFileInventory: older
              ? () async => {
                    'files': [
                      {
                        'id': 'older-folder-video',
                        'upload_status': 'complete',
                        'v2_ready': false,
                        'v2_retired': false,
                        'file_name': 'holiday.mp4',
                        'relative_path': 'Trips/holiday.mp4',
                        'content_type': 'video/mp4',
                        'storage_mode': 'inline',
                      },
                    ],
                  }
              : null,
        ).load();

    final v2 = await load();
    expect(v2.incomplete, isFalse);
    expect(v2.files.singleWhere((f) => f.id == 'folder-video').searchText,
        contains('orchids beside the promenade'));
    expect(v2.files.singleWhere((f) => f.id == 'root-video').searchText,
        isEmpty);

    final old = await load(older: true);
    expect(old.incomplete, isFalse);
    final match = ZkLocalChatRouter.resolve(
      prompt: 'Find my video of orchids beside the promenade',
      savedItems: old.savedItems,
      files: old.files,
    );
    expect(match.selection?.id, 'older-folder-video');
    expect(match.selection?.legacyProofRequired, isTrue);
    expect(requests.join(' '), isNot(contains('Trips')));
    expect(requests.join(' '), isNot(contains('orchids')));
  });

  test('caption links do not guess across duplicate or folder media', () async {
    const caption = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n'
        'beach at sunrise\n';
    final bytes = utf8.encode(caption);
    final contentKey = await VaultKeyHierarchy(_mvk).fileContentKey();
    final captionManifest = await _fileManifest(
      id: 'caption-v2',
      name: 'holiday.vtt',
      mime: 'text/vtt',
      size: bytes.length,
    );
    Future<ZkPrivateChatIndex> load(
      List<Map<String, dynamic>> older, {
      bool truncated = false,
    }) =>
        ZkPrivateChatIndexLoader(
          mvk: _mvk,
          accessIsCurrent: () => true,
          get: (path) async {
            if (path == '/vault/ciphertext/vault-items') return [];
            if (path == '/vault/file-v2') {
              return {
                'files': [
                  {
                    'file_id': 'caption-v2',
                    'verification_state': 'client_verified',
                    'lifecycle_state': 'client_v2_ready',
                  },
                ],
              };
            }
            if (path == '/vault/file-v2/caption-v2/manifest') {
              return captionManifest;
            }
            if (path == '/vault/file-v2/caption-v2/chunk/0') {
              return {
                'file_id': 'caption-v2',
                'chunk_index': 0,
                'ciphertext': b64urlEncode(await aesGcmWrap(contentKey, bytes)),
              };
            }
            fail('Unexpected private GET: $path');
          },
          legacyFileInventory: () async => {
            'files': older,
            'truncated': truncated,
          },
        ).load();
    Map<String, dynamic> video(String id, {String? relativePath}) => {
          'id': id,
          'upload_status': 'complete',
          'v2_ready': false,
          'v2_retired': false,
          'file_name': 'holiday.mp4',
          'content_type': 'video/mp4',
          'storage_mode': 'inline',
          if (relativePath != null) 'relative_path': relativePath,
        };
    final duplicates = await load([video('old-a'), video('old-b')]);
    expect(duplicates.incomplete, isTrue);
    expect(
      duplicates.files
          .where((f) => f.id.startsWith('old-'))
          .every((f) => f.searchText.isEmpty),
      isTrue,
    );
    final folder = await load([
      video('old-folder', relativePath: 'other/holiday.mp4'),
    ]);
    expect(
      folder.files.singleWhere((f) => f.id == 'old-folder').searchText,
      isEmpty,
    );
    final truncated = await load([video('old-partial')], truncated: true);
    expect(truncated.incomplete, isTrue);
    expect(
      truncated.files.singleWhere((f) => f.id == 'old-partial').searchText,
      isEmpty,
    );
  });

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
                      : 'legacy_migration_retired',
                },
              {
                'file_id': 'staged-1',
                'verification_state': 'pending',
                'lifecycle_state': 'active',
              },
            ],
          };
        }
        if (path.endsWith('/manifest')) {
          return files[path.split('/')[3]];
        }
        if (path == '/vault/file-v2/text-1/chunk/0') {
          return {
            'file_id': 'text-1',
            'chunk_index': 0,
            'ciphertext': fixture['textChunk'],
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
    expect(
      index.savedItems.single.searchText,
      isNot(contains('synthetic-password-must-not-index')),
    );
    expect(requested.where((path) => path.contains('/chunk/')), [
      '/vault/file-v2/text-1/chunk/0',
    ]);
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

  test(
    'older media names join private search only with a proof reader',
    () async {
      final ready = await _fileManifest(
        id: 'ready-photo',
        name: 'ready-photo.jpg',
        mime: 'image/jpeg',
        size: 0,
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
                },
              ],
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
                'id': 'ready-photo',
                'upload_status': 'complete',
                'v2_ready': true,
                'file_name': 'ready-photo.jpg',
                'content_type': 'image/jpeg',
                'storage_mode': 'inline',
              },
              {
                'id': 'older-photo',
                'upload_status': 'complete',
                'v2_ready': false,
                'v2_retired': false,
                'file_name': 'red-cloth-black-shoes.jpg',
                'content_type': 'image/jpeg',
                'storage_mode': 'inline',
              },
              {
                'id': 'older-video',
                'upload_status': 'complete',
                'v2_ready': false,
                'v2_retired': false,
                'file_name': 'standing-at-the-beach.mp4',
                'content_type': 'video/mp4',
                'storage_mode': 'chunked',
              },
              {
                'id': 'bad-name',
                'upload_status': 'complete',
                'file_name': '',
                'content_type': 'image/jpeg',
                'storage_mode': 'inline',
              },
            ],
          };
        },
      );
      final index = await loader.load();
      expect(inventoryCalls, 1);
      expect(index.incomplete, isTrue); // Malformed older label was omitted.
      expect(index.files.map((f) => f.id), [
        'ready-photo',
        'older-photo',
        'older-video',
      ]);
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
    },
  );

  test('older media adapter stays inside the existing file cap', () async {
    final ready = await _fileManifest(
      id: 'ready-photo',
      name: 'ready-photo.jpg',
      mime: 'image/jpeg',
      size: 0,
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
              },
            ],
          };
        }
        if (path == '/vault/file-v2/ready-photo/manifest') return ready;
        fail('Unexpected private GET: $path');
      },
      legacyFileInventory: () async => {
        'files': [
          {
            'id': 'older-video',
            'upload_status': 'complete',
            'file_name': 'standing-at-the-beach.mp4',
            'content_type': 'video/mp4',
            'storage_mode': 'chunked',
          },
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

  test('offered older item titles are searchable without PIN or values',
      () async {
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final paths = <String>[];
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      get: (path) async {
        paths.add(path);
        if (path == '/vault/ciphertext/vault-items') return [];
        if (path == '/vault/file-v2') return {'files': []};
        fail('Unexpected private GET: $path');
      },
      legacyItemInventory: () async => [
        {
          'item_id': 31,
          'is_legacy': true,
          'service_ciphertext': await _wrap(key, 'Archive account'),
          'item_type_ciphertext': await _wrap(key, 'login'),
          'payload_ciphertext': 'must-not-be-read',
        },
        {
          'item_id': 32,
          'is_legacy': false,
          'service': 'unrelated item',
        },
      ],
    );
    final index = await loader.load();
    expect(index.savedItems, hasLength(1));
    final item = index.savedItems.single;
    expect(item.itemType, 'login');
    expect(item.title, 'Archive account');
    expect(item.searchText, 'login');
    expect(item.legacyProofRequired, isTrue);
    expect(index.incomplete, isFalse);
    expect(paths, ['/vault/ciphertext/vault-items', '/vault/file-v2']);
    expect(paths.join(' '), isNot(contains('Archive account')));
    expect(paths.join(' '), isNot(contains('must-not-be-read')));
  });

  test('older item metadata cannot exceed the combined private index cap',
      () async {
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final service = await _wrap(key, 'Verified');
    final type = await _wrap(key, 'note');
    final payload = await _wrap(key, '{}');
    final loader = ZkPrivateChatIndexLoader(
      mvk: _mvk,
      accessIsCurrent: () => true,
      get: (path) async {
        if (path == '/vault/ciphertext/vault-items') {
          return List.generate(ZkPrivateChatIndexLoader.maxSavedItems, (i) => {
                'item_id': i + 1,
                'service_ciphertext': service,
                'item_type_ciphertext': type,
                'payload_ciphertext': payload,
              });
        }
        if (path == '/vault/file-v2') return {'files': []};
        fail('Unexpected private GET: $path');
      },
      legacyItemInventory: () async => [
        {'item_id': 501, 'is_legacy': true, 'service': 'First', 'item_type': 'note'},
      ],
    );
    final index = await loader.load();
    expect(index.savedItems, hasLength(ZkPrivateChatIndexLoader.maxSavedItems));
    expect(index.savedItems.every((item) => item.title == 'Verified'), isTrue);
    expect(index.incomplete, isTrue);
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
