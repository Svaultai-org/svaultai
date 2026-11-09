// Bounded, session-only reader for legacy encrypted content. Every export
// grant is obtained through a fresh OPAQUE PIN proof. No plaintext, PIN, key,
// or export grant is persisted by this client.

import 'dart:convert';

typedef LegacyExportPost =
    Future<Map<String, dynamic>> Function(
      String path,
      Map<String, dynamic> body,
    );

typedef LegacyProofProvider = Future<String> Function();

class LegacyCiphertextSource {
  final String ciphertext;
  final String sourceSnapshot;
  final String? deleteSnapshot;
  final Map<String, dynamic> sourceMetadata;

  const LegacyCiphertextSource({
    required this.ciphertext,
    required this.sourceSnapshot,
    this.deleteSnapshot,
    required this.sourceMetadata,
  });
}

class LegacyCiphertextExportClient {
  static const int maxReadChars = 4 * 1024 * 1024;
  // Item source pages may also carry three staged V2 ciphertexts (up to
  // 128 KiB each before base64). Leave space under the server's page cap.
  static const int maxItemSourceReadChars = 3 * 1024 * 1024;
  static const int maxTotalChars = 64 * 1024 * 1024;
  // The server will refuse a page whose charge exceeds its remaining grant.
  // Renew before a page when the old grant cannot cover its maximum charge.
  static const int maxPageCharge = maxReadChars + 64 * 1024;
  static const int grantMaxBytes = 32 * 1024 * 1024;
  static const Duration grantExpiryMargin = Duration(seconds: 30);

  final LegacyExportPost post;
  final LegacyProofProvider proofProvider;

  String? _exportToken;
  int _sequence = 0;
  int _pagesRemaining = 0;
  int _bytesRemaining = 0;
  DateTime? _expiresAt;

  LegacyCiphertextExportClient({
    required this.post,
    required this.proofProvider,
  });

  void clearGrant() {
    _exportToken = null;
    _sequence = 0;
    _pagesRemaining = 0;
    _bytesRemaining = 0;
    _expiresAt = null;
  }

  Future<List<Map<String, dynamic>>> listItems() => _list(
    mode: 'list_items',
    afterKey: 'after_item_id',
    nextKey: 'next_after_item_id',
    idKey: 'item_id',
  );

  Future<List<Map<String, dynamic>>> listItemsBounded({
    required int maxRecords,
  }) => _list(
    mode: 'list_items',
    afterKey: 'after_item_id',
    nextKey: 'next_after_item_id',
    idKey: 'item_id',
    maxRecords: maxRecords,
  );

  Future<List<Map<String, dynamic>>> listFiles() => _list(
    mode: 'list_files',
    afterKey: 'after_file_id',
    nextKey: 'next_after_file_id',
    idKey: 'file_id',
  );

  Future<String> readItemCiphertext({
    required int itemId,
    required int ciphertextChars,
  }) async {
    if (itemId <= 0) throw const FormatException('Invalid item ID');
    return (await _read(
      'read_item',
      'item_id',
      itemId,
      ciphertextChars,
    )).ciphertext;
  }

  Future<String> readFileCiphertext({
    required String fileId,
    required int ciphertextChars,
  }) async {
    if (fileId.isEmpty) throw const FormatException('Invalid file ID');
    return (await _read(
      'read_file',
      'file_id',
      fileId,
      ciphertextChars,
    )).ciphertext;
  }

  Future<LegacyCiphertextSource> readItemSource({
    required int itemId,
    required int ciphertextChars,
  }) {
    if (itemId <= 0) throw const FormatException('Invalid item ID');
    return _read(
      'read_item',
      'item_id',
      itemId,
      ciphertextChars,
      requireSource: true,
    );
  }

  Future<LegacyCiphertextSource> readFileSource({
    required String fileId,
    required int ciphertextChars,
  }) {
    if (fileId.isEmpty) throw const FormatException('Invalid file ID');
    return _read(
      'read_file',
      'file_id',
      fileId,
      ciphertextChars,
      requireSource: true,
    );
  }

  /// Read legacy file-only fields once under the same OPAQUE proof grant.
  /// The source snapshot must match the ciphertext export exactly; these
  /// plaintext fields are then encrypted locally into the V2 manifest.
  Future<Map<String, String?>> readFileExtras({
    required String fileId,
    required String sourceSnapshot,
    bool useV3 = false,
  }) async {
    if (fileId.isEmpty ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(sourceSnapshot)) {
      throw const FormatException('Invalid legacy file extra request');
    }
    try {
      final response = await _page(<String, dynamic>{
        'mode': useV3 ? 'read_file_extra_v3' : 'read_file_extra',
        'file_id': fileId,
      });
      final extras = response['legacy_extra'];
      if (response['file_id'] != fileId ||
          response['source_snapshot'] != sourceSnapshot ||
          (useV3 && response['legacy_extra_version'] != 3) ||
          extras is! Map<String, dynamic> ||
          extras.length != 2 ||
          !extras.containsKey('relative_path') ||
          !extras.containsKey('extracted_text')) {
        throw const FormatException('Legacy file extra source changed');
      }
      final path = extras['relative_path'];
      final text = extras['extracted_text'];
      if ((path != null && path is! String) ||
          (text != null && text is! String) ||
          (path is String && utf8.encode(path).length > 4096) ||
          (text is String && utf8.encode(text).length >
              (useV3 ? 256 * 1024 : 64 * 1024))) {
        throw const FormatException('Invalid legacy file extra shape');
      }
      return <String, String?>{
        'relative_path': path as String?,
        'extracted_text': text as String?,
      };
    } catch (_) {
      clearGrant();
      rethrow;
    }
  }

  Future<void> _startGrant() async {
    final proof = await proofProvider();
    if (proof.isEmpty) throw StateError('PIN proof is unavailable');
    final response = await post(
      '/vault/legacy-ciphertext/export/start',
      <String, dynamic>{'zk_proof_token': proof},
    );
    final token = response['export_token'];
    final sequence = response['next_sequence'];
    final remaining = response['pages_remaining'];
    final bytesRemaining = response['bytes_remaining'];
    final expiresAt = DateTime.tryParse('${response['expires_at']}')?.toUtc();
    if (token is! String ||
        token.isEmpty ||
        sequence != 0 ||
        remaining is! int ||
        remaining <= 0 ||
        bytesRemaining is! int ||
        bytesRemaining < maxPageCharge ||
        bytesRemaining > grantMaxBytes ||
        expiresAt == null ||
        !expiresAt.isAfter(DateTime.now().toUtc().add(grantExpiryMargin))) {
      throw const FormatException('Invalid export grant');
    }
    _exportToken = token;
    _sequence = 0;
    _pagesRemaining = remaining;
    _bytesRemaining = bytesRemaining;
    _expiresAt = expiresAt;
  }

  Future<Map<String, dynamic>> _page(Map<String, dynamic> body) async {
    if (_exportToken == null ||
        _pagesRemaining <= 0 ||
        _bytesRemaining < maxPageCharge ||
        _expiresAt == null ||
        !_expiresAt!.isAfter(DateTime.now().toUtc().add(grantExpiryMargin))) {
      clearGrant();
      await _startGrant();
    }
    final token = _exportToken!;
    final sequence = _sequence;
    final priorBytes = _bytesRemaining;
    try {
      final response = await post(
        '/vault/legacy-ciphertext/export/page',
        <String, dynamic>{'export_token': token, 'sequence': sequence, ...body},
      );
      final next = response['next_sequence'];
      final remaining = response['pages_remaining'];
      final bytesRemaining = response['bytes_remaining'];
      if (next != sequence + 1 || remaining is! int || remaining < 0 ||
          bytesRemaining is! int || bytesRemaining < 0 ||
          bytesRemaining >= priorBytes) {
        throw const FormatException('Invalid export page cursor');
      }
      _sequence = next;
      _pagesRemaining = remaining;
      _bytesRemaining = bytesRemaining;
      return response;
    } catch (_) {
      // A response might have been committed server-side before the network
      // failed. Never retry a sequence: a later call obtains a fresh grant.
      clearGrant();
      rethrow;
    }
  }

  Future<List<Map<String, dynamic>>> _list({
    required String mode,
    required String afterKey,
    required String nextKey,
    required String idKey,
    int maxRecords = 50000,
  }) async {
    try {
      if (maxRecords <= 0 || maxRecords > 50000) {
        throw const FormatException('Invalid export inventory limit');
      }
      final result = <Map<String, dynamic>>[];
      Object? after;
      for (var pages = 0; pages < 1000; pages++) {
        final response = await _page(<String, dynamic>{
          'mode': mode,
          'limit': 50,
          if (after != null) afterKey: after,
        });
        final rows = response['records'];
        final hasMore = response['has_more'];
        if (rows is! List || hasMore is! bool) {
          throw const FormatException('Invalid export listing');
        }
        for (final row in rows) {
          if (row is! Map<String, dynamic> || row[idKey] == null) {
            throw const FormatException('Invalid export record');
          }
          result.add(row);
          if (result.length > maxRecords) {
            throw const FormatException('Export inventory exceeded limit');
          }
        }
        if (!hasMore) return result;
        final next = response[nextKey];
        if (rows.isEmpty || next == null || next == after) {
          throw const FormatException('Export listing did not advance');
        }
        after = next;
      }
      throw StateError('Export listing exceeded page limit');
    } catch (_) {
      clearGrant();
      rethrow;
    }
  }

  Future<LegacyCiphertextSource> _read(
    String mode,
    String idKey,
    Object id,
    int expectedChars, {
    bool requireSource = false,
  }) async {
    if (expectedChars <= 0 || expectedChars > maxTotalChars) {
      throw const FormatException('Invalid ciphertext length');
    }
    try {
      final text = StringBuffer();
      var offset = 0;
      String? snapshot;
      String? deleteSnapshot;
      Map<String, dynamic>? metadata;
      bool? hasSourceShape;
      bool? hasDeleteShape;
      while (offset < expectedChars) {
        final response = await _page(<String, dynamic>{
          'mode': mode,
          idKey: id,
          'offset': offset,
          'max_chars': mode == 'read_item' && requireSource
              ? maxItemSourceReadChars
              : maxReadChars,
        });
        final chunk = response['ciphertext_chunk'];
        final total = response['total_chars'];
        final current = response['offset'];
        final next = response['next_offset'];
        final done = response['done'];
        if (chunk is! String ||
            chunk.isEmpty ||
            total != expectedChars ||
            current != offset ||
            next is! int ||
            next != offset + chunk.length ||
            next > expectedChars ||
            done is! bool ||
            done != (next == expectedChars) ||
            (requireSource && response[idKey] != id)) {
          throw const FormatException('Invalid ciphertext export chunk');
        }
        final rawSnapshot = response['source_snapshot'];
        final rawDeleteSnapshot = response['delete_snapshot'];
        final rawMetadata = response['source_metadata'];
        final hasDelete = rawDeleteSnapshot != null;
        if (hasDeleteShape != null && hasDeleteShape != hasDelete) {
          throw const FormatException('Delete source changed during export');
        }
        hasDeleteShape = hasDelete;
        if (hasDelete) {
          if (mode != 'read_item' || rawDeleteSnapshot is! String ||
              !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(rawDeleteSnapshot) ||
              (deleteSnapshot != null && deleteSnapshot != rawDeleteSnapshot)) {
            throw const FormatException('Invalid delete source snapshot');
          }
          deleteSnapshot = rawDeleteSnapshot;
        }
        final hasSource = rawSnapshot != null || rawMetadata != null;
        if (hasSourceShape != null && hasSourceShape != hasSource) {
          throw const FormatException('Legacy source changed during export');
        }
        hasSourceShape = hasSource;
        if (!hasSource && !requireSource) {
          // Older read-only callers still accept the pre-snapshot export
          // shape; staging always requires the locked source contract.
        } else {
          if (rawSnapshot is! String ||
              !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(rawSnapshot) ||
              rawMetadata is! Map<String, dynamic>) {
            throw const FormatException('Invalid legacy source snapshot');
          }
          if (snapshot == null) {
            snapshot = rawSnapshot;
            metadata = Map<String, dynamic>.from(rawMetadata);
          } else if (snapshot != rawSnapshot ||
              jsonEncode(metadata) != jsonEncode(rawMetadata)) {
            throw const FormatException('Legacy source changed during export');
          }
        }
        text.write(chunk);
        offset = next;
      }
      if (requireSource && (snapshot == null || metadata == null)) {
        throw const FormatException('Legacy source snapshot is unavailable');
      }
      return LegacyCiphertextSource(
        ciphertext: text.toString(),
        sourceSnapshot: snapshot ?? '',
        deleteSnapshot: deleteSnapshot,
        sourceMetadata: metadata ?? const <String, dynamic>{},
      );
    } catch (_) {
      clearGrant();
      rethrow;
    }
  }
}
