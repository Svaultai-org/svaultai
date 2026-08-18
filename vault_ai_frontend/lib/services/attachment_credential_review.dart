/// Returns true only when the text accompanying a current attachment asks to
/// inspect credential material already present in that attachment.
///
/// File-v2 ciphertext is intentionally unreadable to the backend. An explicit
/// document-review request therefore authorizes this one attachment to use the
/// existing server-analyzable encrypted upload path. Ordinary uploads and
/// explicit credential-generation requests remain on file-v2.
bool shouldUseServerReadableCredentialReview(String? accompanyingText) {
  final normalized = (accompanyingText ?? '')
      .toLowerCase()
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (normalized.isEmpty) return false;

  final hasStrongReviewVerb = RegExp(
    r'\b(?:analy[sz]e|read|review|extract|scan|check|pull)\b',
  ).hasMatch(normalized);
  final hasDocumentScope = RegExp(
    r'\b(?:file|document|docx?|pdf|attachment|attached|image|photo)\b',
  ).hasMatch(normalized);
  final hasWeakReviewVerb = RegExp(r'\b(?:find|show)\b').hasMatch(normalized);
  final hasCredentialNoun = RegExp(
    r'\b(?:log\s?ins?|credentials?|passwords?|usernames?|accounts?)\b',
  ).hasMatch(normalized);
  return hasCredentialNoun &&
      (hasStrongReviewVerb || (hasDocumentScope && hasWeakReviewVerb));
}
