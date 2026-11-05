enum ZkPinGateMigrationScheduleFailure { metadata, content }

/// Starts the optional post-unlock migrations only for a successfully
/// restored OPAQUE vault. Each scheduler is best-effort: a failure to queue
/// one must neither prevent the other nor turn a valid unlock into a failure.
void runZkPinGateMigrationBestEffort({
  required bool pinGateRequested,
  required bool opaqueRestored,
  required void Function() scheduleMetadata,
  required void Function() scheduleContent,
  void Function(ZkPinGateMigrationScheduleFailure)? onScheduleFailure,
}) {
  if (!pinGateRequested || !opaqueRestored) return;

  try {
    scheduleMetadata();
  } catch (_) {
    try {
      onScheduleFailure?.call(ZkPinGateMigrationScheduleFailure.metadata);
    } catch (_) {
      // The authenticated session is already usable.
    }
  }
  try {
    scheduleContent();
  } catch (_) {
    try {
      onScheduleFailure?.call(ZkPinGateMigrationScheduleFailure.content);
    } catch (_) {
      // The authenticated session is already usable.
    }
  }
}
