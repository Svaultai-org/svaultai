enum VaultLocalContentKind { memory, login, file }

enum VaultLocalContentAction { retrieve, delete }

class VaultLocalMemorySaveCommand {
  final String title;
  final String value;
  final String memoryType;
  final String relationship;
  final String? attribute;
  final String? validationError;

  const VaultLocalMemorySaveCommand({
    required this.title,
    required this.value,
    required this.memoryType,
    required this.relationship,
    this.attribute,
    this.validationError,
  });

  Map<String, dynamic> toMemoryData() => <String, dynamic>{
        'title': title,
        'memory_key': title,
        'value': value,
        'body': value,
        'memory_type': memoryType,
        'category': memoryType,
        'subject': relationship == 'self' ? 'self' : relationship,
        'subject_display': relationship == 'self' ? 'your' : relationship,
        'relationship': relationship,
        'attribute': attribute ?? title,
      };
}

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
  r"tell\s+me|remind\s+me|do\s+you\s+remember|"
  r"what(?:\s+(?:date|day|time))?(?:\s+is|'s)|"
  r"when(?:\s+is|'s)|where(?:\s+is|'s)|who(?:\s+is|'s))\b",
  caseSensitive: false,
);

final RegExp _memoryCardRecallOpening = RegExp(
  r'^\s*(?:please\s+)?what\s+do\s+you\s+remember\s+about\s+',
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

final RegExp _contextualDeleteTarget = RegExp(
  r'^(?:(?:it|this|that|them|these|those)(?:\s+(?:one|ones|item|items|'
  r'entry|entries|record|records))?|(?:selected|current|previous|last)\s+'
  r'(?:item|entry|record)|delete|remove|erase|forget)(?:\s+please)?$',
);

final RegExp _explicitPersonalMemorySave = RegExp(
  r'^\s*(?:please\s+)?(?:remember|save)\s+(?:that\s+)?my\s+'
  r'(?<title>[^.!?]{1,80}?)\s+(?:is|as|to\s+be)\s+'
  r'(?<value>[^\r\n]{1,2000}?)\s*[.!?]*\s*$',
  caseSensitive: false,
);

final RegExp _namedMemorySave = RegExp(
  r'^\s*(?:please\s+)?(?:save|create|remember)\s+'
  r'(?:a\s+)?(?:new\s+)?memory\s+'
  r'(?:with\s+title\s*:?\s*|(?:titled|named|called)\s+)'
  r'(?<title>.*?)\s+(?:and|with)\s+(?:content|text|body)\s*:\s*'
  r'(?<value>[\s\S]*?)\s*$',
  caseSensitive: false,
  dotAll: true,
);

final RegExp _namedMemoryPrefix = RegExp(
  r'^\s*(?:please\s+)?(?:save|create|remember)\s+'
  r'(?:a\s+)?(?:new\s+)?memory\s+'
  r'(?:with\s+title\b|(?:titled|named|called)\b)',
  caseSensitive: false,
);

final RegExp _relationshipNameMemorySaveWithoutConnector = RegExp(
  r'^\s*(?:please\s+)?(?:remember|save)\s+(?:that\s+)?my\s+'
  r'(?<relationship>friend|wife|husband|spouse|partner|mother|mom|father|dad|'
  r'sister|brother|daughter|son|child|grandmother|grandma|grandfather|grandpa|'
  r'aunt|uncle|cousin)\s+'
  r'(?<attribute>(?:full\s+|first\s+|given\s+)?name)\s+'
  r'(?<value>[^\r\n]{1,2000}?)\s*[.!?]*\s*$',
  caseSensitive: false,
);

final RegExp _sensitiveVaultNoun = RegExp(
  r'\b(?:login|credential|password|passcode|pin|username|email|token|'
  r'secret|private\s+key|seed|recovery|backup\s+code|api\s+key|imei|'
  r'serial|wallet|account|address)\b',
  caseSensitive: false,
);

final RegExp _familyRelationship = RegExp(
  r'^(?:wife|husband|spouse|partner|mother|mom|father|dad|parent|'
  r'sister|brother|daughter|son|child|grandmother|grandma|grandfather|'
  r'grandpa|aunt|uncle|cousin)\b',
  caseSensitive: false,
);

const _maidenSubject =
    r'mother|mom|mum|mama|father|dad|papa|wife|husband|spouse|partner|'
    r'friend|sister|brother|daughter|son';
final RegExp _maidenMemorySave = RegExp(
  r'^\s*(?:please\s+)?(?:save|remember)\s+(?:that\s+)?my\s+'
  '(?<subject>$_maidenSubject)(?:[\'’]s)?\\s+maiden\\s+name\\s*'
  r'(?:(?:is|as|to\s+be)\b|[=:])?\s*(?<value>[^\r\n]*?)\s*[.!?]*\s*$',
  caseSensitive: false,
);
final RegExp _maidenMemoryRecall = RegExp(
  r"^\s*(?:please\s+)?what(?:['’]?s|\s+is)\s+(?:my\s+)?"
  '(?<subject>$_maidenSubject)(?:[\'’]s)?\\s+maiden\\s+name\\s*[.!?]*\\s*\$',
  caseSensitive: false,
);
final RegExp _maidenCredentialValue = RegExp(
  r'^\s*(?:(?:a|the)\s+)?(?:login|credential|account|password)\b|'
  r'\b(?:username|password|email|pin|passcode)\s*(?:=|:|is\b)',
  caseSensitive: false,
);

String _maidenSubjectRelationship(String subject) => switch (subject) {
      'mom' || 'mum' || 'mama' => 'mother',
      'dad' || 'papa' => 'father',
      _ => subject,
    };

String _maidenMemoryTitle(String subject) =>
    "${subject[0].toUpperCase()}${subject.substring(1)}'s maiden name";

VaultLocalMemorySaveCommand? parseVaultLocalMemorySaveCommand(
  String message,
) {
  // The explicit record kind takes precedence over words in the title or
  // content. Keep both fields verbatim; do not turn a named memory into a
  // generated login or silently replace an existing record.
  final named = _namedMemorySave.firstMatch(message);
  if (_namedMemoryPrefix.hasMatch(message)) {
    final title = (named?.namedGroup('title') ?? '').trim();
    final value = (named?.namedGroup('value') ?? '').trim();
    String? validationError;
    if (title.isEmpty || value.isEmpty) {
      validationError =
          'Add a memory title and content first. Nothing was saved.';
    } else if (title.runes.length > 120) {
      validationError =
          'Use a memory title of 120 characters or fewer. Nothing was saved.';
    } else if (value.runes.length > 500 || message.trim().runes.length > 2000) {
      validationError =
          'This chat format supports up to 500 characters of memory content. Use the Memory page for longer notes. Nothing was saved.';
    }
    return VaultLocalMemorySaveCommand(
      title: title,
      value: value,
      memoryType: 'note',
      relationship: 'self',
      validationError: validationError,
    );
  }
  // This explicit personal fact owns incomplete and connector-free forms.
  // Do not let an omitted surname become a generated login or an empty save.
  final maiden = _maidenMemorySave.firstMatch(message);
  if (maiden != null) {
    final subject = maiden.namedGroup('subject')!.toLowerCase();
    final value = maiden.namedGroup('value')!.trim();
    if (_maidenCredentialValue.hasMatch(value)) return null;
    final title = _maidenMemoryTitle(subject);
    return VaultLocalMemorySaveCommand(
      title: title,
      value: value,
      memoryType: subject == 'friend' ? 'relationship' : 'family',
      relationship: _maidenSubjectRelationship(subject),
      attribute: 'maiden_name',
      validationError: value.isEmpty
          ? 'What should I save as ${title[0].toLowerCase()}${title.substring(1)}? Nothing was saved.'
          : value.runes.length > 500
              ? 'This chat format supports up to 500 characters of memory content. Use the Memory page for longer notes. Nothing was saved.'
              : null,
    );
  }
  final explicit = _explicitPersonalMemorySave.firstMatch(message);
  final relationshipName = explicit == null
      ? _relationshipNameMemorySaveWithoutConnector.firstMatch(message)
      : null;
  if (explicit == null && relationshipName == null) return null;
  final rawTitle = explicit != null
      ? (explicit.namedGroup('title') ?? '').trim()
      : '${relationshipName?.namedGroup('relationship') ?? ''} '
              '${relationshipName?.namedGroup('attribute') ?? ''}'
          .trim();
  final value = (explicit?.namedGroup('value') ??
          relationshipName?.namedGroup('value') ??
          '')
      .trim();
  if (rawTitle.isEmpty || value.isEmpty) return null;

  // Credentials, recovery data, and device identifiers use their dedicated
  // encrypted record flows. Never silently downgrade them into a memory.
  if (_sensitiveVaultNoun.hasMatch(rawTitle)) return null;

  final title = rawTitle[0].toUpperCase() + rawTitle.substring(1);
  final family = _familyRelationship.firstMatch(rawTitle);
  final explicitRelationship =
      relationshipName?.namedGroup('relationship')?.toLowerCase();
  final relationship =
      explicitRelationship ?? family?.group(0)?.toLowerCase() ?? 'self';
  return VaultLocalMemorySaveCommand(
    title: title,
    value: value,
    memoryType: relationship == 'friend'
        ? 'relationship'
        : (family == null ? 'note' : 'family'),
    relationship: relationship,
  );
}

VaultLocalContentCommand? parseVaultLocalContentCommand(String message) {
  final text = message.trim();
  if (text.isEmpty) return null;
  // The Memory dashboard asks about a literal title. Preserve that title
  // before generic noun/verb inference: a name containing "login", "file"
  // or "delete" must still retrieve the selected encrypted memory.
  final memoryCardRecall = _memoryCardRecallOpening.firstMatch(text);
  if (memoryCardRecall != null) {
    var query = text.substring(memoryCardRecall.end).trim();
    if (query.endsWith('?')) {
      query = query.substring(0, query.length - 1).trim();
    }
    if (query.isEmpty) return null;
    return VaultLocalContentCommand(
      kind: VaultLocalContentKind.memory,
      action: VaultLocalContentAction.retrieve,
      query: query,
      explicitKind: false,
    );
  }
  final maidenRecall = _maidenMemoryRecall.firstMatch(text);
  if (maidenRecall != null) {
    return VaultLocalContentCommand(
      kind: VaultLocalContentKind.memory,
      action: VaultLocalContentAction.retrieve,
      query:
          _maidenMemoryTitle(maidenRecall.namedGroup('subject')!.toLowerCase()),
      explicitKind: true,
    );
  }
  // Confirmation/cancellation replies need an already selected target. Never
  // reinterpret "Yes, delete it." or "don't delete it" as a memory title.
  if (isVaultLocalDeleteConfirmation(text) ||
      isVaultLocalDeleteCancellation(text)) {
    return null;
  }
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
  if (deleting && !hasMemory) {
    final query =
        normalizeVaultLocalContentText(_extractQuery(text, _memoryNoun));
    // A pronoun refers to chat selection context, not necessarily a memory.
    // Let the selected-item handler resolve it; never guess a content kind.
    if (query.isEmpty || _contextualDeleteTarget.hasMatch(query)) return null;
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
    r'^\s*(?:(?:yes|yep|yup|yeah)(?:(?:\s*,\s*|\s+)(?:please\s+)?delete(?:\s+(?:it|that))?)?|confirm(?:\s+delete)?|delete(?:\s+(?:it|that|now))?|go\s+ahead(?:\s+and\s+delete\s+it)?|proceed|do\s+it)\s*[.!?]*\s*$',
    caseSensitive: false,
  ).hasMatch(message);
}

bool isVaultLocalDeleteCancellation(String message) {
  return RegExp(
    r"^\s*(?:no|nope|cancel(?:\s+(?:it|that|delete))?|stop|keep\s+it|never\s*mind|don['’]?t\s+delete(?:\s+(?:it|that))?|no(?:\s*,\s*|\s+)keep\s+it)\s*[.!?]*\s*$",
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

/// Resolves a query to the position of a label in a listing response.
///
/// Some legacy secure-item list responses intentionally contain only a
/// service name and type, with no database id. Using a missing `id` as the
/// lookup key makes every legacy row look identical ("null"), so a match for
/// a later row can accidentally reopen the first row in the list. A local
/// index is stable for the lifetime of this response and keeps the selected
/// row exact without exposing or requiring a server id.
int? resolveVaultLocalContentLabelIndex({
  required String query,
  required List<String> labels,
}) {
  final normalizedQuery = normalizeVaultLocalContentText(query);
  final queryTerms = _meaningfulTerms(normalizedQuery);
  if (queryTerms.isEmpty) return null;
  final compactQuery = normalizedQuery.replaceAll(' ', '');
  final exactMatches = <int>[];
  final partialMatches = <int>[];
  for (var index = 0; index < labels.length; index++) {
    final normalizedLabel = normalizeVaultLocalContentText(labels[index]);
    // Whole-label spacing variants such as NordVPN/Nord VPN are equivalent.
    // Keep all equivalent rows so even normalized duplicates stay ambiguous.
    if (normalizedLabel.replaceAll(' ', '') == compactQuery) {
      exactMatches.add(index);
    } else if (_meaningfulTerms(normalizedLabel).containsAll(queryTerms)) {
      partialMatches.add(index);
    }
  }
  if (exactMatches.isNotEmpty) {
    return exactMatches.length == 1 ? exactMatches.single : null;
  }
  // A shorter query may name one longer title, but a missing qualifier in a
  // more-specific query must never fall back to a shorter or substring title.
  return partialMatches.length == 1 ? partialMatches.single : null;
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
      r"do\s+you\s+remember|what(?:\s+(?:date|day|time))?(?:\s+is|'s)|"
      r"when(?:\s+is|'s)|"
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
