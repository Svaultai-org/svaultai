/// Select an older-file read before any legacy PIN request is constructed.
///
/// The caller may use the proof reader only when this session has an explicit
/// signed download offer. A strict private-file build fails closed if that
/// offer is absent, while an ordinary legacy session retains its old path.
library;

enum ZkLegacyFileReadRoute { notApplicable, proofOnly, unavailable }

ZkLegacyFileReadRoute selectZkLegacyFileReadRoute({
  required bool availableV2,
  required bool requireReadyV2,
  required bool requirePinFreeChat,
  required bool signedPrivateChatOffered,
  required bool strictPinFreeFiles,
  required bool signedLegacyDownloadOffered,
}) {
  if (availableV2 || requireReadyV2) {
    return ZkLegacyFileReadRoute.notApplicable;
  }
  if (!requirePinFreeChat && !signedPrivateChatOffered && !strictPinFreeFiles) {
    return ZkLegacyFileReadRoute.notApplicable;
  }
  return signedLegacyDownloadOffered
      ? ZkLegacyFileReadRoute.proofOnly
      : ZkLegacyFileReadRoute.unavailable;
}
