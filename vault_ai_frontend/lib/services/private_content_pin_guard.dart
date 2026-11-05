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

bool blocksZkLegacyContentRoute({String? vaultHandle}) =>
    kGuardZkPrivateContentPinRoutes &&
    ((vaultHandle?.isNotEmpty ?? false) ||
        (ZkActiveMvk.currentVaultHandle()?.isNotEmpty ?? false));

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
