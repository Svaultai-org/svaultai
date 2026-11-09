/// Session-bound selection for exact private file follow-ups.
///
/// An upload becomes a selection only when exactly one committed V2 file can
/// be re-read through the private file list and download offers. The caller
/// still re-reads current metadata before opening or inspecting the file.
library;

import 'package:cryptography/cryptography.dart';

import 'zk_private_chat.dart';

class ZkPrivateFileSelection {
  String? _fileId;
  String? _token;
  String? _vaultId;
  SecretKey? _mvk;

  void clear() {
    _fileId = null;
    _token = null;
    _vaultId = null;
    _mvk = null;
  }

  void bindExactResult({
    required String fileId,
    required String token,
    required String vaultId,
    required SecretKey mvk,
  }) {
    clear();
    if (fileId.trim().isEmpty || token.isEmpty || vaultId.isEmpty) return;
    _fileId = fileId;
    _token = token;
    _vaultId = vaultId;
    _mvk = mvk;
  }

  bool bindCommittedV2Uploads({
    required List<String?> fileIds,
    required bool listOffered,
    required bool downloadOffered,
    required String token,
    required String vaultId,
    required SecretKey mvk,
  }) {
    clear();
    if (!listOffered || !downloadOffered || fileIds.length != 1) return false;
    final fileId = fileIds.single;
    if (fileId == null || fileId.trim().isEmpty) return false;
    bindExactResult(
      fileId: fileId,
      token: token,
      vaultId: vaultId,
      mvk: mvk,
    );
    return _fileId != null;
  }

  String? forFollowUp({
    required String prompt,
    required String token,
    required String vaultId,
    required SecretKey mvk,
  }) {
    if (!ZkLocalChatRouter.isSelectedFileFollowUp(prompt) ||
        _token != token ||
        _vaultId != vaultId ||
        !identical(_mvk, mvk)) {
      clear();
      return null;
    }
    return _fileId;
  }
}
