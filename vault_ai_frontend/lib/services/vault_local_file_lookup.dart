class VaultLocalFileLookupEntry {
  final String id;
  final String fileName;
  final String? savedName;
  final String? mimeType;
  final String? assetType;
  final String? relativePath;
  final int sizeBytes;

  const VaultLocalFileLookupEntry({
    required this.id,
    required this.fileName,
    required this.sizeBytes,
    this.savedName,
    this.mimeType,
    this.assetType,
    this.relativePath,
  });

  String get displayName {
    final saved = (savedName ?? '').trim();
    if (saved.isNotEmpty) return saved;
    final fallback = fileName.trim();
    return fallback.isEmpty ? 'file' : fallback;
  }
}

class VaultLocalFileLookupMatch {
  final VaultLocalFileLookupEntry entry;
  final int score;

  const VaultLocalFileLookupMatch({
    required this.entry,
    required this.score,
  });
}

const String localFileListAllQuery = '__vaultai_list_all_files__';

/// Filename metadata can prove a unique local hit, but it cannot prove that a
/// vault has no content-level match.  A metadata miss therefore falls through
/// to the shared semantic/OCR/vision retrieval path instead of producing a
/// terminal "not found" response on the client.
bool shouldDeferLocalFileMissToSemanticSearch({
  required String query,
  required VaultLocalFileLookupMatch? match,
}) =>
    query != localFileListAllQuery && match == null;

String? extractLocalFileLookupQuery(String message) {
  final text = message.trim();
  if (text.isEmpty) return null;
  final lower = text.toLowerCase();
  if (RegExp(
    r'^(?:what\s+(?:files|documents|docs)\s+do\s+i\s+have|show\s+(?:me\s+)?all\s+(?:my\s+)?(?:files|documents|docs))\s*[.!?]*$',
    caseSensitive: false,
  ).hasMatch(text)) {
    return localFileListAllQuery;
  }
  if (lower.startsWith('when ') ||
      lower.startsWith('who ') ||
      lower.startsWith('why ') ||
      lower.startsWith('how ')) {
    return null;
  }
  final aboutMatch = RegExp(
    r'^\s*(?:show(?:\s+me)?|open|view|find|get|download)\s+'
    r'(?:(?:me\s+)?(?:the|my)\s+)?'
    r'(?:file|document|doc|attachment|record)\s+about\s+(?:my\s+)?'
    r'(.+?)\s*[.!?]*\s*$',
    caseSensitive: false,
  ).firstMatch(text);
  if (aboutMatch != null) return aboutMatch.group(1)?.trim();
  final forMatch = RegExp(
    r'^\s*(?:show|find|get)(?:\s+me)?\s+for\s+(?:my\s+)?(.+?)\s*[.!?]*\s*$',
    caseSensitive: false,
  ).firstMatch(text);
  if (forMatch != null) return forMatch.group(1)?.trim();
  final match = RegExp(
    r'^\s*(?:show|open|view|find|get|download)(?:\s+me)?\s+'
    r'(?:(?:the|my)\s+)?'
    r'(?:(?:file|document|doc|image|photo|picture|video|audio)\s+)?'
    r'(.+?)\s*[.!?]*\s*$',
    caseSensitive: false,
  ).firstMatch(text);
  if (match == null) return null;
  final query = (match.group(1) ?? '')
      .replaceFirst(
        RegExp(
            r'\s+(?:file|files|document|documents|doc|docs|attachment|record)$',
            caseSensitive: false),
        '',
      )
      .trim();
  if (query.isEmpty) return null;
  final generic = normalizeLocalFileLookupText(query);
  if (generic.isEmpty ||
      generic == 'file' ||
      generic == 'document' ||
      generic == 'image' ||
      generic == 'photo' ||
      generic == 'video' ||
      generic == 'audio') {
    return null;
  }
  return query;
}

VaultLocalFileLookupMatch? resolveLocalVaultFileLookup({
  required String query,
  required Iterable<VaultLocalFileLookupEntry> files,
}) {
  final normalizedQuery = normalizeLocalFileLookupText(query);
  if (normalizedQuery.isEmpty) return null;

  final scored = <VaultLocalFileLookupMatch>[];
  for (final file in files) {
    final score = _scoreFile(query: normalizedQuery, file: file);
    if (score >= 70) {
      scored.add(VaultLocalFileLookupMatch(entry: file, score: score));
    }
  }
  if (scored.isEmpty) return null;
  scored.sort((a, b) {
    final byScore = b.score.compareTo(a.score);
    if (byScore != 0) return byScore;
    final byName = a.entry.displayName
        .toLowerCase()
        .compareTo(b.entry.displayName.toLowerCase());
    if (byName != 0) return byName;
    return a.entry.id.compareTo(b.entry.id);
  });
  // Equal exact filename matches are still authoritative filename evidence.
  // Pick one stably instead of misreporting a local miss and falling through
  // to semantic search (which is intentionally unavailable in private
  // filename-only vaults).
  return scored.first;
}

String normalizeLocalFileLookupText(String value) {
  final withoutQuotes = value
      .toLowerCase()
      .replaceAll(RegExp("[\"'`]+"), ' ')
      .replaceAll(RegExp(r'[_\-]+'), ' ');
  final cleaned = withoutQuotes.replaceAll(RegExp(r'[^a-z0-9]+'), ' ');
  return cleaned
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim()
      .replaceFirst(RegExp(r'^(?:the|my|about|for)\s+'), '')
      .replaceFirst(
        RegExp(
            r'\s+(?:file|files|document|documents|doc|docs|attachment|record)$'),
        '',
      )
      .replaceFirst(RegExp(r'\s+qa$'), '')
      .trim();
}

int _scoreFile({
  required String query,
  required VaultLocalFileLookupEntry file,
}) {
  var best = 0;
  for (final label in <String>[
    file.savedName ?? '',
    file.fileName,
    _basenameWithoutExtension(file.savedName ?? ''),
    _basenameWithoutExtension(file.fileName),
  ]) {
    final norm = normalizeLocalFileLookupText(label);
    if (norm.isEmpty) continue;
    if (norm == query) {
      best = best < 120 ? 120 : best;
      continue;
    }
    if (_singularize(norm) == _singularize(query)) {
      best = best < 116 ? 116 : best;
      continue;
    }
    if (norm.startsWith(query) || query.startsWith(norm)) {
      best = best < 95 ? 95 : best;
      continue;
    }
    if (norm.contains(query)) {
      best = best < 90 ? 90 : best;
      continue;
    }
    final qTerms = query.split(' ').where((t) => t.isNotEmpty).toList();
    if (qTerms.isNotEmpty && qTerms.every(norm.contains)) {
      best = best < 82 ? 82 : best;
      continue;
    }
    if (qTerms.length == 1 && _editDistanceAtMostOne(qTerms.first, norm)) {
      best = best < 72 ? 72 : best;
    }
  }
  return best;
}

String _basenameWithoutExtension(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return '';
  final slash = trimmed.lastIndexOf(RegExp(r'[\\/]'));
  final name = slash >= 0 ? trimmed.substring(slash + 1) : trimmed;
  final dot = name.lastIndexOf('.');
  if (dot <= 0) return name;
  return name.substring(0, dot);
}

String _singularize(String value) {
  return value
      .split(' ')
      .map((token) => token.length > 3 && token.endsWith('s')
          ? token.substring(0, token.length - 1)
          : token)
      .join(' ');
}

bool _editDistanceAtMostOne(String a, String b) {
  if (a == b) return true;
  if ((a.length - b.length).abs() > 1) return false;
  var i = 0;
  var j = 0;
  var edits = 0;
  while (i < a.length && j < b.length) {
    if (a.codeUnitAt(i) == b.codeUnitAt(j)) {
      i++;
      j++;
      continue;
    }
    edits++;
    if (edits > 1) return false;
    if (a.length > b.length) {
      i++;
    } else if (b.length > a.length) {
      j++;
    } else {
      i++;
      j++;
    }
  }
  if (i < a.length || j < b.length) edits++;
  return edits <= 1;
}
