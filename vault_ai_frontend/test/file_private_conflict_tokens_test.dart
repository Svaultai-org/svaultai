import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_private_conflict_tokens.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 31));
  const vaultId = '123e4567-e89b-12d3-a456-426614174000';
  final digest = Uint8List.fromList(List<int>.filled(32, 4));

  test('old and new spellings produce matching path-scoped name tokens',
      () async {
    final maker = FilePrivateConflictTokenMaker(mvk: mvk, vaultId: vaultId);
    final older = await maker.make(
      wholeFileSha256: digest,
      fileSize: 200,
      fileName: 'Photo.JPG',
      savedName: 'Beach portrait',
      relativePath: ' Holiday/Beach ',
    );
    final incoming = await maker.make(
      wholeFileSha256: Uint8List.fromList(List<int>.filled(32, 5)),
      fileSize: 201,
      fileName: ' beach portrait ',
      relativePath: 'Holiday/Beach',
    );
    expect(older.nameTokens.length, 2);
    expect(incoming.nameTokens.length, 1);
    expect(
      older.nameTokens.any((token) =>
          _equal(token, incoming.nameTokens.single)),
      isTrue,
    );
    expect(_equal(older.contentToken, incoming.contentToken), isFalse);

    final elsewhere = await maker.make(
      wholeFileSha256: digest,
      fileSize: 200,
      fileName: 'beach portrait',
      relativePath: 'Holiday/Other',
    );
    expect(older.nameTokens.any((token) =>
        _equal(token, elsewhere.nameTokens.single)), isFalse);
    expect(_equal(older.contentToken, elsewhere.contentToken), isTrue);
  });

  test('vault key and vault identity separate lookup tokens', () async {
    final base = await FilePrivateConflictTokenMaker(
      mvk: mvk, vaultId: vaultId,
    ).make(
      wholeFileSha256: digest, fileSize: 200, fileName: 'photo.jpg',
    );
    for (final other in <FilePrivateConflictTokenMaker>[
      FilePrivateConflictTokenMaker(
        mvk: SecretKey(List<int>.filled(32, 32)), vaultId: vaultId,
      ),
      FilePrivateConflictTokenMaker(
        mvk: mvk,
        vaultId: '123e4567-e89b-12d3-a456-426614174001',
      ),
    ]) {
      final result = await other.make(
        wholeFileSha256: digest, fileSize: 200, fileName: 'photo.jpg',
      );
      expect(_equal(result.contentToken, base.contentToken), isFalse);
      expect(_equal(result.nameTokens.single, base.nameTokens.single), isFalse);
    }
  });

  test('missing names or invalid content digest fail before token generation',
      () async {
    final maker = FilePrivateConflictTokenMaker(mvk: mvk, vaultId: vaultId);
    await expectLater(
      maker.make(
        wholeFileSha256: Uint8List(31), fileSize: 1, fileName: 'x',
      ),
      throwsFormatException,
    );
    await expectLater(
      maker.make(
        wholeFileSha256: digest, fileSize: 1, fileName: '  ',
      ),
      throwsFormatException,
    );
  });
}

bool _equal(List<int> a, List<int> b) =>
    a.length == b.length &&
    List<int>.generate(a.length, (index) => index)
        .every((index) => a[index] == b[index]);
