// Client-only blind tokens for future private file duplicate decisions.
// These tokens are not sent by current upload routes. The server-side
// conflict gate remains closed until every old file is owner-indexed.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

class FilePrivateConflictTokens {
  final Uint8List contentToken;
  final List<Uint8List> nameTokens;

  const FilePrivateConflictTokens({
    required this.contentToken,
    required this.nameTokens,
  });
}

class FilePrivateConflictTokenMaker {
  final SecretKey mvk;
  final String vaultId;

  const FilePrivateConflictTokenMaker({
    required this.mvk,
    required this.vaultId,
  });

  Future<FilePrivateConflictTokens> make({
    required Uint8List wholeFileSha256,
    required int fileSize,
    required String fileName,
    String? savedName,
    String? relativePath,
  }) async {
    if (vaultId.isEmpty || wholeFileSha256.length != 32 || fileSize < 0 ||
        fileSize > 512 * 1024 * 1024) {
      throw const FormatException('Invalid private file identity');
    }
    final names = <String>{
      if (fileName.trim().isNotEmpty) fileName.trim().toLowerCase(),
      if (savedName != null && savedName.trim().isNotEmpty)
        savedName.trim().toLowerCase(),
    };
    if (names.isEmpty || names.length > 2) {
      throw const FormatException('Invalid private file name');
    }
    final key = await VaultKeyHierarchy(mvk).fileConflictLookupKey();
    final content = await keyedLookupHash(key, <int>[
      ...utf8.encode('file-content-v1\u0000$vaultId\u0000'),
      ..._u64(fileSize),
      ...wholeFileSha256,
    ]);
    final path = utf8.encode(relativePath?.trim() ?? '');
    final tokens = <Uint8List>[];
    for (final name in names) {
      final value = utf8.encode(name);
      tokens.add(await keyedLookupHash(key, <int>[
        ...utf8.encode('file-name-v1\u0000$vaultId\u0000'),
        ..._u32(path.length),
        ...path,
        ..._u32(value.length),
        ...value,
      ]));
    }
    return FilePrivateConflictTokens(
      contentToken: content,
      nameTokens: List<Uint8List>.unmodifiable(tokens),
    );
  }
}

List<int> _u32(int value) => <int>[
      (value >> 24) & 255,
      (value >> 16) & 255,
      (value >> 8) & 255,
      value & 255,
    ];

List<int> _u64(int value) => List<int>.generate(
      8,
      (index) => (value >> ((7 - index) * 8)) & 255,
    );
