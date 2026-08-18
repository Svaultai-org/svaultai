const Map<String, String> _commandAliases = <String, String>{
  'analyse': 'analyze',
  'analysed': 'analyzed',
  'analysing': 'analyzing',
  'anlyze': 'analyze',
  'ths': 'this',
  'teh': 'the',
  'yhe': 'the',
  'credntial': 'credential',
  'credntials': 'credentials',
  'pasword': 'password',
  'paswords': 'passwords',
  'docment': 'document',
};

const Set<String> _commandLexicon = <String>{
  'analyze',
  'analyzed',
  'analyzing',
  'inspect',
  'review',
  'read',
  'scan',
  'extract',
  'identify',
  'classify',
  'explain',
  'compare',
  'summarize',
  'transcribe',
  'describe',
  'understand',
  'find',
  'get',
  'show',
  'save',
  'what',
  'which',
  'who',
  'where',
  'when',
  'why',
  'how',
  'this',
  'that',
  'the',
  'file',
  'document',
  'attachment',
  'attached',
  'pdf',
  'image',
  'photo',
  'credential',
  'credentials',
  'password',
  'passwords',
  'login',
  'logins',
  'username',
  'usernames',
  'account',
  'accounts',
  'pin',
  'pins',
  'secret',
  'secrets',
  'secure',
  'record',
  'records',
  'code',
  'codes',
  'identifier',
  'identifiers',
};

bool _oneEditApart(String left, String right) {
  if (left == right) return true;
  if ((left.length - right.length).abs() > 1) return false;
  if (left.length == right.length) {
    final differences = <int>[];
    for (var index = 0; index < left.length; index += 1) {
      if (left[index] != right[index]) differences.add(index);
    }
    if (differences.length == 1) return true;
    return differences.length == 2 &&
        differences[1] == differences[0] + 1 &&
        left[differences[0]] == right[differences[1]] &&
        left[differences[1]] == right[differences[0]];
  }

  final shorter = left.length < right.length ? left : right;
  final longer = left.length < right.length ? right : left;
  var shortIndex = 0;
  var longIndex = 0;
  var skipped = false;
  while (shortIndex < shorter.length && longIndex < longer.length) {
    if (shorter[shortIndex] == longer[longIndex]) {
      shortIndex += 1;
      longIndex += 1;
      continue;
    }
    if (skipped) return false;
    skipped = true;
    longIndex += 1;
  }
  return true;
}

String _normalizeCommandToken(String token) {
  final lowered = token.toLowerCase();
  final alias = _commandAliases[lowered];
  if (alias != null) return alias;
  if (_commandLexicon.contains(lowered) || lowered.length < 4) return lowered;
  final candidates = _commandLexicon
      .where((known) =>
          (known.length - lowered.length).abs() <= 1 &&
          _oneEditApart(lowered, known))
      .toList(growable: false);
  return candidates.length == 1 ? candidates.single : lowered;
}

/// Returns a disposable, command-only matching view.
///
/// This value must never be used as credential data or persisted. Usernames,
/// passwords, PINs, URLs, identifiers, and extracted document values stay
/// byte-for-byte unchanged.
String normalizeAttachmentCommandLanguage(String? text) {
  return (text ?? '')
      .replaceAllMapped(
        RegExp(r'[A-Za-z]+'),
        (match) => _normalizeCommandToken(match.group(0)!),
      )
      .toLowerCase();
}

/// Returns true only when the text accompanying a current attachment asks to
/// inspect credential material already present in that attachment.
///
/// File-v2 ciphertext is intentionally unreadable to the backend. An explicit
/// document-review request therefore authorizes this one attachment to use the
/// existing server-analyzable encrypted upload path. Ordinary uploads and
/// explicit credential-generation requests remain on file-v2.
bool shouldUseServerReadableCredentialReview(String? accompanyingText) {
  final original = (accompanyingText ?? '')
      .toLowerCase()
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (original.isEmpty) return false;

  // Do not reinterpret credential values that happen to resemble misspelled
  // command words. Only the disposable routing view below is normalized.
  final suppliedCredentialAssertion = RegExp(
    r'\b(?:username|user)\s+(?:is\s+)?\S+.*'
    r'\b(?:password|pass|pwd)\s+(?:is\s+)?\S+',
  );
  if (suppliedCredentialAssertion.hasMatch(original)) return false;

  final normalized = normalizeAttachmentCommandLanguage(original)
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (normalized.isEmpty) return false;

  final hasStrongReviewVerb = RegExp(
    r'\b(?:analyz(?:e|ed|ing)|inspect|read|review|extract|scan|identify|'
    r'classify|explain|compare|summarize|transcribe|describe|understand)\b',
  ).hasMatch(normalized);
  final hasDocumentScope = RegExp(
    r'\b(?:this|that|file|document|docx?|pdf|attachment|attached|image|photo)\b',
  ).hasMatch(normalized);
  final hasWeakReviewVerb =
      RegExp(r'\b(?:find|get|show)\b').hasMatch(normalized);
  final isQuestion = RegExp(
    r'^\s*(?:what|which|who|where|when|why|how|is|are|does|do|can)\b',
  ).hasMatch(normalized);
  final hasCredentialNoun = RegExp(
    r'\b(?:log\s?ins?|credentials?|passwords?|usernames?|accounts?|pins?|'
    r'secrets?|secure\s+records?|access\s+codes?|identifiers?)\b',
  ).hasMatch(normalized);
  return hasCredentialNoun &&
      (hasStrongReviewVerb ||
          (hasDocumentScope && hasWeakReviewVerb) ||
          (hasDocumentScope && isQuestion));
}
