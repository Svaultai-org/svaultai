import 'dart:typed_data';

class ChatAttachmentSummary {
  final String name;

  final String kind;

  final String? mimeType;

  final int? size;

  const ChatAttachmentSummary({
    required this.name,
    required this.kind,
    this.mimeType,
    this.size,
  });
}

class ChatMessage {
  static const String kText = 'text';
  static const String kVaultFile = 'vault_file';
  static const String kInlineCredential = 'inline_credential';

  static const String kVaultFileList = 'vault_file_list';
  static const String kMemory = 'memory';
  static const String kRelationship = 'relationship';
  static const String kConcierge = 'concierge';
  static const String kExpiry = 'expiry';

  static const String kVaultInventory = 'vault_inventory';
  static const String kTravelReadiness = 'travel_readiness';
  static const String kCredentialFiles = 'credential_files';
  static const String kRelatedFiles = 'related_files';

  static const String kFileDisambiguation = 'file_disambiguation';

  static const String kFileSearchResults = 'file_search_results';

  static const String kRelatedFilesGraph = 'related_files_graph';

  static const String kVaultRelationshipClusters =
      'vault_relationship_clusters';

  static const String kCredentialExtractionReview =
      'credential_extraction_review';

  static const String kDeepAnswerProgress = 'deep_answer_progress';

  static const String kVaultBrainAnswer = 'vault_brain_answer';

  static const String kSecureItemResults = 'secure_item_results';

  static const String kCryptoWalletAction = 'crypto_wallet_action';

  static const String kVaultChatCard = 'vault_chat_card';

  final String role;

  /// Immutable UI identity and request correlation.  Assistant messages use
  /// [replyToMessageId] to name the exact user turn they belong to; late
  /// callbacks never infer placement from the last list item.
  final String messageId;
  final String? requestId;
  final String? replyToMessageId;

  final String text;
  final String kind;

  final String? fileId;
  final String? fileName;
  final String? mimeType;

  final Map<String, dynamic>? payload;

  final List<ChatAttachmentSummary>? attachments;

  final DateTime createdAt;

  ChatMessage(
    this.role,
    this.text, {
    String? messageId,
    this.requestId,
    this.replyToMessageId,
    this.kind = kText,
    this.fileId,
    this.fileName,
    this.mimeType,
    this.payload,
    this.attachments,
    DateTime? createdAt,
  })  : messageId = messageId ??
            '${role}_${DateTime.now().microsecondsSinceEpoch}_'
                '${identityHashCode(Object())}',
        createdAt = createdAt ?? DateTime.now();

  ChatMessage withCorrelationFrom(ChatMessage original) => ChatMessage(
        role,
        text,
        messageId: original.messageId,
        requestId: original.requestId,
        replyToMessageId: original.replyToMessageId,
        kind: kind,
        fileId: fileId,
        fileName: fileName,
        mimeType: mimeType,
        payload: payload,
        attachments: attachments,
        createdAt: createdAt,
      );

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';
  bool get isSystem => role == 'system';

  bool get isCard =>
      kind == kVaultFile ||
      kind == kInlineCredential ||
      kind == kVaultFileList ||
      kind == kMemory ||
      kind == kRelationship ||
      kind == kConcierge ||
      kind == kExpiry ||
      kind == kVaultInventory ||
      kind == kTravelReadiness ||
      kind == kCredentialFiles ||
      kind == kCredentialExtractionReview ||
      kind == kDeepAnswerProgress ||
      kind == kRelatedFiles ||
      kind == kRelatedFilesGraph ||
      kind == kVaultRelationshipClusters ||
      kind == kFileDisambiguation ||
      kind == kFileSearchResults ||
      kind == kVaultBrainAnswer ||
      kind == kSecureItemResults ||
      kind == kCryptoWalletAction ||
      kind == kVaultChatCard;

  bool get hasAttachments => (attachments?.isNotEmpty ?? false);
}

class ChatAttachment {
  final String name;
  final String kind;
  final Uint8List bytes;
  final String? mimeType;
  final int size;
  String? uploadedFileId;
  bool uploaded;

  ChatAttachment({
    required this.name,
    required this.kind,
    required this.bytes,
    required this.size,
    this.mimeType,
    this.uploadedFileId,
    this.uploaded = false,
  });

  ChatAttachment copy() => ChatAttachment(
        name: name,
        kind: kind,
        bytes: bytes,
        size: size,
        mimeType: mimeType,
        uploadedFileId: uploadedFileId,
        uploaded: uploaded,
      );
}
