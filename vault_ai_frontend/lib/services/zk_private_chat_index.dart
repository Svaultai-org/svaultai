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

  const ZkPrivateChatIndex({
    required this.savedItems,
    required this.files,
    required this.incomplete,
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

  const ZkPrivateChatIndexLoader({
    required this.mvk,
    required this.get,
    required this.accessIsCurrent,
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
    final savedItems = <ZkLocalChatRecord>[];
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
        savedItems.add(ZkLocalChatRecord(
          kind: ZkLocalChatKind.savedItem,
          id: id.toString(),
          title: service.trim().isEmpty ? type : service,
          searchText: searchText.length > 8192
              ? searchText.substring(0, 8192)
              : searchText,
        ));
      } catch (_) {
        incomplete = true;
      }
    }

    final listing = await _get('/vault/file-v2');
    if (listing is! Map || listing['files'] is! List) {
      throw const FormatException('Private file index is unavailable');
    }
    final fileRows = listing['files'] as List;
    if (fileRows.length > maxFiles) {
      throw const FormatException('Private file index exceeds safe limit');
    }
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
    for (final row in fileRows) {
      _checkAccess();
      if (row is! Map || row['file_id'] is! String) {
        incomplete = true;
        continue;
      }
      // Only these records have a guaranteed PIN-free file viewer path.
      // A staged record must never become a card that can fall back to a
      // legacy raw-PIN download when tapped.
      if (row['verification_state'] != 'client_verified' ||
          row['lifecycle_state'] != 'legacy_migration_retired') {
        incomplete = true;
        continue;
      }
      try {
        final manifest = await reader.readManifest(row['file_id'] as String);
        _checkAccess();
        var content = '';
        final isText = _isTextFile(manifest.contentType, manifest.displayName);
        if (isText &&
            manifest.totalBytes <= maxTextFileBytes &&
            textFiles < maxTextFiles &&
            textBytes + manifest.totalBytes <= maxTotalTextBytes) {
          final download = await reader.download(manifest.fileId);
          _checkAccess();
          content = utf8.decode(download.bytes);
          textFiles++;
          textBytes += manifest.totalBytes;
        } else if (isText) {
          incomplete = true;
        }
        files.add(ZkLocalChatRecord(
          kind: ZkLocalChatKind.file,
          id: manifest.fileId,
          title: manifest.displayName,
          searchText: content,
          mimeType: manifest.contentType,
          mediaKind: _mediaKind(manifest.contentType, manifest.displayName),
        ));
      } catch (_) {
        incomplete = true;
      }
    }
    _checkAccess();
    return ZkPrivateChatIndex(
      savedItems: savedItems,
      files: files,
      incomplete: incomplete,
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
