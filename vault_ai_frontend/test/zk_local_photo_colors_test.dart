import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_local_photo_colors.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

Future<Uint8List> _syntheticPng() async {
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  canvas.drawRect(
    const ui.Rect.fromLTWH(0, 0, 48, 64),
    ui.Paint()..color = const ui.Color(0xffff0000),
  );
  canvas.drawRect(
    const ui.Rect.fromLTWH(48, 0, 16, 64),
    ui.Paint()..color = const ui.Color(0xff000000),
  );
  final image = await recorder.endRecording().toImage(64, 64);
  try {
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    return data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
  } finally {
    image.dispose();
  }
}

void main() {
  test('decodes actual synthetic photo pixels locally and observes colors',
      () async {
    final pixels = await _syntheticPng();
    final observed = await observePhotoColors(
      pixels, accessIsCurrent: () => true,
    );
    expect(observed, {'red', 'black'});
    final file = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'synthetic-photo',
      title: 'IMG_0042.png',
      mediaKind: ZkLocalMediaKind.photo,
      visualColors: observed,
    );
    final colorMatch = ZkLocalChatRouter.resolve(
      prompt: 'Find my red photo', savedItems: const [], files: [file],
    );
    expect(colorMatch.selection?.id, 'synthetic-photo');
    expect(colorMatch.visualColorEvidence, true);
    expect(colorMatch.maySendToGeneralAi, false);
    final genericColorMatch = ZkLocalChatRouter.resolve(
      prompt: 'Find my red file', savedItems: const [], files: [file],
    );
    expect(genericColorMatch.visualColorEvidence, true);
    final objectClaim = ZkLocalChatRouter.resolve(
      prompt: 'Find my photo wearing red clothes and black shoes',
      savedItems: const [], files: [file],
    );
    expect(objectClaim.selection, isNull);
    expect(objectClaim.disposition, ZkLocalChatDisposition.needsPrivateIndex);
    expect(objectClaim.maySendToGeneralAi, false);
  });

  test('transparent pixels and isolated color are not evidence', () {
    final rgba = Uint8List(100 * 4);
    for (var pixel = 0; pixel < 100; pixel++) {
      final at = pixel * 4;
      rgba[at] = pixel == 0 ? 255 : 0;
      rgba[at + 1] = pixel == 0 ? 0 : 0;
      rgba[at + 2] = pixel == 0 ? 0 : 255;
      rgba[at + 3] = pixel == 0 ? 0 : 255;
    }
    expect(classifyPhotoColors(rgba), {'blue'});
  });

  test('stale access and oversized photo fail before decoding', () async {
    await expectLater(
      observePhotoColors(Uint8List.fromList([1]), accessIsCurrent: () => false),
      throwsStateError,
    );
    await expectLater(
      observePhotoColors(
        Uint8List(maxLocalPhotoColorBytes + 1),
        accessIsCurrent: () => true,
      ),
      throwsFormatException,
    );
  });

  test('tiny compressed photo with huge dimensions is rejected', () async {
    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    canvas.drawRect(
      const ui.Rect.fromLTWH(0, 0, 6001, 1),
      ui.Paint()..color = const ui.Color(0xff000000),
    );
    final image = await recorder.endRecording().toImage(6001, 1);
    Uint8List encoded;
    try {
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      encoded = data!.buffer.asUint8List(
        data.offsetInBytes, data.lengthInBytes,
      );
    } finally {
      image.dispose();
    }
    expect(encoded.length, lessThan(maxLocalPhotoColorBytes));
    await expectLater(
      observePhotoColors(encoded, accessIsCurrent: () => true),
      throwsFormatException,
    );
  });

  test('opt-in private index decrypts image locally and default skips pixels',
      () async {
    final mvk = SecretKey(List<int>.filled(32, 73));
    final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
    final contentKey = await VaultKeyHierarchy(mvk).fileContentKey();
    final photo = await _syntheticPng();
    Future<String> wrap(SecretKey key, List<int> bytes) async =>
        b64urlEncode(await aesGcmWrap(key, bytes));
    final manifestBody = <String, dynamic>{
      'schema': 'vaultai.file.migrated.v1',
      'file_id': 'photo-42',
      'file_size': photo.length,
      'content_type': 'image/png',
      'chunk_size': photo.length,
      'chunk_count': 1,
      'encrypted_metadata': <String, String>{
        'file_name_ciphertext':
            await wrap(metadataKey, utf8.encode('IMG_0042.png')),
        'content_type_ciphertext':
            await wrap(metadataKey, utf8.encode('image/png')),
      },
    };
    final manifest = <String, dynamic>{
      'file_id': 'photo-42',
      'crypto_version': 'client_mvk_v2',
      'manifest_ciphertext':
          await wrap(metadataKey, utf8.encode(jsonEncode(manifestBody))),
      'total_bytes': photo.length,
      'chunk_size': photo.length,
      'chunk_count': 1,
    };
    final chunk = await wrap(contentKey, photo);
    final requested = <String>[];
    Future<Object?> get(String path) async {
      requested.add(path);
      if (path == '/vault/ciphertext/vault-items') return [];
      if (path == '/vault/file-v2') return {
        'files': [{
          'file_id': 'photo-42',
          'verification_state': 'client_verified',
          'lifecycle_state': 'client_v2_ready',
        }],
      };
      if (path == '/vault/file-v2/photo-42/manifest') return manifest;
      if (path == '/vault/file-v2/photo-42/chunk/0') return {
        'file_id': 'photo-42', 'chunk_index': 0, 'ciphertext': chunk,
      };
      fail('Unexpected private path: $path');
    }
    final defaultIndex = await ZkPrivateChatIndexLoader(
      mvk: mvk, get: get, accessIsCurrent: () => true,
    ).load();
    expect(defaultIndex.files.single.visualColors, isEmpty);
    expect(requested.where((path) => path.contains('/chunk/')), isEmpty);
    requested.clear();
    final optIn = await ZkPrivateChatIndexLoader(
      mvk: mvk, get: get, accessIsCurrent: () => true,
      indexPhotoColors: true,
    ).load();
    expect(optIn.files.single.visualColors, {'red', 'black'});
    expect(optIn.incomplete, false);
    expect(requested.where((path) => path.contains('/chunk/')).toList(), [
      '/vault/file-v2/photo-42/chunk/0',
    ]);
    expect(requested.join(' '), isNot(contains('IMG_0042')));
    expect(requested.join(' '), isNot(contains('pin')));
  });

  test('opt-in color scan never opens an unverified file', () async {
    final requested = <String>[];
    final index = await ZkPrivateChatIndexLoader(
      mvk: SecretKey(List<int>.filled(32, 74)),
      indexPhotoColors: true,
      accessIsCurrent: () => true,
      get: (path) async {
        requested.add(path);
        if (path == '/vault/ciphertext/vault-items') return [];
        if (path == '/vault/file-v2') return {
          'files': [{
            'file_id': 'pending-photo',
            'verification_state': 'pending',
            'lifecycle_state': 'active',
          }],
        };
        fail('Unverified photo was opened: $path');
      },
    ).load();
    expect(index.files, isEmpty);
    expect(index.incomplete, true);
    expect(requested, [
      '/vault/ciphertext/vault-items', '/vault/file-v2',
    ]);
  });
}
