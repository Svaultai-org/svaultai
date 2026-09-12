enum VaultLocalContentKind { memory, login, file }

enum VaultLocalContentAction { retrieve, delete }

class VaultLocalContentCommand {
  final VaultLocalContentKind kind;
  final VaultLocalContentAction action;
  final String query;
  final bool explicitKind;

  const VaultLocalContentCommand({
    required this.kind,
    required this.action,
    required this.query,
    required this.explicitKind,
  });
}

class VaultLocalContentEntry {
  final String id;
  final String label;
  final List<String> aliases;

  const VaultLocalContentEntry({
    required this.id,
    required this.label,
    this.aliases = const <String>[],
  });
}

class VaultLocalContentMatch {
  final VaultLocalContentEntry entry;
  final int score;

  const VaultLocalContentMatch({required this.entry, required this.score});
}

final RegExp _deleteVerb = RegExp(
  r'\b(?:delete|remove|erase|forget)\b',
  caseSensitive: false,
);

final RegExp _retrieveOpening = RegExp(
  r"^\s*(?:please\s+)?(?:show(?:\s+me)?|find|view|open|retrieve|get|"
  r"tell\s+me|remind\s+me|do\s+you\s+remember|what(?:\s+is|'s)|"
  r"when(?:\s+is|'s)|where(?:\s+is|'s)|who(?:\s+is|'s))\b",
  caseSensitive: false,
);

final RegExp _loginNoun = RegExp(
  r'\b(?:logins?|credentials?|passwords?|accounts?|sign[\s-]?ins?)\b',
  caseSensitive: false,
);

final RegExp _memoryNoun = RegExp(
  r'\b(?:memories|memory|notes?|facts?)\b',
  caseSensitive: false,
);

final RegExp _fileNoun = RegExp(
  r'\b(?:files?|documents?|docs?|images?|photos?|pictures?|videos?|audio)\b',
  caseSensitive: false,
);

VaultLocalContentCommand? parseVaultLocalContentCommand(String message) {
  final text = message.trim();
  if (text.isEmpty) return null;
  final deleting = _deleteVerb.hasMatch(text);
  final retrieving = _retrieveOpening.hasMatch(text);
  if (!deleting && !retrieving) return null;

  final hasLogin = _loginNoun.hasMatch(text);
  final hasMemory = _memoryNoun.hasMatch(text);
  final hasFile = _fileNoun.hasMatch(text);
  final action = deleting
      ? VaultLocalContentAction.delete
      : VaultLocalContentAction.retrieve;

  if (hasLogin) {
    return VaultLocalContentCommand(
      kind: VaultLocalContentKind.login,
      action: action,
      query: _extractQuery(text, _loginNoun),
      explicitKind: true,
    );
  }
  if (hasFile) {
    return VaultLocalContentCommand(
      kind: VaultLocalContentKind.file,
      action: action,
      query: _extractQuery(text, _fileNoun),
      explicitKind: true,
    );
  }
  if (hasMemory || deleting) {
    return VaultLocalContentCommand(
      kind: VaultLocalContentKind.memory,
      action: action,
      query: _extractQuery(text, _memoryNoun),
      explicitKind: hasMemory,
    );
  }

  // A natural question such as "What is the Project Atlas launch date?"
  // may refer to an encrypted memory. The caller only handles this implicit
  // command when a strong local title match exists; otherwise normal chat
  // continues unchanged.
  return VaultLocalContentCommand(
    kind: VaultLocalContentKind.memory,
    action: action,
    query: _extractQuery(text, _memoryNoun),
    explicitKind: false,
  );
}

bool isVaultLocalDeleteConfirmation(String message) {
  return RegExp(
    r'^\s*(?:yes|confirm|delete|do\s+it|yes,?\s+delete(?:\s+it)?)\s*[.!]?\s*$',
    caseSensitive: false,
  ).hasMatch(message);
}

bool isVaultLocalDeleteCancellation(String message) {
  return RegExp(
    r'^\s*(?:no|cancel|stop|keep\s+it|never\s+mind)\s*[.!]?\s*$',
    caseSensitive: false,
  ).hasMatch(message);
}

VaultLocalContentMatch? resolveVaultLocalContentMatch({
  required String query,
  required Iterable<VaultLocalContentEntry> entries,
}) {
  final normalizedQuery = normalizeVaultLocalContentText(query);
  if (normalizedQuery.isEmpty) return null;
  final queryTerms = _meaningfulTerms(normalizedQuery);
  if (queryTerms.isEmpty) return null;

  final matches = <VaultLocalContentMatch>[];
  for (final entry in entries) {
    var best = 0;
    for (final candidate in <String>[entry.label, ...entry.aliases]) {
      final normalizedCandidate = normalizeVaultLocalContentText(candidate);
      if (normalizedCandidate.isEmpty) continue;
      final candidateTerms = _meaningfulTerms(normalizedCandidate);
      if (normalizedCandidate == normalizedQuery) {
        best = 120;
      } else if (candidateTerms.isNotEmpty &&
          queryTerms.containsAll(candidateTerms)) {
        best = best < 110 ? 110 : best;
      } else if (queryTerms.every(candidateTerms.contains)) {
        best = best < 100 ? 100 : best;
      } else if (normalizedCandidate.contains(normalizedQuery) ||
          normalizedQuery.contains(normalizedCandidate)) {
        best = best < 92 ? 92 : best;
      }
    }
    if (best >= 92) {
      matches.add(VaultLocalContentMatch(entry: entry, score: best));
    }
  }
  if (matches.isEmpty) return null;
  matches.sort((a, b) {
    final byScore = b.score.compareTo(a.score);
    if (byScore != 0) return byScore;
    return a.entry.label.toLowerCase().compareTo(b.entry.label.toLowerCase());
  });
  if (matches.length > 1 && matches[0].score == matches[1].score) {
    return null;
  }
  return matches.first;
}

String normalizeVaultLocalContentText(String value) {
  return value
      .toLowerCase()
      .replaceAll(RegExp("[\"'`]+"), ' ')
      .replaceAll(RegExp(r'[_\-]+'), ' ')
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
}

String _extractQuery(String text, RegExp noun) {
  var value = text.trim();
  value = value.replaceFirst(
    RegExp(
      r"^\s*(?:please\s+)?(?:delete|remove|erase|forget|show(?:\s+me)?|"
      r"find|view|open|retrieve|get|tell\s+me|remind\s+me|"
      r"do\s+you\s+remember|what(?:\s+is|'s)|when(?:\s+is|'s)|"
      r"where(?:\s+is|'s)|who(?:\s+is|'s))\s+",
      caseSensitive: false,
    ),
    '',
  );
  value = value.replaceFirst(
    RegExp(
      r'^\s*(?:(?:the|my|a|an|saved|stored)\s+)*(?:login|credential|password|'
      r'account|sign[\s-]?in|memory|note|fact|file|document|doc|image|photo|'
      r'picture|video|audio)s?\s+(?:for|named|called)?\s*',
      caseSensitive: false,
    ),
    '',
  );
  value = value.replaceAll(noun, ' ');
  value = value
      .replaceFirst(
        RegExp(r'^\s*(?:for\s+)?(?:(?:the|my|a|an|saved|stored)\s+)+',
            caseSensitive: false),
        '',
      )
      .replaceAll(
          RegExp(r'\b(?:from\s+my\s+vault|from\s+the\s+vault)\b',
              caseSensitive: false),
          ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  return value.replaceAll(RegExp(r'[.!?]+$'), '').trim();
}

Set<String> _meaningfulTerms(String normalized) {
  const ignored = <String>{
    'a',
    'an',
    'the',
    'my',
    'me',
    'please',
    'saved',
    'stored',
    'from',
    'vault',
    'about',
    'for',
    'is',
    'was',
    'are',
    'do',
    'you',
  };
  return normalized
      .split(' ')
      .where((term) => term.isNotEmpty && !ignored.contains(term))
      .toSet();
}
