enum FileInventoryViewState {
  loading,
  readyEmpty,
  readyWithFiles,
  error,
}

FileInventoryViewState resolveFileInventoryViewState({
  required bool loading,
  required bool authoritativeLoadCompleted,
  required int fileCount,
  required bool hasError,
}) {
  if (loading || (!authoritativeLoadCompleted && !hasError)) {
    return FileInventoryViewState.loading;
  }
  if (hasError) return FileInventoryViewState.error;
  return fileCount == 0
      ? FileInventoryViewState.readyEmpty
      : FileInventoryViewState.readyWithFiles;
}
