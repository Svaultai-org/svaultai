String? attachmentTitleFromComposerText(
  String text, {
  required int attachmentCount,
}) {
  if (attachmentCount != 1) return null;

  var candidate = text.trim();
  if (candidate.isEmpty ||
      candidate.length > 120 ||
      candidate.contains('?') ||
      candidate.contains('\n')) {
    return null;
  }

  candidate = candidate.replaceAll(RegExp(r'\s+'), ' ');
  candidate = _stripMatchingQuotes(candidate);

  final explicit = _stripExplicitNamingCommand(candidate);
  if (explicit != null) {
    final normalized = _normalizeTitle(explicit);
    return normalized.isEmpty ? null : normalized;
  }

  if (_looksLikeQuestionOrInstruction(candidate)) return null;
  if (!_looksLikeSimpleTitle(candidate)) return null;

  final normalized = _normalizeTitle(candidate);
  return normalized.isEmpty ? null : normalized;
}

/// Preserves the user's exact visible title while retaining a safe original
/// extension for downloads/playback. The exact title is stored separately as
/// FileV2 metadata `label`; this filename is the transport/download name.
String filenameWithChosenTitle({
  required String originalFilename,
  String? chosenTitle,
}) {
  final title = chosenTitle?.trim();
  if (title == null || title.isEmpty) return originalFilename;
  final originalBase = originalFilename.split(RegExp(r'[\\/]')).last;
  final dot = originalBase.lastIndexOf('.');
  final extension = dot > 0 && dot < originalBase.length - 1
      ? originalBase.substring(dot)
      : '';
  if (extension.isNotEmpty &&
      title.toLowerCase().endsWith(extension.toLowerCase())) {
    return title;
  }
  return '$title$extension';
}

String? _stripExplicitNamingCommand(String text) {
  final patterns = <RegExp>[
    RegExp(
        r'^(?:save|saved|upload|store)\s+(?:it|this|this file|this image|this photo|this document|the file|the image|the photo|the document)\s+as\s+(.+)$',
        caseSensitive: false),
    RegExp(
        r'^(?:name|rename|call|label)\s+(?:it|this|this file|this image|this photo|this document|the file|the image|the photo|the document)\s+as\s+(.+)$',
        caseSensitive: false),
    RegExp(
        r'^(?:name|rename|call|label)\s+(?:it|this|this file|this image|this photo|this document|the file|the image|the photo|the document)\s+(.+)$',
        caseSensitive: false),
  ];

  for (final pattern in patterns) {
    final match = pattern.firstMatch(text);
    if (match != null) return match.group(1);
  }
  return null;
}

bool _looksLikeQuestionOrInstruction(String text) {
  final lower = text.toLowerCase();
  const prefixes = <String>[
    'what ',
    "what's ",
    'who ',
    'when ',
    'where ',
    'why ',
    'how ',
    'is ',
    'are ',
    'can ',
    'could ',
    'would ',
    'please ',
    'tell ',
    'show ',
    'open ',
    'download ',
    'summarize ',
    'summarise ',
    'analyze ',
    'analyse ',
    'read ',
    'extract ',
    'find ',
    'search ',
    'look ',
    'ask ',
    'answer ',
    'create ',
    'make ',
    'generate ',
    'send ',
  ];

  if (prefixes.any(lower.startsWith)) return true;
  return lower.contains(' please ') ||
      lower.contains(' tell me ') ||
      lower.contains(' summarize ') ||
      lower.contains(' analyse ') ||
      lower.contains(' analyze ');
}

bool _looksLikeSimpleTitle(String text) {
  final words = text.split(' ').where((w) => w.trim().isNotEmpty).toList();
  if (words.length > 8) return false;
  if (!RegExp(r'[A-Za-z0-9]').hasMatch(text)) return false;
  if (RegExp(r'[{}<>|\\]').hasMatch(text)) return false;
  if (text.endsWith('!') || text.endsWith(';')) return false;
  return true;
}

String _normalizeTitle(String text) {
  var out = text.trim().replaceAll(RegExp(r'\s+'), ' ');
  out = _stripMatchingQuotes(out);
  while (out.endsWith('.') && out.length > 1) {
    out = out.substring(0, out.length - 1).trimRight();
  }
  return out;
}

String _stripMatchingQuotes(String text) {
  if (text.length < 2) return text;
  final first = text[0];
  final last = text[text.length - 1];
  if ((first == '"' && last == '"') || (first == "'" && last == "'")) {
    return text.substring(1, text.length - 1).trim();
  }
  return text;
}
