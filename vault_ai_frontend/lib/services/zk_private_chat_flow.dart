/// One unlocked ZK vault's PIN-free chat state. Construct a fresh instance on
/// each vault/session/MVK change; private turns are never put in AI history.

library;

import 'zk_private_chat.dart';
import 'zk_private_chat_index.dart';

enum ZkChatEntryRoute { privateChat, unavailable, legacy }

/// Decide before touching the legacy PIN-derived crypto context. A confirmed
/// ZK session must fail closed if its MVK disappeared or belongs to a different
/// vault, rather than silently falling into the raw-PIN chat pipeline.
ZkChatEntryRoute resolveZkChatEntryRoute({
  required bool privateChatEnabled,
  required bool hasZkHandle,
  required bool hasMvk,
  required bool mvkMatchesVault,
}) {
  if (!privateChatEnabled) return ZkChatEntryRoute.legacy;
  if (!hasZkHandle && !hasMvk) return ZkChatEntryRoute.legacy;
  if (!hasMvk || !mvkMatchesVault) return ZkChatEntryRoute.unavailable;
  return ZkChatEntryRoute.privateChat;
}

class ZkPrivateChatTurn {
  final ZkLocalChatResult local;
  final String? generalReply;
  final bool indexIncomplete;

  const ZkPrivateChatTurn({
    required this.local,
    this.generalReply,
    this.indexIncomplete = false,
  });
}

class ZkPrivateChatFlow {
  final Future<ZkPrivateChatIndex> Function() loadIndex;
  final Future<String> Function(String, List<ZkGeneralChatTurn>) sendGeneral;
  final bool Function() accessIsCurrent;
  final List<ZkGeneralChatTurn> _generalHistory = [];
  ZkLocalChatRecord? _selection;

  ZkPrivateChatFlow({
    required this.loadIndex,
    required this.sendGeneral,
    required this.accessIsCurrent,
  });

  void clear() {
    _selection = null;
    _generalHistory.clear();
  }

  void _checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Vault access changed during private chat');
    }
  }

  Future<ZkPrivateChatTurn> run(String prompt, {bool forcePrivate = false}) async {
    _checkAccess();
    final preliminary = ZkLocalChatRouter.resolve(
      prompt: prompt,
      savedItems: const [],
      files: const [],
      previousSelection: _selection,
      forcePrivate: forcePrivate,
    );
    if (preliminary.disposition == ZkLocalChatDisposition.unsupportedAction) {
      return ZkPrivateChatTurn(local: preliminary);
    }
    if (preliminary.maySendToGeneralAi) {
      final reply = await sendGeneral(
        prompt,
        List<ZkGeneralChatTurn>.unmodifiable(_generalHistory),
      );
      _checkAccess();
      _generalHistory.add(ZkGeneralChatTurn(role: 'user', content: prompt));
      _generalHistory.add(ZkGeneralChatTurn(role: 'assistant', content: reply));
      while (_generalHistory.length > 10) {
        _generalHistory.removeAt(0);
      }
      return ZkPrivateChatTurn(local: preliminary, generalReply: reply);
    }

    final index = await loadIndex();
    _checkAccess();
    final result = ZkLocalChatRouter.resolve(
      prompt: prompt,
      savedItems: index.savedItems,
      files: index.files,
      previousSelection: _selection,
      forcePrivate: forcePrivate,
    );
    _selection = result.disposition == ZkLocalChatDisposition.found
        ? result.selection
        : null;
    return ZkPrivateChatTurn(
      local: result,
      indexIncomplete: index.incomplete,
    );
  }
}
