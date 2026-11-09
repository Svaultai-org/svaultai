/// A bounded, device-local answer to "what does that file say?".
///
/// The caller fetches only ciphertext through the V2 or owner-proof reader.
/// This helper never sends clear text to a chat service and clears the opened
/// byte buffer even when decoding or the session check fails.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'zk_private_chat.dart';

const int maxLocalTextFollowUpBytes = 128 * 1024;

bool isLocallyReadableText(String name, String? mimeType) {
  final mime = (mimeType ?? '').toLowerCase().split(';').first.trim();
  final lowerName = name.toLowerCase();
  final extension = RegExp(r'\.(txt|md|json|vtt|srt)$').hasMatch(lowerName);
  if (mime.startsWith('text/') ||
      mime == 'application/json' ||
      mime == 'application/x-subrip') {
    return true;
  }
  return (mime.isEmpty || mime == 'application/octet-stream') && extension;
}

String? localTextFollowUpExcerpt({
  required Uint8List bytes,
  required String fileName,
  required String? mimeType,
  required bool Function() accessIsCurrent,
}) {
  try {
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    if (!isLocallyReadableText(fileName, mimeType)) return null;
    if (bytes.length > maxLocalTextFollowUpBytes) {
      throw const FormatException('File exceeds local text read limit');
    }
    final content = utf8.decode(bytes);
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    return localFileTextExcerpt(ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'selected',
      title: fileName,
      searchText: content,
    ));
  } finally {
    bytes.fillRange(0, bytes.length, 0);
  }
}
