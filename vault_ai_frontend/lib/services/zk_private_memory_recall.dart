/// PIN-free recall of client-decrypted V2 memories in a private chat session.
///
/// The supplied reader must use the authenticated ciphertext memory route.
/// A missing result cannot prove that an older, unready memory does not exist.
library;

import 'memory_title_identity.dart';
import 'vault_local_content_command.dart';

typedef ZkPrivateMemoryReader = Future<Map<String, dynamic>> Function();

final RegExp _explicitRecallCue = RegExp(
  r'\b(?:memor(?:y|ies)|remember|notes?|facts?)\b',
  caseSensitive: false,
);
final RegExp _privateOwnershipCue = RegExp(
  r'\b(?:my|mine|vault|saved|stored)\b',
  caseSensitive: false,
);

Future<String?> tryZkPrivateMemoryRecall({
  required String prompt,
  required ZkPrivateMemoryReader readMemories,
  required bool Function() accessIsCurrent,
}) async {
  final command = parseVaultLocalContentCommand(prompt);
  if (command == null ||
      command.kind != VaultLocalContentKind.memory ||
      command.action != VaultLocalContentAction.retrieve) {
    return null;
  }
  // Generic questions such as "What is two-factor authentication?" belong to
  // general chat. A personal or explicit memory cue is needed before any
  // private-memory request is made.
  if (!command.explicitKind &&
      !_explicitRecallCue.hasMatch(prompt) &&
      !_privateOwnershipCue.hasMatch(prompt)) {
    return null;
  }
  if (!accessIsCurrent()) {
    throw StateError('Vault access changed during private memory recall');
  }
  final result = await readMemories();
  if (!accessIsCurrent()) {
    throw StateError('Vault access changed during private memory recall');
  }
  if (result['engine'] != 'ciphertext' || result['items'] is! List) {
    throw const FormatException('Private memory inventory is unavailable');
  }
  final rows = <Map<String, dynamic>>[];
  final entries = <VaultLocalContentEntry>[];
  for (final raw in result['items'] as List) {
    if (raw is! Map) continue;
    final row = Map<String, dynamic>.from(raw);
    final id = '${row['id'] ?? ''}'.trim();
    final title = '${row['title'] ?? row['memory_key'] ?? ''}'.trim();
    if (id.isEmpty || title.isEmpty) continue;
    rows.add(row);
    entries.add(
      VaultLocalContentEntry(
        id: id,
        label: title,
        aliases: <String>[
          if (row['memory_key'] != null) '${row['memory_key']}',
          if (row['value'] != null) '${row['value']}',
          if (row['memory_value'] != null) '${row['memory_value']}',
          if (row['body'] != null) '${row['body']}',
        ],
      ),
    );
  }
  final match = resolveMemoryLocalContentMatch(
    query: command.query,
    entries: entries,
  );
  if (!accessIsCurrent()) {
    throw StateError('Vault access changed during private memory recall');
  }
  if (match != null) {
    final index = entries.indexOf(match.entry);
    if (index >= 0) return memoryLocalReply(rows[index]);
  }
  if (memoryQueryIsAmbiguous(query: command.query, entries: entries)) {
    return 'Several private memories match "${command.query}". '
        'Open Memory and select the exact one.';
  }
  final explicit = command.explicitKind || _explicitRecallCue.hasMatch(prompt);
  if (!explicit) return null;
  final unavailable = (result['unavailable_count'] as num?)?.toInt() ?? 0;
  return unavailable > 0
      ? 'I could not match that memory. Some private memories could not be opened; '
          'unlock again or refresh Memory and try again.'
      : 'I could not find a match in the private memories available here. '
          'Older memories may still need a private upgrade.';
}
