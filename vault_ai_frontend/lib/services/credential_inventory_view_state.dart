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

/// Returns true only when every inventory source required for the active
/// vault architecture completed successfully.
///
/// A ZK vault can contain legacy-compatible rows or opaque ciphertext rows
/// during the rolling migration, so either successful source is sufficient
/// alongside V2. Requiring both caused valid records from the successful
/// source to be discarded whenever the other endpoint was not yet deployed.
/// A pre-ZK vault has no opaque inventory, so its legacy endpoint remains
/// required.
bool credentialInventorySourcesComplete({
  required bool isZkVault,
  required bool legacyCompleted,
  required bool opaqueCompleted,
  required bool v2Completed,
}) {
  return v2Completed &&
      (isZkVault ? (opaqueCompleted || legacyCompleted) : legacyCompleted);
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
