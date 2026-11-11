/// Default-off owner indexing after a verified old-file V2 readback.
///
/// The server receives only vault-keyed 32-byte tags, a source snapshot,
/// a session-bound readback receipt, and an OPAQUE proof. File bytes, names,
/// the vault key, and the PIN stay on the client.
library;

import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';

import 'file_private_conflict_tokens.dart';
import 'file_v2_reader.dart';
import 'legacy_content_migration_stager.dart';
import 'vault_key_hierarchy.dart';
import 'zk_proof_token_guard.dart';

typedef FileConflictBackfillGet = Future<Map<String, dynamic>> Function(
    String bearer, String path);
typedef FileConflictBackfillPost = Future<Map<String, dynamic>> Function(
    String bearer, String path, Map<String, dynamic> body);

class _DigestCapture implements Sink<crypto.Digest> {
  crypto.Digest? value;

  @override
  void add(crypto.Digest data) {
    if (value != null) throw StateError('File digest already completed');
    value = data;
  }

  @override
  void close() {
    if (value == null) throw StateError('File digest is incomplete');
  }
}

class FilePrivateConflictBackfill {
  static const int maxFileBytes = 64 * 1024 * 1024;

  final bool enabled;
  final String bearer;
  final String vaultId;
  final int sessionEpoch;
  final SecretKey mvk;
  final String? Function() currentBearer;
  final String? Function() currentVaultId;
  final int Function() currentSessionEpoch;
  final SecretKey? Function() currentMvk;
  final FileConflictBackfillGet get;
  final FileConflictBackfillPost post;
  final Future<String> Function() proofProvider;

  const FilePrivateConflictBackfill({
    this.enabled = false,
    required this.bearer,
    required this.vaultId,
    required this.sessionEpoch,
    required this.mvk,
    required this.currentBearer,
    required this.currentVaultId,
    required this.currentSessionEpoch,
    required this.currentMvk,
    required this.get,
    required this.post,
    required this.proofProvider,
  });

  void _requireCurrent() {
    if (!enabled ||
        bearer.isEmpty ||
        vaultId.isEmpty ||
        currentBearer() != bearer ||
        currentVaultId() != vaultId ||
        currentSessionEpoch() != sessionEpoch ||
        !identical(currentMvk(), mvk)) {
      throw StateError('Private file indexing session changed');
    }
  }

  Future<void> indexVerifiedLegacyFile(
      LegacyStageReadbackEvidence evidence) async {
    _requireCurrent();
    final fileId = evidence.recordId;
    if (!evidence.isFile ||
        fileId.isEmpty ||
        fileId.length > 128 ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(evidence.sourceSnapshot) ||
        evidence.readbackReceipt.isEmpty ||
        !evidence.receiptExpiresAt.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Verified old-file readback is unavailable');
    }
    final encodedId = Uri.encodeComponent(fileId);
    final reader = FileV2Reader(
      mvk: mvk,
      get: (path) => get(bearer, path),
    );
    final download = await reader.download(
      fileId,
      maxBytes: maxFileBytes,
    );
    _requireCurrent();
    try {
      final manifest = download.manifest;
      if (manifest.fileId != fileId ||
          manifest.totalBytes != download.bytes.length ||
          (manifest.fileName?.trim().isEmpty ?? true) &&
              (manifest.savedName?.trim().isEmpty ?? true) ||
          (manifest.relativePath != null && !evidence.verifiedExtraFields)) {
        throw const FormatException('Old-file readback identity changed');
      }
      final staged = await get(
        bearer,
        '/vault/legacy-ciphertext/migrate/file-staged/$encodedId',
      );
      _requireCurrent();
      if (staged['file_id'] != fileId ||
          staged['source_snapshot'] != evidence.sourceSnapshot ||
          staged['total_bytes'] != manifest.totalBytes ||
          staged['chunk_count'] != manifest.chunkCount ||
          staged['readback_receipt'] is! String ||
          staged['v2_ciphertext_sha256'] is! String) {
        throw const FormatException('Old-file source changed');
      }
      final digest = Uint8List.fromList(
        (await Sha256().hash(download.bytes)).bytes,
      );
      late final FilePrivateConflictTokens tokens;
      try {
        _requireCurrent();
        tokens = await FilePrivateConflictTokenMaker(
          mvk: mvk,
          vaultId: vaultId,
        ).make(
          wholeFileSha256: digest,
          fileSize: download.bytes.length,
          fileName: manifest.fileName ?? '',
          savedName: manifest.savedName,
          relativePath: manifest.relativePath,
        );
      } finally {
        digest.fillRange(0, digest.length, 0);
      }
      _requireCurrent();
      final proof = rejectPinShapedZkProof(await proofProvider());
      _requireCurrent();
      if (proof.isEmpty ||
          !evidence.receiptExpiresAt.isAfter(DateTime.now().toUtc())) {
        throw StateError('Old-file proof expired');
      }
      final reply = await post(
        bearer,
        '/vault/file-conflict/index-legacy',
        <String, dynamic>{
          'file_id': fileId,
          'source_snapshot': evidence.sourceSnapshot,
          'readback_receipt': evidence.readbackReceipt,
          'content_token': b64urlEncode(tokens.contentToken),
          'name_tokens': <String>[
            for (final token in tokens.nameTokens) b64urlEncode(token),
          ],
          'zk_proof_token': proof,
          'client_verified_exact_bytes': true,
        },
      );
      _requireCurrent();
      if (reply['file_id'] != fileId ||
          reply['source_snapshot'] != evidence.sourceSnapshot ||
          reply['indexed'] != true) {
        throw const FormatException('Old-file index was not confirmed');
      }
    } finally {
      download.bytes.fillRange(0, download.bytes.length, 0);
    }
  }

  /// Index a previously retired or newly ready V2 file, including files too
  /// large for the old-source migration codec. Only a streaming digest and
  /// MVK-blinded name/content tags leave this client; plaintext stays local.
  Future<void> indexReadyV2File(String fileId) async {
    _requireCurrent();
    if (fileId.isEmpty || fileId.length > 128) {
      throw const FormatException('Invalid private file ID');
    }
    final path = '/vault/file-conflict/ready-source/'
        '${Uri.encodeComponent(fileId)}';
    Future<Map<String, dynamic>> source() async {
      _requireCurrent();
      final value = await get(bearer, path);
      _requireCurrent();
      if (value['file_id'] != fileId ||
          value['source_revision'] is! String ||
          !RegExp(r'^[A-Za-z0-9_-]{43}$')
              .hasMatch(value['source_revision'] as String) ||
          value['file_size'] is! int ||
          value['name_version'] is! int) {
        throw const FormatException('Invalid ready file source');
      }
      return value;
    }

    final first = await source();
    final reader = FileV2Reader(
      mvk: mvk,
      get: (requestPath) async {
        _requireCurrent();
        final response = await get(bearer, requestPath);
        _requireCurrent();
        return response;
      },
    );
    final manifest = await reader.readManifest(fileId, requireReady: true);
    _requireCurrent();
    if (manifest.totalBytes != first['file_size'] ||
        manifest.nameVersion != first['name_version'] ||
        (manifest.fileName?.trim().isEmpty ?? true) &&
            (manifest.savedName?.trim().isEmpty ?? true)) {
      throw const FormatException('Ready file identity changed');
    }
    final digestCapture = _DigestCapture();
    final digestInput = crypto.sha256.startChunkedConversion(digestCapture);
    for (var index = 0; index < manifest.chunkCount; index++) {
      _requireCurrent();
      final clear = await reader.readChunk(manifest, index);
      try {
        _requireCurrent();
        digestInput.add(clear);
      } finally {
        clear.fillRange(0, clear.length, 0);
      }
    }
    digestInput.close();
    final finalSource = await source();
    if (finalSource['source_revision'] != first['source_revision'] ||
        finalSource['file_size'] != manifest.totalBytes ||
        finalSource['name_version'] != manifest.nameVersion) {
      throw const FormatException('Ready file changed during readback');
    }
    final digest = Uint8List.fromList(digestCapture.value!.bytes);
    late final FilePrivateConflictTokens tags;
    try {
      tags = await FilePrivateConflictTokenMaker(
        mvk: mvk,
        vaultId: vaultId,
      ).make(
        wholeFileSha256: digest,
        fileSize: manifest.totalBytes,
        fileName: manifest.fileName ?? '',
        savedName: manifest.savedName,
        relativePath: manifest.relativePath,
      );
    } finally {
      digest.fillRange(0, digest.length, 0);
    }
    _requireCurrent();
    final proof = rejectPinShapedZkProof(await proofProvider());
    _requireCurrent();
    final reply = await post(
      bearer,
      '/vault/file-conflict/index-ready',
      <String, dynamic>{
        'file_id': fileId,
        'source_revision': first['source_revision'],
        'content_token': b64urlEncode(tags.contentToken),
        'name_tokens': <String>[
          for (final token in tags.nameTokens) b64urlEncode(token),
        ],
        'zk_proof_token': proof,
        'client_verified_exact_bytes': true,
      },
    );
    _requireCurrent();
    if (reply['file_id'] != fileId ||
        reply['source_revision'] != first['source_revision'] ||
        reply['indexed'] != true) {
      throw const FormatException('Ready file index was not confirmed');
    }
  }

  Future<int> finishIndex() async {
    _requireCurrent();
    final proof = rejectPinShapedZkProof(await proofProvider());
    _requireCurrent();
    final reply = await post(
      bearer,
      '/vault/file-conflict/index-complete',
      <String, dynamic>{'zk_proof_token': proof},
    );
    _requireCurrent();
    final generation = reply['inventory_generation'];
    if (reply['indexed'] != true ||
        reply['private_upload_enabled'] != false ||
        generation is! int ||
        generation < 0) {
      throw const FormatException('Private file index is incomplete');
    }
    return generation;
  }
}
