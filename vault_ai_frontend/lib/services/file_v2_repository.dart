import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'zk_active_mvk.dart';
import 'vault_key_hierarchy.dart';

/// Client-only FILE_V2 envelope and key lifecycle.
class FileV2Repository {
  FileV2Repository._(this._mvk, this._vaultId);

  final SecretKey _mvk;
  final String _vaultId;
  static FileV2Repository? _active;

  static FileV2Repository? current() {
    final mvk = ZkActiveMvk.current();
    final vaultId = ZkActiveMvk.currentVaultId();
    if (mvk == null || vaultId == null || vaultId.isEmpty) {
      _active = null;
      return null;
    }
    // A repository owns key material for exactly one authenticated vault.
    // Never retain it across logout/login or a vault switch merely because
    // no caller sampled current() during the signed-out interval.
    if (_active == null || _active!._vaultId != vaultId) {
      _active = FileV2Repository._(mvk, vaultId);
    }
    return _active;
  }

  static void clear() => _active = null;

  Future<SecretKey> _fileKey(String fileId) async {
    final mvkBytes = await _mvk.extractBytes();
    final files = await Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
      secretKey: SecretKey(mvkBytes),
      nonce: const [],
      info: utf8.encode('vaultai.file.encryption.v2'),
    );
    return Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
      secretKey: SecretKey(await files.extractBytes()),
      nonce: utf8.encode(fileId),
      info: utf8.encode('vaultai.file.record.v2'),
    );
  }

  List<int> _aad(String fileId, [int? chunk]) => utf8.encode(
      'svaultai|client_mvk_v2|file|$fileId${chunk == null ? '' : '|chunk|$chunk'}');

  Future<Uint8List> encryptEnvelope(
      {required String fileId,
      required Uint8List bytes,
      required String filename,
      String? contentType,
      String? relativePath,
      String? label}) async {
    final payload = jsonEncode({
      'filename': filename,
      'content_type': contentType,
      'relative_path': relativePath,
      'label': label,
      'bytes': base64Url.encode(bytes)
    });
    return aesGcmWrapWithAad(await _fileKey(fileId), utf8.encode(payload),
        aad: _aad(fileId));
  }

  Future<Uint8List> encryptMetadata(
      {required String fileId,
      required String filename,
      String? contentType,
      String? relativePath,
      String? label}) async {
    final payload = jsonEncode({
      'filename': filename,
      'content_type': contentType,
      'relative_path': relativePath,
      'label': label
    });
    return aesGcmWrapWithAad(await _fileKey(fileId), utf8.encode(payload),
        aad: _aad(fileId));
  }

  Future<
      ({
        Uint8List bytes,
        String filename,
        String? contentType,
        String? relativePath,
        String? label
      })> decryptEnvelope(String fileId, Uint8List envelope) async {
    final raw = await aesGcmUnwrapWithAad(await _fileKey(fileId), envelope,
        aad: _aad(fileId));
    final map = jsonDecode(utf8.decode(raw)) as Map<String, dynamic>;
    return (
      bytes: Uint8List.fromList(base64Url.decode(map['bytes'] as String)),
      filename: map['filename'] as String,
      contentType: map['content_type'] as String?,
      relativePath: map['relative_path'] as String?,
      label: map['label'] as String?
    );
  }

  Future<Uint8List> encryptChunk(
          String fileId, int index, Uint8List bytes) async =>
      aesGcmWrapWithAad(await _fileKey(fileId), bytes,
          aad: _aad(fileId, index));

  Future<Uint8List> decryptChunk(
          String fileId, int index, Uint8List envelope) async =>
      aesGcmUnwrapWithAad(await _fileKey(fileId), envelope,
          aad: _aad(fileId, index));

  Future<
      ({
        String filename,
        String? contentType,
        String? relativePath,
        String? label
      })> decryptMetadata(String fileId, Uint8List envelope) async {
    final raw = await aesGcmUnwrapWithAad(await _fileKey(fileId), envelope,
        aad: _aad(fileId));
    final map = jsonDecode(utf8.decode(raw)) as Map<String, dynamic>;
    return (
      filename: map['filename'] as String,
      contentType: map['content_type'] as String?,
      relativePath: map['relative_path'] as String?,
      label: map['label'] as String?
    );
  }
}
