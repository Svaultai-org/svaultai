

import 'chat_models.dart';


String askBrainUserPromptLabel({
  required String fileName,
  String? savedName,
}) {
  final saved = (savedName ?? '').trim();
  final fallback = fileName.trim().isEmpty ? 'this file' : fileName.trim();
  final label = saved.isNotEmpty ? saved : fallback;
  return 'Show me $label';
}


List<ChatMessage> buildAskBrainHandoff({
  required String fileId,
  required String fileName,
  String? savedName,
  String? mimeType,
  String? assetType,
  String? relativePath,
  int? sizeBytes,
}) {
  final saved = (savedName ?? '').trim();
  final rp = (relativePath ?? '').trim();
  final at = (assetType ?? '').trim();

  final payload = <String, dynamic>{
    if (saved.isNotEmpty) 'saved_name': saved,
    if (rp.isNotEmpty) 'relative_path': rp,
    if (at.isNotEmpty) 'asset_type': at,
    if (sizeBytes != null && sizeBytes > 0) 'size_bytes': sizeBytes,
  };

  final label = saved.isNotEmpty
      ? saved
      : (fileName.trim().isEmpty ? 'this file' : fileName.trim());

  return <ChatMessage>[
    ChatMessage(
      'user',
      'Show me $label',
    ),
    ChatMessage(
      'assistant',
      'Here is "$label" from your vault.',
      kind: ChatMessage.kVaultFile,
      fileId: fileId,
      fileName: fileName,
      mimeType: mimeType,
      payload: payload.isEmpty ? null : payload,
    ),
  ];
}
