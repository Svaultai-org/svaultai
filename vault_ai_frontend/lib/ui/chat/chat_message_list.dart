import 'dart:async';

import 'package:flutter/material.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../tokens.dart';
import '../vault_chat_cards.dart' as vcr_ui;
import 'chat_bubble.dart';
import 'chat_models.dart';
import 'crypto_wallet_action_card.dart';
import 'typing_pulse.dart';

class ChatMessageList extends StatefulWidget {
  final List<ChatMessage> messages;
  final bool thinking;
  final bool streaming;
  final bool isMobile;
  final EdgeInsets padding;
  final ScrollController? scrollController;

  /// User-chosen vault name — the product-facing identity for
  /// both the vault and its AI keeper. Composes the typing
  /// indicator label. Null when no name has been set on this
  /// device — the typing indicator then falls back to the neutral
  /// "Svaultai is thinking..." literal. MUST NOT be substituted
  /// with the display name, VLT handle, vault_id, random
  /// placeholder, or any hash.
  final String? vaultName;
  final void Function(ChatMessage msg)? onOpenVaultFile;

  /// Real download callback — distinct from onOpenVaultFile.
  final void Function(ChatMessage msg)? onDownloadVaultFile;

  /// Per-file in-flight tracking, provided by main.dart from AppState.
  /// Cards render a spinner + disable buttons based on membership.
  final Set<String> viewInFlightFileIds;
  final Set<String> downloadInFlightFileIds;

  /// Callback that re-issues the "show more" chat prompt so the
  /// backend re-emits the next paginated slice of the file list.
  final VoidCallback? onShowMoreFiles;

  /// True while a Show more request is in flight, so file-list cards
  /// disable their button + render a spinner.
  final bool isShowMoreFilesInFlight;

  final void Function(String fileId)? onShowRelated;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;
  final FutureOr<void> Function(
      ChatMessage msg, String action, Map<String, dynamic>? data)? onCardAction;

  final Future<Map<String, dynamic>?> Function(String jobId)? onDeepAnswerPoll;

  final void Function(Map<String, dynamic> snapshot)? onDeepAnswerReady;

  final void Function(ChatMessage credentialMsg)? onScanRemaining;

  final bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive;

  final void Function(String itemId, String title, String itemType)?
      onSecureItemView;
  final void Function(String itemId, String title, String itemType)?
      onSecureItemReveal;
  final void Function(String username)? onSecureItemCopyUsername;
  final void Function(String value)? onSecureItemCopyValue;
  final void Function(String title, String itemType)? onSecureItemEdit;
  final void Function(String title, String itemType)? onSecureItemDelete;

  final CryptoWalletActionCallback? onCryptoWalletAction;

  final VoidCallback? onOpenVault;
  final void Function(String asset)? onOpenAssetDetail;
  final VoidCallback? onOpenSendFlow;
  final VoidCallback? onOpenSecurityPage;
  final VoidCallback? onOpenBillingPage;
  final VoidCallback? onOpenStoragePage;
  final void Function(String category, String? id)? onOpenVaultItem;
  final void Function(String query)? onSearchVault;

  final vcr_ui.CryptoBalanceFetcher? onFetchCryptoBalance;
  final vcr_ui.CryptoActivityFetcher? onFetchCryptoActivity;
  final vcr_ui.CryptoChatLiveCache? cryptoCache;

  final bool cryptoEntitled;
  final VoidCallback? onOpenCryptoUpgrade;

  const ChatMessageList({
    super.key,
    required this.messages,
    required this.thinking,
    required this.streaming,
    required this.isMobile,
    this.padding = const EdgeInsets.symmetric(
      horizontal: VaultSpacing.md,
      vertical: VaultSpacing.md,
    ),
    this.scrollController,
    this.vaultName,
    this.onOpenVaultFile,
    this.onDownloadVaultFile,
    this.viewInFlightFileIds = const <String>{},
    this.downloadInFlightFileIds = const <String>{},
    this.onShowMoreFiles,
    this.isShowMoreFilesInFlight = false,
    this.onShowRelated,
    this.onLoadRelated,
    this.onCardAction,
    this.onDeepAnswerPoll,
    this.onDeepAnswerReady,
    this.onScanRemaining,
    this.isDeepScanActive,
    this.onSecureItemView,
    this.onSecureItemReveal,
    this.onSecureItemCopyUsername,
    this.onSecureItemCopyValue,
    this.onSecureItemEdit,
    this.onSecureItemDelete,
    this.onCryptoWalletAction,
    this.onOpenVault,
    this.onOpenAssetDetail,
    this.onOpenSendFlow,
    this.onOpenSecurityPage,
    this.onOpenBillingPage,
    this.onOpenStoragePage,
    this.onOpenVaultItem,
    this.onSearchVault,
    this.onFetchCryptoBalance,
    this.onFetchCryptoActivity,
    this.cryptoCache,
    this.cryptoEntitled = true,
    this.onOpenCryptoUpgrade,
  });

  @override
  State<ChatMessageList> createState() => _ChatMessageListState();
}

class _ChatMessageListState extends State<ChatMessageList> {
  static const double _autoFollowThresholdPx = 96;

  late final ScrollController _scroll;
  bool _ownsScroll = false;

  final Set<int> _animated = <int>{};

  @override
  void initState() {
    super.initState();
    _scroll = widget.scrollController ?? ScrollController();
    _ownsScroll = widget.scrollController == null;
  }

  @override
  void dispose() {
    if (_ownsScroll) _scroll.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant ChatMessageList old) {
    super.didUpdateWidget(old);

    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeAutoScroll());
  }

  void _maybeAutoScroll() {
    if (!_scroll.hasClients) return;
    final pos = _scroll.position;
    final distanceFromBottom = pos.maxScrollExtent - pos.pixels;
    if (distanceFromBottom < _autoFollowThresholdPx) {
      _scroll.animateTo(
        pos.maxScrollExtent,
        duration: VaultMotion.standard,
        curve: VaultMotion.curveStandard,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final msgs = widget.messages;
    final itemCount = msgs.length + (widget.thinking ? 1 : 0);

    return ListView.builder(
      controller: _scroll,
      padding: widget.padding,
      itemCount: itemCount,
      itemBuilder: (context, index) {
        if (widget.thinking && index == msgs.length) {
          final l = AppLocalizations.of(context);
          // Typing indicator label source is the user-chosen
          // vault name (the same string the user typed to sign
          // in). Before migration 0031, the ZK signup path wrote
          // ``encode(gen_random_bytes(16),'hex')`` into
          // ``vaults.vault_name`` as a placeholder to satisfy
          // NOT NULL UNIQUE — that hex string then leaked into
          // production as
          // "b21e31c5b59abdc8067ff6b23643b254 is thinking...".
          // Migration 0031 dropped the placeholder path; this
          // widget now reads the real product name, and falls
          // back to the neutral "Svaultai is thinking..." literal
          // when the row is unset. Never use vault_id, display
          // name, VLT handle, or any hash here.
          final name = widget.vaultName?.trim();
          final label = (name != null && name.isNotEmpty)
              ? l.chatThinkingWithName(name)
              : l.chatThinking;
          return FadeSlideIn(
            child: TypingPulse(label: label),
          );
        }

        final msg = msgs[index];
        final prev = index > 0 ? msgs[index - 1] : null;
        final next = index < msgs.length - 1 ? msgs[index + 1] : null;

        final isFirst = prev == null ||
            prev.role != msg.role ||
            msg.createdAt.difference(prev.createdAt).inSeconds > 60;
        final isLast = next == null ||
            next.role != msg.role ||
            next.createdAt.difference(msg.createdAt).inSeconds > 60;

        final isStreamingTail =
            widget.streaming && msg.isAssistant && index == msgs.length - 1;

        final firstSeen = !_animated.contains(index);
        if (firstSeen) _animated.add(index);

        final bubble = ChatBubble(
          msg: msg,
          isMobile: widget.isMobile,
          isFirstInGroup: isFirst,
          isLastInGroup: isLast,
          isStreaming: isStreamingTail,
          onOpenVaultFile: widget.onOpenVaultFile,
          onDownloadVaultFile: widget.onDownloadVaultFile,
          viewInFlightFileIds: widget.viewInFlightFileIds,
          downloadInFlightFileIds: widget.downloadInFlightFileIds,
          onShowMoreFiles: widget.onShowMoreFiles,
          isShowMoreFilesInFlight: widget.isShowMoreFilesInFlight,
          onShowRelated: widget.onShowRelated,
          onLoadRelated: widget.onLoadRelated,
          onCardAction: widget.onCardAction,
          onDeepAnswerPoll: widget.onDeepAnswerPoll,
          onDeepAnswerReady: widget.onDeepAnswerReady,
          onScanRemaining: widget.onScanRemaining,
          isDeepScanActive: widget.isDeepScanActive,
          onSecureItemView: widget.onSecureItemView,
          onSecureItemReveal: widget.onSecureItemReveal,
          onSecureItemCopyUsername: widget.onSecureItemCopyUsername,
          onSecureItemCopyValue: widget.onSecureItemCopyValue,
          onSecureItemEdit: widget.onSecureItemEdit,
          onSecureItemDelete: widget.onSecureItemDelete,
          onCryptoWalletAction: widget.onCryptoWalletAction,
          onOpenVault: widget.onOpenVault,
          onOpenAssetDetail: widget.onOpenAssetDetail,
          onOpenSendFlow: widget.onOpenSendFlow,
          onOpenSecurityPage: widget.onOpenSecurityPage,
          onOpenBillingPage: widget.onOpenBillingPage,
          onOpenStoragePage: widget.onOpenStoragePage,
          onOpenVaultItem: widget.onOpenVaultItem,
          onSearchVault: widget.onSearchVault,
          onFetchCryptoBalance: widget.onFetchCryptoBalance,
          onFetchCryptoActivity: widget.onFetchCryptoActivity,
          cryptoCache: widget.cryptoCache,
          cryptoEntitled: widget.cryptoEntitled,
          onOpenCryptoUpgrade: widget.onOpenCryptoUpgrade,
        );

        final messageIdentifier =
            msg.isUser ? 'chat_user_message' : 'chat_assistant_message';
        return RepaintBoundary(
          key: ValueKey(msg.messageId),
          child: FadeSlideIn(
            animate: firstSeen,
            duration: VaultMotion.emphasized,
            offset: 10,
            child: Semantics(
              container: true,
              identifier: '${messageIdentifier}_${msg.messageId}',
              child: bubble,
            ),
          ),
        );
      },
    );
  }
}
