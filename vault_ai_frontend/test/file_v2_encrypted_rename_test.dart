import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/file_v2_renamer.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 41));

  Future<(String, Map<String, dynamic>)> fixture() async {
    final fileId = FileV2Writer.newFileId();
    final prepared = await FileV2Writer(mvk).prepare(
      fileId: fileId,
      fileName: 'synthetic-photo.jpg',
      bytes: Uint8List.fromList(const <int>[1, 2, 3, 4]),
      savedName: 'old title',
    );
    return (
      fileId,
      <String, dynamic>{
        ...prepared.toManifestBody(),
        'lifecycle_state': 'client_v2_ready',
        'verification_state': 'client_verified',
        'saved_name_override_ciphertext': null,
        'name_version': 0,
      }
    );
  }

  test('sends only MVK ciphertext and proof, then verifies exact readback',
      () async {
    final (fileId, manifest) = await fixture();
    late Map<String, dynamic> sent;
    final renamer = FileV2Renamer(
      mvk: mvk,
      get: (path) async {
        expect(path, '/vault/file-v2/$fileId/manifest');
        return Map<String, dynamic>.from(manifest);
      },
      post: (path, body) async {
        expect(path, '/vault/file-v2/$fileId/rename');
        sent = Map<String, dynamic>.from(body);
        expect(
            sent.keys,
            containsAll(<String>[
              'zk_proof_token',
              'expected_name_version',
              'saved_name_ciphertext',
            ]));
        expect(sent.keys, isNot(contains('pin')));
        expect(sent.keys, isNot(contains('saved_name')));
        expect(sent.values, isNot(contains('new private title')));
        final key = await VaultKeyHierarchy(mvk).metadataKey();
        final clear = await aesGcmUnwrap(
          key,
          b64urlDecode(sent['saved_name_ciphertext'] as String),
        );
        expect(utf8.decode(clear), 'new private title');
        manifest['saved_name_override_ciphertext'] =
            sent['saved_name_ciphertext'];
        manifest['name_version'] = 1;
        return <String, dynamic>{
          'file_id': fileId,
          'name_version': 1,
          'renamed': true,
        };
      },
    );
    final renamed = await renamer.rename(
      fileId: fileId,
      savedName: '  new private title  ',
      zkProofToken: 'synthetic-one-time-proof',
    );
    expect(sent['expected_name_version'], 0);
    expect(renamed.savedName, 'new private title');
    expect(renamed.nameVersion, 1);
    expect(renamed.readyForUse, isTrue);
    final reopened = await FileV2Reader(
      mvk: SecretKey(await mvk.extractBytes()),
      get: (_) async => Map<String, dynamic>.from(manifest),
    ).readManifest(fileId, requireReady: true);
    expect(reopened.savedName, 'new private title');
    expect(reopened.nameVersion, 1);
  });

  test('recovers a lost response only after exact ciphertext readback',
      () async {
    final (fileId, manifest) = await fixture();
    final renamer = FileV2Renamer(
      mvk: mvk,
      get: (_) async => Map<String, dynamic>.from(manifest),
      post: (_, body) async {
        manifest['saved_name_override_ciphertext'] =
            body['saved_name_ciphertext'];
        manifest['name_version'] = 1;
        throw StateError('synthetic response loss');
      },
    );
    final result = await renamer.rename(
      fileId: fileId,
      savedName: 'new title',
      zkProofToken: 'synthetic-one-time-proof',
    );
    expect(result.savedName, 'new title');
    expect(result.nameVersion, 1);
  });

  test('rejects conflicting readback and a tampered encrypted override',
      () async {
    final (fileId, manifest) = await fixture();
    final renamer = FileV2Renamer(
      mvk: mvk,
      get: (_) async => Map<String, dynamic>.from(manifest),
      post: (_, __) async => <String, dynamic>{
        'file_id': fileId,
        'name_version': 1,
        'renamed': true,
      },
    );
    await expectLater(
      renamer.rename(
        fileId: fileId,
        savedName: 'new title',
        zkProofToken: 'synthetic-one-time-proof',
      ),
      throwsA(isA<FormatException>()),
    );

    manifest['name_version'] = 1;
    manifest['saved_name_override_ciphertext'] =
        b64urlEncode(List<int>.filled(32, 0));
    await expectLater(
      FileV2Reader(mvk: mvk, get: (_) async => manifest).readManifest(
        fileId,
        requireReady: true,
      ),
      throwsA(anything),
    );
  });
}
