import 'dart:async';
import 'dart:typed_data';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';

/// Serializes older inline file reads in one unlocked vault session.
/// Export page numbers are single-use, and the bounded grant is kept only in
/// memory until lock, session replacement, or an uncertain response.
final class LegacyFileReadSession {
  LegacyFileReadSession({
    required LegacyCiphertextExportClient export,
    required LegacyCiphertextMigrationCodec codec,
    required bool Function() isCurrent,
  })  : _export = export,
        _codec = codec,
        _isCurrent = isCurrent;

  final LegacyCiphertextExportClient _export;
  final LegacyCiphertextMigrationCodec _codec;
  final bool Function() _isCurrent;
  Future<void> _tail = Future<void>.value();
  List<Map<String, dynamic>>? _records;
  bool _closed = false;

  Future<({Uint8List bytes, Map<String, dynamic> sourceMetadata})> readFile(
    String fileId,
  ) =>
      readFileWith(fileId, (opened) async => opened);

  /// Keep the caller's final metadata check inside the page-sequence queue.
  Future<T> readFileWith<T>(
    String fileId,
    Future<T> Function(
      ({Uint8List bytes, Map<String, dynamic> sourceMetadata}) opened,
    ) inspect,
  ) async {
    if (fileId.isEmpty || fileId.length > 128) {
      throw const FormatException('Invalid file identity');
    }
    final previous = _tail;
    final release = Completer<void>();
    _tail = release.future;
    await previous;
    try {
      _requireCurrent();
      final records = _records ??= await _export.listFiles();
      _requireCurrent();
      final matches = records.where((row) => row['file_id'] == fileId).toList();
      if (matches.length != 1) {
        throw const FormatException('Older file is unavailable');
      }
      final chars = matches.single['ciphertext_chars'];
      final declaredSize = matches.single['file_size'];
      if (chars is! int ||
          chars <= 0 ||
          chars > LegacyCiphertextExportClient.maxTotalChars ||
          declaredSize is! int ||
          declaredSize < 0 ||
          declaredSize > LegacyCiphertextExportClient.maxTotalChars) {
        throw const FormatException('Older file needs another download path');
      }
      final source = await _export.readFileSource(
        fileId: fileId,
        ciphertextChars: chars,
      );
      _requireCurrent();
      if (!RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot) ||
          source.ciphertext.length != chars ||
          source.sourceMetadata['file_size'] != declaredSize) {
        throw const FormatException('Older file changed during download');
      }
      final bytes = await _codec.decodeLegacyFileBytes(source.ciphertext);
      _requireCurrent();
      if (bytes.length != declaredSize) {
        throw const FormatException('Older file size did not match');
      }
      final inspected = await inspect(
        (bytes: bytes, sourceMetadata: source.sourceMetadata),
      );
      _requireCurrent();
      return inspected;
    } catch (_) {
      // A response could have committed despite a dropped connection. Never
      // retry its page number or cached inventory under the same grant.
      invalidate();
      rethrow;
    } finally {
      release.complete();
    }
  }

  void _requireCurrent() {
    if (_closed || !_isCurrent()) {
      throw StateError('Vault session changed during file download');
    }
  }

  void invalidate() {
    _records = null;
    _export.clearGrant();
  }

  void close() {
    _closed = true;
    invalidate();
  }
}
