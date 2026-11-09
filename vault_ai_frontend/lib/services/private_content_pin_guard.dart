/// Stops server-side content discovery from receiving a ZK vault PIN while
/// the private chat or explicit private-content guard is enabled.
library;

import 'zk_active_mvk.dart';

const bool kGuardZkPrivateContentPinRoutes = bool.fromEnvironment(
      'VAULTAI_ENABLE_ZK_PRIVATE_ONLY_UNLOCK',
      defaultValue: false,
    ) ||
    bool.fromEnvironment(
      'VAULTAI_ENABLE_ZK_PRIVATE_CHAT',
      defaultValue: false,
    );

// Narrow opt-in: related-file suggestions can use the local V2 file index
// without enabling the rest of private chat. Legacy files are not included.
const bool kEnableZkLocalRelatedFiles = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_LOCAL_RELATED_FILES',
  defaultValue: false,
);

// Narrow opt-in: the credential deep scan reads a bounded private V2 index
// locally. Its server-side start/poll requests must not receive a ZK PIN.
const bool kEnableZkLocalDeepScan = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_LOCAL_DEEP_SCAN',
  defaultValue: false,
);

bool _hasZkVault({String? vaultHandle}) =>
    (vaultHandle?.isNotEmpty ?? false) ||
    ZkActiveMvk.current() != null ||
    (ZkActiveMvk.currentVaultHandle()?.isNotEmpty ?? false);

bool blocksZkLegacyContentRoute({String? vaultHandle}) =>
    kGuardZkPrivateContentPinRoutes && _hasZkVault(vaultHandle: vaultHandle);

bool blocksZkRelatedFilesPinRoute({String? vaultHandle}) =>
    (kGuardZkPrivateContentPinRoutes || kEnableZkLocalRelatedFiles) &&
    _hasZkVault(vaultHandle: vaultHandle);

bool blocksZkDeepAnswerPinRoute({String? vaultHandle}) =>
    (kGuardZkPrivateContentPinRoutes || kEnableZkLocalDeepScan) &&
    _hasZkVault(vaultHandle: vaultHandle);

class PrivateContentSearchUnavailable implements Exception {
  final String message;

  const PrivateContentSearchUnavailable(this.message);

  @override
  String toString() => message;
}

const deepScanPrivateMessage =
    'Deep scan is not available in private mode yet. '
    'You can search saved names and searchable text in chat.';

const relatedFilesPrivateMessage =
    'Related-file suggestions are not available in private mode yet. '
    'Ask chat to find a file by its saved name or searchable text.';
