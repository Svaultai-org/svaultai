enum CredentialInventoryViewState {
  loading,
  readyEmpty,
  readyWithItems,
  error,
}

/// Owns only the lifecycle identity of a credential inventory. A dashboard
/// may remain mounted while AppState signs out or switches vaults; in that
/// case the old list and its single-flight must be discarded before any new
/// session can render or query them.
class CredentialInventorySessionBinding {
  int? _epoch;

  int? get epoch => _epoch;

  bool bind(int sessionEpoch) {
    if (_epoch == sessionEpoch) return false;
    _epoch = sessionEpoch;
    return true;
  }
}

CredentialInventoryViewState resolveCredentialInventoryViewState({
  required bool loading,
  required bool authoritativeLoadCompleted,
  required int itemCount,
  required bool hasError,
}) {
  if (loading || (!authoritativeLoadCompleted && !hasError)) {
    return CredentialInventoryViewState.loading;
  }
  if (hasError) return CredentialInventoryViewState.error;
  return itemCount == 0
      ? CredentialInventoryViewState.readyEmpty
      : CredentialInventoryViewState.readyWithItems;
}
