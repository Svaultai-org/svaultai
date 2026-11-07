/// Ephemeral, client-decrypted search index for an unlocked ZK vault.
///
/// The server returns only MVK ciphertext and structural file IDs. This class
/// decrypts on the client, keeps search material in memory for one lookup,
/// and never sends private terms, file bytes, or the MVK to general chat.

library;

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'vault_key_hierarchy.dart';
import 'zk_private_chat.dart';

typedef ZkPrivateChatGet = Future<Object?> Function(String path);

class ZkPrivateChatIndex {
  final List<ZkLocalChatRecord> savedItems;
  final List<ZkLocalChatRecord> files;
  final bool incomplete;
  final int totalListedFiles;
  final int contentIndexedFiles;

  const ZkPrivateChatIndex({
    required this.savedItems,
    required this.files,
    required this.incomplete,
    this.totalListedFiles = 0,
    this.contentIndexedFiles = 0,
  });
}

class ZkPrivateChatIndexLoader {
  static const int maxSavedItems = 500;
  static const int maxFiles = 100;
  static const int maxTextFiles = 16;
  static const int maxTextFileBytes = 128 * 1024;
  static const int maxTotalTextBytes = 512 * 1024;

  final SecretKey mvk;
  final ZkPrivateChatGet get;
  final bool Function() accessIsCurrent;
  final bool includeSavedItems;
  final int fileLimit;
  final int textFileLimit;
  final int textFileByteLimit;
  final int extractedTextByteLimit;
  final int totalTextByteLimit;
  final bool allowPartialFileListing;

  const ZkPrivateChatIndexLoader({
    required this.mvk,
    required this.get,
    required this.accessIsCurrent,
    this.includeSavedItems = true,
    this.fileLimit = maxFiles,
    this.textFileLimit = maxTextFiles,
    this.textFileByteLimit = maxTextFileBytes,
    this.extractedTextByteLimit = maxTotalTextBytes,
    this.totalTextByteLimit = maxTotalTextBytes,
    this.allowPartialFileListing = false,
  });

  void _checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Vault access changed during private search');
    }
  }

  Future<Object?> _get(String path) async {
    _checkAccess();
    final result = await get(path);
    _checkAccess();
    return result;
  }

  Future<ZkPrivateChatIndex> load() async {
    _checkAccess();
    var incomplete = false;
    final savedItems = <ZkLocalChatRecord>[];
    if (includeSavedItems) {
      final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
      _checkAccess();

      Future<String> decryptRequired(Object? encoded) async {
        if (encoded is! String || encoded.isEmpty) {
          throw const FormatException('Missing private item ciphertext');
        }
        final clear = await aesGcmUnwrap(metadataKey, b64urlDecode(encoded));
        _checkAccess();
        return utf8.decode(clear);
      }

      final itemResponse = await _get('/vault/ciphertext/vault-items');
      if (itemResponse is! List || itemResponse.length > maxSavedItems) {
        throw const FormatException('Private saved-item index is unavailable');
      }
      for (final raw in itemResponse) {
        _checkAccess();
        if (raw is! Map) {
          incomplete = true;
          continue;
        }
        try {
          final id = raw['item_id'];
          if (id is! int || id <= 0) {
            throw const FormatException('Invalid item ID');
          }
          final service = await decryptRequired(raw['service_ciphertext']);
          final type = await decryptRequired(raw['item_type_ciphertext']);
          final payload = jsonDecode(
            await decryptRequired(raw['payload_ciphertext']),
          );
          if (payload is! Map) {
            throw const FormatException('Invalid private item');
          }
          final notes =
              payload['notes'] is String ? payload['notes'] as String : '';
          final fields = payload['fields'];
          final extra = <String>[];
          if (fields is Map) {
            const searchable = {
              'username',
              'email',
              'url',
              'website',
              'account_name',
              'label',
              'description',
            };
            for (final entry in fields.entries) {
              if (!searchable.contains(entry.key.toString().toLowerCase())) {
                continue;
              }
              final value = entry.value;
              if (value is String) extra.add(value);
            }
          }
          final searchText = '$type $notes ${extra.join(' ')}';
          savedItems.add(
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.savedItem,
              id: id.toString(),
              title: service.trim().isEmpty ? type : service,
              searchText: searchText.length > 8192
                  ? searchText.substring(0, 8192)
                  : searchText,
            ),
          );
        } catch (_) {
          incomplete = true;
        }
      }
    }

    final listing = await _get('/vault/file-v2');
    if (listing is! Map || listing['files'] is! List) {
      throw const FormatException('Private file index is unavailable');
    }
    final fileRows = listing['files'] as List;
    if (fileLimit < 1 ||
        textFileLimit < 0 ||
        textFileByteLimit < 0 ||
        extractedTextByteLimit < 0 ||
        totalTextByteLimit < 0) {
      throw ArgumentError('Invalid private file scan limits');
    }
    if (fileRows.length > fileLimit && !allowPartialFileListing) {
      throw const FormatException('Private file index exceeds safe limit');
    }
    if (fileRows.length > fileLimit) incomplete = true;
    final reader = FileV2Reader(
      mvk: mvk,
      get: (path) async {
        final result = await _get(path);
        if (result is! Map) {
          throw const FormatException('Invalid private file response');
        }
        return Map<String, dynamic>.from(result);
      },
    );
    final files = <ZkLocalChatRecord>[];
    var textFiles = 0;
    var textBytes = 0;
    var contentIndexedFiles = 0;
    for (final row in fileRows.take(fileLimit)) {
      _checkAccess();
      if (row is! Map || row['file_id'] is! String) {
        incomplete = true;
        continue;
      }
      // Only verified records have a guaranteed PIN-free file viewer path.
      // A staged record must never become a card that can fall back to a
      // legacy raw-PIN download when tapped.
      if (row['verification_state'] != 'client_verified' ||
          (row['lifecycle_state'] != 'legacy_migration_retired' &&
              row['lifecycle_state'] != 'client_v2_ready')) {
        incomplete = true;
        continue;
      }
      try {
        final manifest = await reader.readManifest(row['file_id'] as String);
        _checkAccess();
        var content = '';
        var fullTextRead = false;
        final isText = _isTextFile(manifest.contentType, manifest.displayName);
        if (isText &&
            manifest.totalBytes <= textFileByteLimit &&
            textFiles < textFileLimit &&
            textBytes + manifest.totalBytes <= totalTextByteLimit) {
          final download = await reader.download(manifest.fileId);
          _checkAccess();
          content = utf8.decode(download.bytes);
          fullTextRead = true;
          textFiles++;
          textBytes += manifest.totalBytes;
        } else if (isText) {
          incomplete = true;
        }
        // A retired legacy file may carry its old OCR, document text, or
        // transcript inside the client-encrypted V2 manifest. Search that
        // text only on this device when full text was not already read.
        final extracted = manifest.extractedText;
        if (!fullTextRead && extracted != null && extracted.isNotEmpty) {
          final extractedBytes = utf8.encode(extracted).length;
          if (extractedBytes <= extractedTextByteLimit &&
              textFiles < textFileLimit &&
              textBytes + extractedBytes <= totalTextByteLimit) {
            content = extracted;
            textFiles++;
            textBytes += extractedBytes;
            fullTextRead = true;
          } else {
            incomplete = true;
          }
        }
        if (fullTextRead) contentIndexedFiles++;
        files.add(
          ZkLocalChatRecord(
            kind: ZkLocalChatKind.file,
            id: manifest.fileId,
            title: manifest.displayName,
            searchText: content,
            mimeType: manifest.contentType,
            mediaKind: _mediaKind(manifest.contentType, manifest.displayName),
          ),
        );
      } catch (_) {
        incomplete = true;
      }
    }
    _checkAccess();
    return ZkPrivateChatIndex(
      savedItems: savedItems,
      files: files,
      incomplete: incomplete,
      totalListedFiles: fileRows.length,
      contentIndexedFiles: contentIndexedFiles,
    );
  }

  static bool _isTextFile(String? mime, String name) {
    final lowerMime = (mime ?? '').toLowerCase();
    final lowerName = name.toLowerCase();
    return lowerMime.startsWith('text/') ||
        lowerMime == 'application/json' ||
        lowerName.endsWith('.txt') ||
        lowerName.endsWith('.md') ||
        lowerName.endsWith('.json');
  }

  static ZkLocalMediaKind _mediaKind(String? mime, String name) {
    final lowerMime = (mime ?? '').toLowerCase();
    final lowerName = name.toLowerCase();
    if (lowerMime.startsWith('image/') ||
        RegExp(r'\.(jpg|jpeg|png|heic|webp|gif)$').hasMatch(lowerName)) {
      return ZkLocalMediaKind.photo;
    }
    if (lowerMime.startsWith('video/') ||
        RegExp(r'\.(mp4|mov|m4v|webm)$').hasMatch(lowerName)) {
      return ZkLocalMediaKind.video;
    }
    if (lowerMime.startsWith('audio/') ||
        RegExp(r'\.(m4a|mp3|wav|aac|ogg)$').hasMatch(lowerName)) {
      return ZkLocalMediaKind.audio;
    }
    if (lowerMime == 'application/pdf' ||
        lowerMime.startsWith('text/') ||
        lowerName.endsWith('.pdf') ||
        lowerName.endsWith('.txt')) {
      return ZkLocalMediaKind.document;
    }
    return ZkLocalMediaKind.other;
  }
}
