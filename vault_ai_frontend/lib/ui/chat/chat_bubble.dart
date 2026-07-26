

import 'package:flutter/material.dart';
import '../tokens.dart';
import '../../services/vault_chat_router.dart' as vcr;
import '../vault_chat_cards.dart' as vcr_ui;
import 'chat_cards.dart';
import 'chat_models.dart';
import 'crypto_wallet_action_card.dart';

class ChatBubble extends StatelessWidget {
  final ChatMessage msg;
  final bool isMobile;
  final bool isFirstInGroup;
  final bool isLastInGroup;
  final bool isStreaming;
  final void Function(ChatMessage msg)? onOpenVaultFile;

  /// Distinct from onOpenVaultFile — Download must NOT open the media
  /// viewer, it should trigger a real browser file download and
  /// preserve the original filename + MIME.
  final void Function(ChatMessage msg)? onDownloadVaultFile;

  /// File ids currently being fetched for View / Download. The
  /// cards render a spinner + disable buttons based on membership.
  final Set<String> viewInFlightFileIds;
  final Set<String> downloadInFlightFileIds;

  /// Callback used by VaultFileListCard's Show more button. Parent
  /// re-issues the chat prompt "show more" so the backend re-emits
  /// the next paginated slice.
  final VoidCallback? onShowMoreFiles;

  /// True while the "show more" request is in flight.
  final bool isShowMoreFilesInFlight;


  final void Function(String fileId)? onShowRelated;
  
  
  final Future<Map<String, dynamic>?> Function(String jobId)?
      onDeepAnswerPoll;
  
  
  final void Function(Map<String, dynamic> snapshot)? onDeepAnswerReady;
  
  
  final void Function(ChatMessage credentialMsg)? onScanRemaining;
  
  
  final bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive;
  

  final CryptoWalletActionCallback? onCryptoWalletAction;


  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;
  final void Function(ChatMessage msg, String action, Map<String, dynamic>? data)?
      onCardAction;


  final VoidCallback? onBrainSearchDeeper;


  final void Function(String itemId, String title, String itemType)?
      onSecureItemView;
  final void Function(String itemId, String title, String itemType)?
      onSecureItemReveal;
  final void Function(String username)? onSecureItemCopyUsername;

  final void Function(String value)? onSecureItemCopyValue;
  final void Function(String title, String itemType)? onSecureItemEdit;
  final void Function(String title, String itemType)? onSecureItemDelete;



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

  const ChatBubble({
    super.key,
    required this.msg,
    required this.isMobile,
    this.isFirstInGroup = true,
    this.isLastInGroup = true,
    this.isStreaming = false,
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
    this.onBrainSearchDeeper,
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
  Widget build(BuildContext context) {
    if (msg.isCard) {
      return _CardBubble(
        msg: msg,
        isMobile: isMobile,
        isFirstInGroup: isFirstInGroup,
        onOpenVaultFile: onOpenVaultFile,
        onDownloadVaultFile: onDownloadVaultFile,
        viewInFlightFileIds: viewInFlightFileIds,
        downloadInFlightFileIds: downloadInFlightFileIds,
        onShowMoreFiles: onShowMoreFiles,
        isShowMoreFilesInFlight: isShowMoreFilesInFlight,
        onShowRelated: onShowRelated,
        onLoadRelated: onLoadRelated,
        onCardAction: onCardAction,
        onDeepAnswerPoll: onDeepAnswerPoll,
        onDeepAnswerReady: onDeepAnswerReady,
        onScanRemaining: onScanRemaining,
        isDeepScanActive: isDeepScanActive,
        onBrainSearchDeeper: onBrainSearchDeeper,
        onCryptoWalletAction: onCryptoWalletAction,
        onOpenVault: onOpenVault,
        onOpenAssetDetail: onOpenAssetDetail,
        onOpenSendFlow: onOpenSendFlow,
        onOpenSecurityPage: onOpenSecurityPage,
        onOpenBillingPage: onOpenBillingPage,
        onOpenStoragePage: onOpenStoragePage,
        onOpenVaultItem: onOpenVaultItem,
        onSearchVault: onSearchVault,
        onFetchCryptoBalance:  onFetchCryptoBalance,
        onFetchCryptoActivity: onFetchCryptoActivity,
        cryptoCache:           cryptoCache,
        cryptoEntitled:        cryptoEntitled,
        onOpenCryptoUpgrade:   onOpenCryptoUpgrade,
        onSecureItemView: onSecureItemView,
        onSecureItemReveal: onSecureItemReveal,
        onSecureItemCopyUsername: onSecureItemCopyUsername,
        onSecureItemCopyValue: onSecureItemCopyValue,
        onSecureItemEdit: onSecureItemEdit,
        onSecureItemDelete: onSecureItemDelete,
      );
    }
    return _TextBubble(
      msg: msg,
      isMobile: isMobile,
      isFirstInGroup: isFirstInGroup,
      isLastInGroup: isLastInGroup,
      isStreaming: isStreaming,
    );
  }
}


class _TextBubble extends StatelessWidget {
  final ChatMessage msg;
  final bool isMobile;
  final bool isFirstInGroup;
  final bool isLastInGroup;
  final bool isStreaming;

  const _TextBubble({
    required this.msg,
    required this.isMobile,
    required this.isFirstInGroup,
    required this.isLastInGroup,
    required this.isStreaming,
  });

  @override
  Widget build(BuildContext context) {
    final isUser = msg.isUser;
    final maxFraction = isMobile ? 0.86 : 0.62;

    final radius = _bubbleRadius(
      isUser: isUser,
      isFirstInGroup: isFirstInGroup,
      isLastInGroup: isLastInGroup,
    );

    final decoration = isUser
        ? BoxDecoration(
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                VaultColors.bubbleUserA,
                VaultColors.bubbleUserB,
              ],
            ),
            borderRadius: radius,
            boxShadow: VaultShadows.e1,
          )
        : BoxDecoration(
            color: VaultColors.bubbleAssistant,
            borderRadius: radius,
            border: Border.all(color: VaultColors.borderSubtle),
            boxShadow: VaultShadows.e1,
          );

    final textColor = isUser
        ? VaultColors.textOnAccent
        : VaultColors.textPrimary;

    
    final renderAttachments = isUser && msg.hasAttachments;
    final textIsBlank = msg.text.isEmpty;
    final content = ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * maxFraction,
      ),
      child: Container(
        padding: EdgeInsets.symmetric(
          vertical: VaultSpacing.md,
          horizontal: isMobile ? VaultSpacing.md + 2 : VaultSpacing.lg,
        ),
        decoration: decoration,
        child: Column(
          crossAxisAlignment: isUser
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (renderAttachments)
              MessageAttachmentList(
                attachments: msg.attachments!,
                isMobile: isMobile,
                onAccent: isUser,
              ),
            if (renderAttachments && !textIsBlank)
              const SizedBox(height: VaultSpacing.sm),
            if (!(renderAttachments && textIsBlank))
              SelectableText(
                msg.text.isEmpty && isStreaming ? '...' : msg.text,
                style: VaultText.bodyLg.copyWith(color: textColor),
              ),
            if (isStreaming && !isUser)
              const Padding(
                padding: EdgeInsets.only(top: VaultSpacing.xs),
                child: _StreamingCaret(),
              ),
          ],
        ),
      ),
    );

    return Padding(
      padding: EdgeInsets.only(
        top: isFirstInGroup ? VaultSpacing.md : VaultSpacing.xs,
        bottom: isLastInGroup ? VaultSpacing.md : 0,
        left: VaultSpacing.xs,
        right: VaultSpacing.xs,
      ),
      child: Align(
        alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
        child: isUser
            ? content
            : Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisSize: MainAxisSize.min,
                children: [
                  _AssistantAvatar(visible: isFirstInGroup),
                  const SizedBox(width: VaultSpacing.sm),
                  Flexible(child: content),
                ],
              ),
      ),
    );
  }

  BorderRadius _bubbleRadius({
    required bool isUser,
    required bool isFirstInGroup,
    required bool isLastInGroup,
  }) {
    const r = Radius.circular(VaultRadius.xl);
    const tight = Radius.circular(VaultRadius.sm);
    
    
    if (isUser) {
      return BorderRadius.only(
        topLeft: r,
        bottomLeft: r,
        topRight: isFirstInGroup ? r : tight,
        bottomRight: isLastInGroup ? r : tight,
      );
    }
    return BorderRadius.only(
      topRight: r,
      bottomRight: r,
      topLeft: isFirstInGroup ? r : tight,
      bottomLeft: isLastInGroup ? r : tight,
    );
  }
}


class _CardBubble extends StatelessWidget {
  final ChatMessage msg;
  final bool isMobile;
  final bool isFirstInGroup;
  final void Function(ChatMessage msg)? onOpenVaultFile;
  final void Function(ChatMessage msg)? onDownloadVaultFile;
  final Set<String> viewInFlightFileIds;
  final Set<String> downloadInFlightFileIds;
  final VoidCallback? onShowMoreFiles;
  final bool isShowMoreFilesInFlight;
  final void Function(String fileId)? onShowRelated;
  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;
  final void Function(ChatMessage msg, String action, Map<String, dynamic>? data)?
      onCardAction;
  final Future<Map<String, dynamic>?> Function(String jobId)?
      onDeepAnswerPoll;
  final void Function(Map<String, dynamic> snapshot)? onDeepAnswerReady;
  final void Function(ChatMessage credentialMsg)? onScanRemaining;
  final bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive;
  final VoidCallback? onBrainSearchDeeper;
  
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

  const _CardBubble({
    required this.msg,
    required this.isMobile,
    required this.isFirstInGroup,
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
    this.onBrainSearchDeeper,
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
  Widget build(BuildContext context) {
    Widget body;
    switch (msg.kind) {
      case ChatMessage.kVaultFile:
        body = VaultFileCard(
          msg: msg,
          onOpen: () => onOpenVaultFile?.call(msg),
          onDownload: onDownloadVaultFile == null
              ? null
              : () => onDownloadVaultFile!(msg),
          isViewInFlight:
              viewInFlightFileIds.contains(msg.fileId ?? ''),
          isDownloadInFlight:
              downloadInFlightFileIds.contains(msg.fileId ?? ''),
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kVaultFileList:
        body = VaultFileListCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onDownload: onDownloadVaultFile == null
              ? null
              : (fileMsg) => onDownloadVaultFile!(fileMsg),
          viewInFlight: viewInFlightFileIds,
          downloadInFlight: downloadInFlightFileIds,
          onShowMore: onShowMoreFiles,
          isShowMoreInFlight: isShowMoreFilesInFlight,
          onLoadRelated: onLoadRelated,
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kMemory:
        body = MemoryCard(msg: msg);
        break;
      case ChatMessage.kRelationship:
        body = RelationshipCard(msg: msg);
        break;
      case ChatMessage.kConcierge:
        body = ConciergeCard(
          msg: msg,
          onAction: (action, data) =>
              onCardAction?.call(msg, action, data),
        );
        break;
      case ChatMessage.kExpiry:
        body = ExpiryCard(
          msg: msg,
          onAction: (action, data) =>
              onCardAction?.call(msg, action, data),
        );
        break;
      case ChatMessage.kVaultInventory:
        body = VaultInventoryCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onDownload: onDownloadVaultFile == null
              ? null
              : (fileMsg) => onDownloadVaultFile!(fileMsg),
          viewInFlight: viewInFlightFileIds,
          downloadInFlight: downloadInFlightFileIds,
          onLoadRelated: onLoadRelated,
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kTravelReadiness:
        body = TravelReadinessCard(msg: msg);
        break;
      case ChatMessage.kCredentialFiles:
        body = CredentialFileSearchCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onLoadRelated: onLoadRelated,
          onShowRelated: onShowRelated,
          onScanRemaining: onScanRemaining == null
              ? null
              : () => onScanRemaining!(msg),
          isDeepScanActive: isDeepScanActive,
        );
        break;
      case ChatMessage.kCredentialExtractionReview:
        body = CredentialExtractionReviewCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
        );
        break;
      case ChatMessage.kDeepAnswerProgress:
        body = DeepAnswerProgressCard(
          msg: msg,
          onPoll: onDeepAnswerPoll,
          onReady: onDeepAnswerReady,
        );
        break;
      case ChatMessage.kRelatedFiles:
        body = RelatedFilesCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
        );
        break;
      case ChatMessage.kRelatedFilesGraph:
        body = RelatedFilesGraphCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onLoadRelated: onLoadRelated,
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kVaultRelationshipClusters:
        body = VaultRelationshipClustersCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kFileDisambiguation:
        body = FileDisambiguationCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
        );
        break;
      case ChatMessage.kFileSearchResults:
        body = FileSearchResultsCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onLoadRelated: onLoadRelated,
          onShowRelated: onShowRelated,
        );
        break;
      case ChatMessage.kSecureItemResults:
        
        
        body = SecureItemResultsCard(
          msg: msg,
          actions: SecureItemCardActions(
            onView:         onSecureItemView,
            onReveal:       onSecureItemReveal,
            onCopyUsername: onSecureItemCopyUsername,
            onCopyValue:    onSecureItemCopyValue,
            onEdit:         onSecureItemEdit,
            onDelete:       onSecureItemDelete,
          ),
        );
        break;
      case ChatMessage.kCryptoWalletAction:


        body = CryptoWalletActionCard(
          msg: msg,
          onAction: onCryptoWalletAction,
        );
        break;
      case ChatMessage.kVaultChatCard:


        body = _buildVaultChatCardView();
        break;
      case ChatMessage.kVaultBrainAnswer:
        
        
        body = VaultBrainAnswerCard(
          msg: msg,
          onOpen: (fileMsg) => onOpenVaultFile?.call(fileMsg),
          onSearchDeeper: onBrainSearchDeeper,
        );
        break;
      default:
        body = const SizedBox.shrink();
    }

    final maxFraction = isMobile ? 0.92 : 0.72;
    return _wrapCardBody(context, body, maxFraction);
  }


  Widget _buildVaultChatCardView() {
    final payload = msg.payload;
    if (payload == null) {

      return const SizedBox.shrink();
    }
    final intent = payload['intent']?.toString() ?? '';
    final cardRaw = payload['card'];
    final cardMap = cardRaw is Map
        ? cardRaw.cast<String, dynamic>()
        : const <String, dynamic>{};

    final response = vcr.VaultChatResponse.fromJson(<String, dynamic>{
      'intent': intent,
      'card':   cardMap,
    });
    return vcr_ui.VaultChatCardView(
      response: response,
      onOpenVault:        onOpenVault,
      onOpenAssetDetail:  onOpenAssetDetail,
      onOpenSendFlow:     onOpenSendFlow,
      onOpenSecurityPage: onOpenSecurityPage,
      onOpenBillingPage:  onOpenBillingPage,
      onFetchCryptoBalance:  onFetchCryptoBalance,
      onFetchCryptoActivity: onFetchCryptoActivity,
      cryptoCache:           cryptoCache,
      cryptoEntitled:        cryptoEntitled,
      onOpenCryptoUpgrade:   onOpenCryptoUpgrade,

      onLoginEdit: (service) =>
          onSecureItemEdit?.call(service, 'login'),
      onLoginDelete: (service) =>
          onSecureItemDelete?.call(service, 'login'),
      onLoginOpenWebsite: (service, url) {
        if (onCardAction != null) {
          onCardAction!(msg, 'open_login_website', {
            'service': service,
            'url':     url,
          });
        }
      },
      onLoginChooseCandidate: (title) {
        if (onCardAction != null) {
          onCardAction!(msg, 'choose_login', {
            'query': title,
          });
        }
      },
      onLoginSelectById: (id, title) {
        // Id-aware selection: goes through the same onCardAction
        // channel but carries the row's stable item id so the
        // handler can send a selection_hint alongside the natural
        // prompt.
        if (onCardAction != null) {
          onCardAction!(msg, 'select_login_by_id', {
            'id':    id,
            'title': title,
          });
        }
      },
      // 2026-08-01 generated-login draft Save / Cancel wiring. The
      // card owns the visual button row; this file translates the
      // button tap into an `onCardAction` call the main.dart chat
      // controller turns into a "save it" / "cancel" chat message,
      // which the backend state machine consumes to persist or
      // discard the draft.
      onGeneratedLoginSave: (draftId, service) {
        if (onCardAction != null) {
          onCardAction!(msg, 'generated_login_save', {
            'draft_id': draftId,
            'service':  service,
          });
        }
      },
      onGeneratedLoginCancel: (draftId, service) {
        if (onCardAction != null) {
          onCardAction!(msg, 'generated_login_cancel', {
            'draft_id': draftId,
            'service':  service,
          });
        }
      },
    );
  }


  Widget _wrapCardBody(
    BuildContext context, Widget body, double maxFraction,
  ) {

    return Padding(
      padding: EdgeInsets.only(
        top: isFirstInGroup ? VaultSpacing.md : VaultSpacing.xs,
        bottom: VaultSpacing.md,
        left: VaultSpacing.xs,
        right: VaultSpacing.xs,
      ),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            _AssistantAvatar(visible: isFirstInGroup),
            const SizedBox(width: VaultSpacing.sm),
            Flexible(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width * maxFraction,
                ),
                child: body,
              ),
            ),
          ],
        ),
      ),
    );
  }
}


class _AssistantAvatar extends StatelessWidget {
  final bool visible;
  const _AssistantAvatar({this.visible = true});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 28,
      height: 28,
      child: visible
          ? Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    VaultColors.accentBright,
                    VaultColors.accent,
                  ],
                ),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.bolt,
                color: VaultColors.textOnAccent,
                size: 16,
              ),
            )
          : null,
    );
  }
}


class MessageAttachmentList extends StatelessWidget {
  final List<ChatAttachmentSummary> attachments;
  final bool isMobile;

  
  final bool onAccent;

  
  static const double maxHeightDesktop = 220;
  static const double maxHeightMobile = 180;

  const MessageAttachmentList({
    super.key,
    required this.attachments,
    required this.isMobile,
    this.onAccent = false,
  });

  IconData _iconFor(ChatAttachmentSummary a) {
    final mt = (a.mimeType ?? '').toLowerCase();
    if (mt.startsWith('image/')) return Icons.image;
    if (mt.startsWith('video/')) return Icons.videocam_outlined;
    if (mt.startsWith('audio/')) return Icons.audiotrack;
    if (mt == 'application/pdf' || a.name.toLowerCase().endsWith('.pdf')) {
      return Icons.picture_as_pdf;
    }
    
    switch (a.kind) {
      case 'image':
        return Icons.image;
      case 'video':
        return Icons.videocam_outlined;
      case 'audio':
        return Icons.audiotrack;
      default:
        return Icons.insert_drive_file;
    }
  }

  String _formatBytes(int bytes) {
    if (bytes <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    var size = bytes.toDouble();
    var i = 0;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024;
      i++;
    }
    return '${size.toStringAsFixed(size >= 10 || i == 0 ? 0 : 1)} ${units[i]}';
  }

  
  static const int folderSummaryThreshold = 6;

  
  static const int folderSummaryPreviewLimit = 3;

  @override
  Widget build(BuildContext context) {
    final count = attachments.length;
    final fg = onAccent ? VaultColors.textOnAccent : VaultColors.textPrimary;
    final subtleFg = onAccent
        ? VaultColors.textOnAccent.withValues(alpha: 0.78)
        : VaultColors.textSecondary;
    final chipBg = onAccent
        ? Colors.white.withValues(alpha: 0.10)
        : VaultColors.bubbleAssistant;
    final chipBorder = onAccent
        ? Colors.white.withValues(alpha: 0.22)
        : VaultColors.borderSubtle;

    final maxHeight = isMobile ? maxHeightMobile : maxHeightDesktop;

    
    if (count >= folderSummaryThreshold) {
      return _FolderSummaryCard(
        attachments: attachments,
        previewLimit: folderSummaryPreviewLimit,
        fg: fg,
        subtleFg: subtleFg,
        chipBg: chipBg,
        chipBorder: chipBorder,
        iconFor: _iconFor,
        formatBytes: _formatBytes,
      );
    }

    final rows = ListView.builder(
      shrinkWrap: true,
      padding: EdgeInsets.zero,
      itemCount: count,
      itemBuilder: (context, index) {
        final a = attachments[index];
        return _AttachmentRow(
          icon: _iconFor(a),
          name: a.name,
          subtitle: a.size != null && a.size! > 0 ? _formatBytes(a.size!) : null,
          fg: fg,
          subtleFg: subtleFg,
          chipBg: chipBg,
          chipBorder: chipBorder,
        );
      },
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (count >= 2)
          Padding(
            padding: const EdgeInsets.only(bottom: VaultSpacing.xs),
            child: Text(
              'Uploaded $count files',
              style: VaultText.bodySm.copyWith(
                color: subtleFg,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: maxHeight),
          child: rows,
        ),
      ],
    );
  }
}


class _FolderSummaryCard extends StatelessWidget {
  final List<ChatAttachmentSummary> attachments;
  final int previewLimit;
  final Color fg;
  final Color subtleFg;
  final Color chipBg;
  final Color chipBorder;
  final IconData Function(ChatAttachmentSummary) iconFor;
  final String Function(int) formatBytes;

  const _FolderSummaryCard({
    required this.attachments,
    required this.previewLimit,
    required this.fg,
    required this.subtleFg,
    required this.chipBg,
    required this.chipBorder,
    required this.iconFor,
    required this.formatBytes,
  });

  
  String _deriveFolderName() {
    for (final a in attachments) {
      final n = a.name;
      final slash = n.indexOf('/');
      if (slash > 0) return n.substring(0, slash);
    }
    return 'Folder import';
  }

  int _totalBytes() {
    var t = 0;
    for (final a in attachments) {
      final s = a.size;
      if (s != null && s > 0) t += s;
    }
    return t;
  }

  @override
  Widget build(BuildContext context) {
    final folderName = _deriveFolderName();
    final total = _totalBytes();
    final preview = attachments.take(previewLimit).toList(growable: false);
    final remaining = attachments.length - preview.length;

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: chipBg,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: chipBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Icon(Icons.folder_copy_outlined, size: 20, color: fg),
              const SizedBox(width: VaultSpacing.sm),
              Expanded(
                child: Text(
                  folderName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.bodySm.copyWith(
                    color: fg,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            total > 0
                ? '${attachments.length} files · ${formatBytes(total)}'
                : '${attachments.length} files',
            style: VaultText.caption.copyWith(color: subtleFg),
          ),
          if (preview.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            for (final a in preview)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 1),
                child: Row(
                  children: [
                    Icon(iconFor(a), size: 12, color: subtleFg),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        a.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.caption.copyWith(color: subtleFg),
                      ),
                    ),
                  ],
                ),
              ),
            if (remaining > 0) ...[
              const SizedBox(height: 2),
              Text(
                '+$remaining more',
                style: VaultText.caption.copyWith(
                  color: subtleFg,
                  fontStyle: FontStyle.italic,
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}


class _AttachmentRow extends StatelessWidget {
  final IconData icon;
  final String name;
  final String? subtitle;
  final Color fg;
  final Color subtleFg;
  final Color chipBg;
  final Color chipBorder;

  const _AttachmentRow({
    required this.icon,
    required this.name,
    required this.subtitle,
    required this.fg,
    required this.subtleFg,
    required this.chipBg,
    required this.chipBorder,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.sm + 2,
        vertical: VaultSpacing.xs + 2,
      ),
      decoration: BoxDecoration(
        color: chipBg,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: chipBorder),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: fg),
          const SizedBox(width: VaultSpacing.sm),
          Flexible(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.body.copyWith(
                    color: fg,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (subtitle != null && subtitle!.isNotEmpty)
                  Text(
                    subtitle!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: VaultText.bodySm.copyWith(color: subtleFg),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


class _StreamingCaret extends StatefulWidget {
  const _StreamingCaret();

  @override
  State<_StreamingCaret> createState() => _StreamingCaretState();
}

class _StreamingCaretState extends State<_StreamingCaret>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    
    if (MediaQuery.of(context).disableAnimations) {
      return Container(
        width: 7,
        height: 14,
        decoration: BoxDecoration(
          color: VaultColors.accentBright,
          borderRadius: BorderRadius.circular(2),
        ),
      );
    }
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) {
        final v = _ctrl.value;
        final opacity = (1 - (v - 0.5).abs() * 2).clamp(0.25, 1.0);
        return Opacity(
          opacity: opacity,
          child: Container(
            width: 7,
            height: 14,
            decoration: BoxDecoration(
              color: VaultColors.accentBright,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        );
      },
    );
  }
}
