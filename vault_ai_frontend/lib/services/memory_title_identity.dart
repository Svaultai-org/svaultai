import 'vault_local_content_command.dart';

const String kMemoryTitleConflictMessage =
    'A memory with this title already exists. Choose a different title, '
    'or edit the existing memory.';

class MemoryTitleConflictException implements Exception {
  const MemoryTitleConflictException();

  @override
  String toString() => kMemoryTitleConflictMessage;
}

String _normalizedMemoryTitle(String title) =>
    title.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

bool memoryTitleConflicts({
  required String title,
  required Iterable<Map<String, dynamic>> memories,
  String? editingMemoryId,
}) {
  final wanted = _normalizedMemoryTitle(title);
  if (wanted.isEmpty) return false;
  for (final row in memories) {
    final id = '${row['id'] ?? ''}'.trim();
    if (editingMemoryId != null && id == editingMemoryId) continue;
    final existing = '${row['title'] ?? row['memory_key'] ?? ''}';
    if (_normalizedMemoryTitle(existing) == wanted) return true;
  }
  return false;
}

/// The shared matcher intentionally refuses equal-score matches. Distinguish
/// that safe refusal from "nothing exists" without guessing a record ID.
bool memoryQueryIsAmbiguous({
  required String query,
  required Iterable<VaultLocalContentEntry> entries,
}) {
  final rows = entries.toList();
  final exact = rows.where((entry) =>
      _normalizedMemoryTitle(entry.label) == _normalizedMemoryTitle(query));
  if (exact.length > 1) return true;
  if (exact.length == 1) return false;
  var best = 0;
  var bestCount = 0;
  for (final entry in rows) {
    final match = resolveVaultLocalContentMatch(query: query, entries: [entry]);
    if (match == null) continue;
    if (match.score > best) {
      best = match.score;
      bestCount = 1;
    } else if (match.score == best) {
      bestCount++;
    }
  }
  return bestCount > 1;
}

/// Literal memory titles can contain any script or emoji. Do not remove those
/// characters before an exact comparison, and never pick one duplicate ID.
VaultLocalContentMatch? resolveMemoryLocalContentMatch({
  required String query,
  required Iterable<VaultLocalContentEntry> entries,
}) {
  final rows = entries.toList();
  final wanted = _normalizedMemoryTitle(query);
  if (wanted.isEmpty) return null;
  final exact = rows
      .where((entry) => _normalizedMemoryTitle(entry.label) == wanted)
      .toList();
  if (exact.length == 1) {
    return VaultLocalContentMatch(entry: exact.single, score: 130);
  }
  if (exact.length > 1) return null;
  return resolveVaultLocalContentMatch(query: query, entries: rows);
}

String memoryLocalReply(Map<String, dynamic> row) {
  final label = '${row['title'] ?? row['memory_key'] ?? 'Memory'}'.trim();
  final lines = <String>[];
  for (final raw in [row['value'], row['memory_value'], row['body']]) {
    final text = '${raw ?? ''}'.trim();
    if (text.isNotEmpty && !lines.contains(text)) lines.add(text);
  }
  final fields = row['custom_fields'];
  if (fields is List) {
    for (final field in fields.whereType<Map>()) {
      final key = '${field['label'] ?? ''}'.trim();
      final value = '${field['value'] ?? ''}'.trim();
      if (key.isEmpty && value.isEmpty) continue;
      lines.add(key.isEmpty ? value : (value.isEmpty ? key : '$key: $value'));
    }
  } else if (fields is Map) {
    for (final entry in fields.entries) {
      lines.add('${entry.key}: ${entry.value}');
    }
  }
  return lines.isEmpty
      ? 'I found the "$label" memory.'
      : 'I remember "$label": ${lines.join('\n')}';
}
