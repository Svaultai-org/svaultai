// Bounded, session-only reader for legacy encrypted content. Every export
// grant is obtained through a fresh OPAQUE PIN proof. No plaintext, PIN, key,
// or export grant is persisted by this client.

typedef LegacyExportPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body,
);

typedef LegacyProofProvider = Future<String> Function();

class LegacyCiphertextExportClient {
  static const int maxReadChars = 4 * 1024 * 1024;
  static const int maxTotalChars = 64 * 1024 * 1024;

  final LegacyExportPost post;
  final LegacyProofProvider proofProvider;

  String? _exportToken;
  int _sequence = 0;
  int _pagesRemaining = 0;

  LegacyCiphertextExportClient({
    required this.post,
    required this.proofProvider,
  });

  void clearGrant() {
    _exportToken = null;
    _sequence = 0;
    _pagesRemaining = 0;
  }

  Future<List<Map<String, dynamic>>> listItems() => _list(
        mode: 'list_items',
        afterKey: 'after_item_id',
        nextKey: 'next_after_item_id',
        idKey: 'item_id',
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
  }) {
    if (itemId <= 0) throw const FormatException('Invalid item ID');
    return _read('read_item', 'item_id', itemId, ciphertextChars);
  }

  Future<String> readFileCiphertext({
    required String fileId,
    required int ciphertextChars,
  }) {
    if (fileId.isEmpty) throw const FormatException('Invalid file ID');
    return _read('read_file', 'file_id', fileId, ciphertextChars);
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
    if (token is! String ||
        token.isEmpty ||
        sequence != 0 ||
        remaining is! int ||
        remaining <= 0) {
      throw const FormatException('Invalid export grant');
    }
    _exportToken = token;
    _sequence = 0;
    _pagesRemaining = remaining;
  }

  Future<Map<String, dynamic>> _page(Map<String, dynamic> body) async {
    if (_exportToken == null || _pagesRemaining <= 0) await _startGrant();
    final token = _exportToken!;
    final sequence = _sequence;
    try {
      final response = await post(
        '/vault/legacy-ciphertext/export/page',
        <String, dynamic>{
          'export_token': token,
          'sequence': sequence,
          ...body,
        },
      );
      final next = response['next_sequence'];
      final remaining = response['pages_remaining'];
      if (next != sequence + 1 || remaining is! int || remaining < 0) {
        throw const FormatException('Invalid export page cursor');
      }
      _sequence = next;
      _pagesRemaining = remaining;
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
  }) async {
    try {
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

  Future<String> _read(
    String mode,
    String idKey,
    Object id,
    int expectedChars,
  ) async {
    if (expectedChars <= 0 || expectedChars > maxTotalChars) {
      throw const FormatException('Invalid ciphertext length');
    }
    try {
      final text = StringBuffer();
      var offset = 0;
      while (offset < expectedChars) {
        final response = await _page(<String, dynamic>{
          'mode': mode,
          idKey: id,
          'offset': offset,
          'max_chars': maxReadChars,
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
            done != (next == expectedChars)) {
          throw const FormatException('Invalid ciphertext export chunk');
        }
        text.write(chunk);
        offset = next;
      }
      return text.toString();
    } catch (_) {
      clearGrant();
      rethrow;
    }
  }
}
