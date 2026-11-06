import 'dart:async';

import 'legacy_ciphertext_export_client.dart';

/// One unlocked OPAQUE session's bounded legacy item reader. Export page
/// sequence numbers are single use, so concurrent details share a queue.
/// The grant and list never leave memory and are discarded on lock/switch.
final class LegacySavedItemReadSession {
  LegacySavedItemReadSession({
    required LegacyCiphertextExportClient export,
    required bool Function() isCurrent,
  }) : _export = export, _isCurrent = isCurrent;

  final LegacyCiphertextExportClient _export;
  final bool Function() _isCurrent;
  Future<void> _tail = Future<void>.value();
  List<Map<String, dynamic>>? _records;
  bool _closed = false;

  Future<({Map<String, dynamic> record, String ciphertext})> readItem(
    int itemId,
  ) async {
    if (itemId <= 0) throw ArgumentError.value(itemId, 'itemId');
    final previous = _tail;
    final release = Completer<void>();
    _tail = release.future;
    await previous;
    try {
      _requireCurrent();
      final records = _records ??= await _export.listItems();
      _requireCurrent();
      final matches = records.where((row) => row['item_id'] == itemId).toList();
      if (matches.length != 1) throw StateError('Saved item is unavailable');
      final record = matches.single;
      final chars = record['ciphertext_chars'];
      if (chars is! int) throw const FormatException('Invalid saved-item size');
      final ciphertext = await _export.readItemCiphertext(
        itemId: itemId, ciphertextChars: chars,
      );
      _requireCurrent();
      return (record: record, ciphertext: ciphertext);
    } catch (_) {
      // A stale list or partially committed page must never be retried with
      // its old sequence. The next call obtains a fresh proof and inventory.
      _records = null;
      _export.clearGrant();
      rethrow;
    } finally {
      release.complete();
    }
  }

  void _requireCurrent() {
    if (_closed || !_isCurrent()) {
      throw StateError('Vault session changed during saved-item read');
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
