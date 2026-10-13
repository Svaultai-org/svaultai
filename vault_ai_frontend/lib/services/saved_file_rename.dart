// Saved-file title changes are metadata-only and always bind to a stable ID.
enum SavedFileRenameOutcome { saved, stale, cancelled, inFlight }

class SavedFileRenameCommand {
  final String target;
  final String name;
  const SavedFileRenameCommand({required this.target, required this.name});
}

String normalizeSavedFileName(String name) => name.trim();

String? savedFileNameValidationError(String name) {
  final normalized = normalizeSavedFileName(name);
  if (normalized.isEmpty) return 'Enter a file name.';
  if (normalized.length > 120) return 'Use 120 characters or fewer.';
  if (RegExp(r'[\x00-\x1f\x7f]').hasMatch(normalized)) {
    return 'Use a single-line file name without control characters.';
  }
  return null;
}

SavedFileRenameCommand? parseSavedFileRenameCommand(String text) {
  final match = RegExp(
    r'^\s*(?:please\s+)?rename\s+(?:(?:my|the)\s+)?'
    r'(?:(?:file|document|image|photo|video|audio)\s+)?'
    r'(?:"([^"]+)"|\x27([^\x27]+)\x27|(.+?))\s+to(?:\s+|$)([\s\S]*)$',
    caseSensitive: false,
  ).firstMatch(text.trim());
  if (match == null) return null;
  final target =
      (match.group(1) ?? match.group(2) ?? match.group(3) ?? '').trim();
  if (target.isEmpty ||
      RegExp(r'^(?:it|this|that|them|these|those)(?:\s+file)?$',
              caseSensitive: false)
          .hasMatch(target)) {
    return null;
  }
  // Leave unrelated credential/memory edit commands in their existing flows.
  if (RegExp(r'\b(?:login|password|credential|memory|memories|note)\b',
              caseSensitive: false)
          .hasMatch(target) &&
      !RegExp(r'^\s*(?:please\s+)?rename\s+(?:(?:my|the)\s+)?file\s+',
              caseSensitive: false)
          .hasMatch(text)) {
    return null;
  }
  var name = (match.group(4) ?? '').trim();
  if (name.length >= 2 &&
      ((name.startsWith('"') && name.endsWith('"')) ||
          (name.startsWith("'") && name.endsWith("'")))) {
    name = name.substring(1, name.length - 1);
  }
  return SavedFileRenameCommand(target: target, name: name);
}

class SavedFileRenameValidationException implements Exception {
  final String message;
  const SavedFileRenameValidationException(this.message);
}

/// A captured-session single-flight guard. It never owns file bytes or paths.
class SavedFileRenameController {
  final String fileId;
  final bool Function() accessIsCurrent;
  bool _busy = false;
  bool _cancelled = false;
  bool _committed = false;

  SavedFileRenameController({
    required this.fileId,
    required this.accessIsCurrent,
  });

  bool get busy => _busy;

  bool cancel() {
    if (_busy) return false;
    _cancelled = true;
    return true;
  }

  Future<SavedFileRenameOutcome> save({
    required String name,
    required Future<void> Function(String normalizedName) write,
    required void Function(String normalizedName) onCommitted,
  }) async {
    if (_cancelled) return SavedFileRenameOutcome.cancelled;
    if (_busy) return SavedFileRenameOutcome.inFlight;
    if (_committed) return SavedFileRenameOutcome.saved;
    if (fileId.isEmpty || !accessIsCurrent()) {
      return SavedFileRenameOutcome.stale;
    }
    final error = savedFileNameValidationError(name);
    if (error != null) throw SavedFileRenameValidationException(error);
    _busy = true;
    try {
      if (!accessIsCurrent()) return SavedFileRenameOutcome.stale;
      final normalized = normalizeSavedFileName(name);
      await write(normalized);
      if (!accessIsCurrent()) return SavedFileRenameOutcome.stale;
      onCommitted(normalized);
      _committed = true;
      return SavedFileRenameOutcome.saved;
    } finally {
      _busy = false;
    }
  }
}
