enum GeneratedCredentialDraftStatus { pending, saving, saved, canceled }

class GeneratedCredentialDraftFinalizer {
  final Map<String, GeneratedCredentialDraftStatus> _statuses = {};
  final Map<String, Future<void>> _saves = {};

  GeneratedCredentialDraftStatus status(String key) =>
      _statuses[key] ?? GeneratedCredentialDraftStatus.pending;

  void remember(String key) {
    _statuses.putIfAbsent(key, () => GeneratedCredentialDraftStatus.pending);
  }

  Future<bool> save(String key, Future<void> Function() operation) async {
    final current = status(key);
    if (current == GeneratedCredentialDraftStatus.saved ||
        current == GeneratedCredentialDraftStatus.canceled) {
      return false;
    }
    if (current == GeneratedCredentialDraftStatus.saving) {
      await _saves[key];
      return false;
    }

    _statuses[key] = GeneratedCredentialDraftStatus.saving;
    final save = operation();
    _saves[key] = save;
    try {
      await save;
      _statuses[key] = GeneratedCredentialDraftStatus.saved;
      return true;
    } catch (_) {
      _statuses[key] = GeneratedCredentialDraftStatus.pending;
      rethrow;
    } finally {
      _saves.remove(key);
    }
  }

  Future<bool> cancel(String key, Future<void> Function() operation) async {
    if (status(key) == GeneratedCredentialDraftStatus.saving) {
      try {
        await _saves[key];
      } catch (_) {
        // A failed save returns the draft to pending and may still be canceled.
      }
    }
    final current = status(key);
    if (current == GeneratedCredentialDraftStatus.saved ||
        current == GeneratedCredentialDraftStatus.canceled) {
      return false;
    }

    // Reserve the terminal state before the asynchronous server operation so
    // a concurrent save cannot start while cancellation is in flight.
    _statuses[key] = GeneratedCredentialDraftStatus.canceled;
    try {
      await operation();
      return true;
    } catch (_) {
      _statuses[key] = GeneratedCredentialDraftStatus.pending;
      rethrow;
    }
  }
}
