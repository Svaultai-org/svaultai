/// Ephemeral, client-decrypted search index for an unlocked ZK vault.
///
/// The server returns only MVK ciphertext and structural file IDs. This class
/// decrypts on the client, keeps search material in memory for one lookup,
/// and never sends private terms, file bytes, or the MVK to general chat.

library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'private_content_pin_guard.dart';
import 'vault_key_hierarchy.dart';
import 'zk_private_chat.dart';
import 'zk_local_photo_colors.dart';
import 'zk_local_photo_description.dart';

typedef ZkPrivateChatGet = Future<Object?> Function(String path);
typedef ZkPrivateLegacyFileInventory = Future<Map<String, dynamic>> Function();
typedef ZkPrivateLegacyTextRead = Future<Uint8List> Function(
  Map<String, dynamic> listed,
);
typedef ZkPrivateLegacyItemInventory = Future<List<Map<String, dynamic>>>
    Function();

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
  static const int maxLegacyFileRows = 500;
  static const int maxFiles = 100;
  static const int maxTextFiles = 16;
  static const int maxTextFileBytes = 128 * 1024;
  static const int maxTotalTextBytes = 512 * 1024;
  static const int maxInspectedPhotos = 12;
  static const int maxTotalInspectedPhotoBytes = 8 * 1024 * 1024;

  final SecretKey mvk;
  final ZkPrivateChatGet get;
  final bool Function() accessIsCurrent;
  final bool includeSavedItems;
  final bool indexTextContent;

  /// Opt-in search of a recording's encrypted transcript metadata or a
  /// same-folder VTT/SRT sidecar. No audio decoding or speech recognition.
  final bool indexAudioTranscripts;
  final bool indexPhotoColors;
  final bool indexPhotoDescriptions;
  final bool includeLegacyDocumentsForRelations;
  final int fileLimit;
  final int textFileLimit;
  final int textFileByteLimit;
  final int extractedTextByteLimit;
  final int totalTextByteLimit;
  final bool allowPartialFileListing;

  /// Optional session-only metadata inventory. The caller must supply it only
  /// when this bearer can open older files through the proof-only reader.
  final ZkPrivateLegacyFileInventory? legacyFileInventory;

  /// An owner-approved, proof-only reader for small older text files. It must
  /// compare the opened source with [listed] and must never send a raw PIN.
  /// The returned bytes are cleared immediately after decoding. An absent
  /// reader keeps the existing filename-only behavior.
  final ZkPrivateLegacyTextRead? legacyFileTextReader;
  final int legacyTextFileLimit;

  /// Trusted-session metadata only. Older item values are never requested or
  /// indexed; a title match cannot claim to answer about the item's contents.
  final ZkPrivateLegacyItemInventory? legacyItemInventory;

  const ZkPrivateChatIndexLoader({
    required this.mvk,
    required this.get,
    required this.accessIsCurrent,
    this.includeSavedItems = true,
    this.indexTextContent = true,
    this.indexAudioTranscripts = false,
    this.indexPhotoColors = false,
    this.indexPhotoDescriptions = false,
    this.includeLegacyDocumentsForRelations = false,
    this.fileLimit = maxFiles,
    this.textFileLimit = maxTextFiles,
    this.textFileByteLimit = maxTextFileBytes,
    this.extractedTextByteLimit = maxTotalTextBytes,
    this.totalTextByteLimit = maxTotalTextBytes,
    this.allowPartialFileListing = false,
    this.legacyFileInventory,
    this.legacyFileTextReader,
    this.legacyTextFileLimit = 4,
    this.legacyItemInventory,
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
              itemType: type,
              searchText: searchText.length > 8192
                  ? searchText.substring(0, 8192)
                  : searchText,
            ),
          );
        } catch (_) {
          incomplete = true;
        }
      }
      if (legacyItemInventory != null) {
        _checkAccess();
        final inventory = await legacyItemInventory!();
        _checkAccess();
        if (inventory.length > maxSavedItems) {
          throw const FormatException(
              'Older saved-item index exceeds safe limit');
        }
        final seenIds = savedItems.map((item) => item.id).toSet();
        for (final raw in inventory) {
          _checkAccess();
          if (raw['is_legacy'] != true) continue;
          try {
            final id = raw['item_id'];
            if (id is! int || id <= 0 || !seenIds.add('$id')) {
              if (id is int && savedItems.any((item) => item.id == '$id')) {
                continue; // The verified V2 copy is already searchable.
              }
              throw const FormatException('Duplicate older item identity');
            }
            Future<String> label(
                String encryptedField, String plainField) async {
              final encrypted = raw[encryptedField];
              if (encrypted is String && encrypted.isNotEmpty) {
                return decryptRequired(encrypted);
              }
              final plain = raw[plainField];
              if (plain is String && plain.isNotEmpty) return plain;
              throw const FormatException('Older item label is unavailable');
            }

            final service =
                (await label('service_ciphertext', 'service')).trim();
            final type =
                (await label('item_type_ciphertext', 'item_type')).trim();
            if (service.isEmpty ||
                service.length > 255 ||
                type.isEmpty ||
                type.length > 128) {
              throw const FormatException('Invalid older item label');
            }
            if (savedItems.length >= maxSavedItems) {
              incomplete = true;
              break;
            }
            savedItems.add(ZkLocalChatRecord(
              kind: ZkLocalChatKind.savedItem,
              id: '$id',
              title: service,
              itemType: type,
              searchText: type,
              legacyProofRequired: true,
            ));
          } catch (_) {
            incomplete = true;
          }
        }
      }
    }

    final listing = await _get('/vault/file-v2');
    if (listing is! Map || listing['files'] is! List) {
      throw const FormatException('Private file index is unavailable');
    }
    final fileRows = listing['files'] as List;
    if (fileLimit < 1 ||
        legacyTextFileLimit < 0 ||
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
    // Caption sidecars are a useful local content source for media, including
    // older media opened through the proof-only reader. Pair only an exact
    // folder and stem with a unique playable file. V2 paths are decrypted on
    // this device; no folder or caption text is sent in the lookup request.
    final mediaPairKeys = <String, String>{};
    final captionPairs = <(String, String)>[];
    var textFiles = 0;
    var textBytes = 0;
    var contentIndexedFiles = 0;
    var legacyTextFiles = 0;
    var inspectedPhotos = 0;
    var inspectedPhotoBytes = 0;
    var mediaScanIncomplete = false;
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
        final mediaKind = _mediaKind(
          manifest.contentType,
          manifest.displayName,
        );
        var content = '';
        var fullTextRead = false;
        final isText = _isTextFile(manifest.contentType, manifest.displayName);
        if (indexTextContent &&
            isText &&
            manifest.totalBytes <= textFileByteLimit &&
            textFiles < textFileLimit &&
            textBytes + manifest.totalBytes <= totalTextByteLimit) {
          final download = await reader.download(manifest.fileId);
          try {
            _checkAccess();
            content = utf8.decode(download.bytes);
          } finally {
            download.bytes.fillRange(0, download.bytes.length, 0);
          }
          fullTextRead = true;
          textFiles++;
          textBytes += manifest.totalBytes;
        } else if (indexTextContent && isText) {
          incomplete = true;
        }
        // A retired legacy file may carry its old OCR, document text, or
        // transcript inside the client-encrypted V2 manifest. Search that
        // text only on this device when full text was not already read.
        final extracted = manifest.extractedText;
        if (indexTextContent &&
            !fullTextRead &&
            (mediaKind != ZkLocalMediaKind.audio || indexAudioTranscripts) &&
            extracted != null &&
            extracted.isNotEmpty) {
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
        var visualColors = const <String>{};
        String? photoDescription;
        if ((indexPhotoColors || indexPhotoDescriptions) &&
            mediaKind == ZkLocalMediaKind.photo) {
          if (manifest.totalBytes <= 0 ||
              manifest.totalBytes > maxLocalPhotoColorBytes ||
              inspectedPhotos >= maxInspectedPhotos ||
              inspectedPhotoBytes + manifest.totalBytes >
                  maxTotalInspectedPhotoBytes) {
            mediaScanIncomplete = true;
          } else {
            inspectedPhotos++;
            inspectedPhotoBytes += manifest.totalBytes;
            try {
              final download = await reader.download(
                manifest.fileId,
                maxBytes: maxLocalPhotoColorBytes,
              );
              try {
                _checkAccess();
                if (indexPhotoColors) {
                  try {
                    visualColors = await observePhotoColors(
                      download.bytes,
                      accessIsCurrent: accessIsCurrent,
                    );
                  } catch (_) {
                    _checkAccess();
                    mediaScanIncomplete = true;
                  }
                }
                if (indexPhotoDescriptions) {
                  try {
                    photoDescription = readEmbeddedJpegDescription(
                      download.bytes,
                      accessIsCurrent: accessIsCurrent,
                    );
                  } catch (_) {
                    _checkAccess();
                    mediaScanIncomplete = true;
                  }
                }
                _checkAccess();
              } finally {
                download.bytes.fillRange(0, download.bytes.length, 0);
              }
            } catch (_) {
              _checkAccess();
              mediaScanIncomplete = true;
            }
          }
        }
        if (mediaKind == ZkLocalMediaKind.video ||
            mediaKind == ZkLocalMediaKind.audio) {
          final key =
              _captionPairKey(manifest.displayName, manifest.relativePath);
          if (key != null) mediaPairKeys[manifest.fileId] = key;
        }
        if (_isCaptionFile(manifest.contentType, manifest.displayName) &&
            fullTextRead) {
          final key =
              _captionPairKey(manifest.displayName, manifest.relativePath);
          final fullTranscript = _captionTranscript(content);
          if (fullTranscript.length > 8192) incomplete = true;
          final transcript = fullTranscript.length > 8192
              ? fullTranscript.substring(0, 8192)
              : fullTranscript;
          if (key != null && transcript.isNotEmpty) {
            captionPairs.add((key, transcript));
          }
        }
        files.add(
          ZkLocalChatRecord(
            kind: ZkLocalChatKind.file,
            id: manifest.fileId,
            title: manifest.displayName,
            searchText: content,
            mimeType: manifest.contentType,
            mediaKind: mediaKind,
            sizeBytes: manifest.totalBytes,
            visualColors: visualColors,
            photoDescription: photoDescription,
          ),
        );
      } catch (_) {
        incomplete = true;
      }
    }
    if (legacyFileInventory != null) {
      _checkAccess();
      final inventory = await legacyFileInventory!();
      _checkAccess();
      final rows = inventory['files'];
      if (rows is! List) {
        throw const FormatException('Older private file index is unavailable');
      }
      if (inventory['truncated'] == true) incomplete = true;
      if (rows.length > maxLegacyFileRows) incomplete = true;
      final seenIds = files.map((file) => file.id).toSet();
      for (final raw in rows.take(maxLegacyFileRows)) {
        _checkAccess();
        if (raw is! Map<String, dynamic>) {
          incomplete = true;
          continue;
        }
        final id = raw['id'];
        if (id is! String ||
            id.isEmpty ||
            id.length > 128 ||
            raw['upload_status'] != 'complete') {
          incomplete = true;
          continue;
        }
        if (seenIds.contains(id) ||
            raw['v2_ready'] == true ||
            raw['v2_retired'] == true) {
          continue;
        }
        final name = raw['saved_name'] is String &&
                (raw['saved_name'] as String).trim().isNotEmpty
            ? (raw['saved_name'] as String).trim()
            : raw['file_name'] is String
                ? (raw['file_name'] as String).trim()
                : '';
        final mime = raw['content_type'];
        final mode = raw['storage_mode'];
        if (name.isEmpty ||
            name.length > 255 ||
            (mime != null && (mime is! String || mime.length > 255)) ||
            (mode != 'inline' && mode != 'chunked' && mode != 'chunks')) {
          incomplete = true;
          continue;
        }
        final kind = _mediaKind(mime as String?, name);
        if (!includeLegacyDocumentsForRelations &&
            kind != ZkLocalMediaKind.photo &&
            kind != ZkLocalMediaKind.video &&
            kind != ZkLocalMediaKind.audio) {
          continue;
        }
        if (files.length >= fileLimit) {
          incomplete = true;
          break;
        }
        var olderText = '';
        final declaredSize = raw['file_size'];
        final canReadOlderText = indexTextContent &&
            legacyFileTextReader != null &&
            _isTextFile(mime, name) &&
            mode == 'inline' &&
            declaredSize is int &&
            declaredSize >= 0 &&
            declaredSize <= textFileByteLimit;
        if (canReadOlderText) {
          if (legacyTextFiles >= legacyTextFileLimit ||
              textFiles >= textFileLimit ||
              textBytes + declaredSize > totalTextByteLimit) {
            incomplete = true;
          } else {
            Uint8List? opened;
            try {
              _checkAccess();
              opened = await legacyFileTextReader!(raw);
              _checkAccess();
              if (opened.length != declaredSize ||
                  opened.length > textFileByteLimit ||
                  textBytes + opened.length > totalTextByteLimit) {
                throw const FormatException('Older text file changed');
              }
              olderText = utf8.decode(opened);
              legacyTextFiles++;
              textFiles++;
              textBytes += opened.length;
              contentIndexedFiles++;
            } catch (_) {
              _checkAccess();
              incomplete = true;
            } finally {
              if (opened != null) opened.fillRange(0, opened.length, 0);
            }
          }
        } else if (indexTextContent &&
            legacyFileTextReader != null &&
            _isTextFile(mime, name)) {
          incomplete = true;
        }
        files.add(
          ZkLocalChatRecord(
            kind: ZkLocalChatKind.file,
            id: id,
            title: name,
            searchText: olderText,
            mimeType: mime,
            mediaKind: kind,
            legacyProofRequired: true,
            sizeBytes: raw['file_size'] is int ? raw['file_size'] as int : null,
          ),
        );
        final path = raw['relative_path'];
        if (kind == ZkLocalMediaKind.video || kind == ZkLocalMediaKind.audio) {
          final key = _captionPairKey(name, path);
          if (key != null) mediaPairKeys[id] = key;
        }
        seenIds.add(id);
      }
    }
    // A caption is associated only when it and one playable media record
    // share a unique folder and basename. Otherwise leave the caption as its
    // own searchable file; guessing a media match could show the wrong item.
    final captionsByKey = <String, List<String>>{};
    for (final (key, transcript) in captionPairs) {
      captionsByKey.putIfAbsent(key, () => []).add(transcript);
    }
    final mediaByKey = <String, List<int>>{};
    for (var i = 0; i < files.length; i++) {
      final file = files[i];
      final key = mediaPairKeys[file.id];
      if (key != null) mediaByKey.putIfAbsent(key, () => []).add(i);
    }
    // An omitted file could have the same stem, so a partial inventory
    // cannot establish the uniqueness required for pairing. A skipped
    // optional photo scan does not make the file inventory incomplete.
    final pairingInventoryComplete = !incomplete;
    for (final entry in captionsByKey.entries) {
      if (!pairingInventoryComplete) break;
      final positions = mediaByKey[entry.key];
      if (entry.value.length != 1 ||
          positions == null ||
          positions.length != 1) {
        incomplete = true;
        continue;
      }
      final at = positions.single;
      final media = files[at];
      if (media.mediaKind == ZkLocalMediaKind.audio && !indexAudioTranscripts) {
        continue;
      }
      final caption = entry.value.single;
      files[at] = ZkLocalChatRecord(
        kind: media.kind,
        id: media.id,
        title: media.title,
        searchText: '${media.searchText} $caption'.trim(),
        mimeType: media.mimeType,
        mediaKind: media.mediaKind,
        legacyProofRequired: media.legacyProofRequired,
        sizeBytes: media.sizeBytes,
        visualColors: media.visualColors,
        photoDescription: media.photoDescription,
      );
    }
    _checkAccess();
    return ZkPrivateChatIndex(
      savedItems: savedItems,
      files: files,
      incomplete: incomplete || mediaScanIncomplete,
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
        lowerName.endsWith('.json') ||
        _isCaptionFile(mime, name);
  }

  static bool _isCaptionFile(String? mime, String name) {
    final lowerMime = (mime ?? '').toLowerCase();
    final lowerName = name.toLowerCase();
    return lowerMime == 'text/vtt' ||
        lowerMime == 'application/x-subrip' ||
        lowerName.endsWith('.vtt') ||
        lowerName.endsWith('.srt');
  }

  static String? _mediaStem(String name) {
    final trimmed = name.trim().toLowerCase();
    final dot = trimmed.lastIndexOf('.');
    if (dot <= 0) return null;
    final stem = trimmed.substring(0, dot).trim();
    return stem.isEmpty ? null : stem;
  }

  static String? _captionPairKey(String displayName, Object? relativePath) {
    var name = displayName;
    var folder = '';
    if (relativePath != null) {
      if (relativePath is! String) return null;
      final path = relativePath.trim();
      if (path.isNotEmpty) {
        final parts = path.split('/');
        if (parts.any((part) => part.isEmpty || part == '.' || part == '..')) {
          return null;
        }
        name = parts.last;
        folder = parts.length == 1
            ? ''
            : parts.sublist(0, parts.length - 1).join('/');
      }
    }
    final stem = _mediaStem(name);
    return stem == null ? null : '$folder\u0000$stem';
  }

  static String _captionTranscript(String raw) {
    final lines = <String>[];
    var skipBlock = false;
    for (final source in raw.split(RegExp(r'\r?\n'))) {
      final line = source.trim();
      if (line.isEmpty) {
        skipBlock = false;
        continue;
      }
      if (line == 'WEBVTT') continue;
      if (RegExp(r'^(NOTE|STYLE|REGION)(?:\s|$)').hasMatch(line)) {
        skipBlock = true;
        continue;
      }
      if (skipBlock ||
          line.contains('-->') ||
          RegExp(r'^\d+$').hasMatch(line)) {
        continue;
      }
      final text = line.replaceAll(RegExp(r'<[^>]{1,100}>'), ' ').trim();
      if (text.isNotEmpty) lines.add(text);
    }
    return lines.join(' ');
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

/// Suggest verified V2 files and, when offered, older files by comparing
/// saved names and bounded locally available V2 text on the current device.
/// No PIN, query, MVK, filename, or decrypted content is sent to the server.
Future<Map<String, dynamic>> loadZkLocalRelatedFilesEnvelope({
  required String fileId,
  required SecretKey mvk,
  required ZkPrivateChatGet get,
  required bool Function() accessIsCurrent,
  ZkPrivateLegacyFileInventory? legacyFileInventory,
}) async {
  if (fileId.trim().isEmpty) throw ArgumentError('Missing file ID');
  final index = await ZkPrivateChatIndexLoader(
    mvk: mvk,
    get: get,
    accessIsCurrent: accessIsCurrent,
    legacyFileInventory: legacyFileInventory,
    includeLegacyDocumentsForRelations: true,
    includeSavedItems: false,
    // Keep this tap bounded; only ciphertext crosses the wire and text is
    // compared on the device. Older files without a proof reader stay at
    // saved-name-only relations.
    indexTextContent: true,
    textFileLimit: 16,
    textFileByteLimit: 64 * 1024,
    extractedTextByteLimit: 64 * 1024,
    totalTextByteLimit: 512 * 1024,
  ).load();
  if (!accessIsCurrent()) throw StateError('Vault access changed');
  final anchors = index.files.where((file) => file.id == fileId).toList();
  if (anchors.length != 1) {
    throw const PrivateContentSearchUnavailable(
      'This file is not available in the private search index.',
    );
  }
  final anchor = anchors.single;
  return ZkLocalFileRelations.envelope(
    anchor: anchor,
    matches: ZkLocalFileRelations.related(anchor, index.files),
    incomplete: index.incomplete,
  );
}
