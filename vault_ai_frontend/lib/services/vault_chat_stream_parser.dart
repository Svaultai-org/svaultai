
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../ui/chat/chat_models.dart';




Map<String, dynamic>? _asStringDynamicMap(Object? raw) {
  if (raw is Map<String, dynamic>) return raw;
  if (raw is Map) {
    return raw.map<String, dynamic>(
      (key, value) => MapEntry(key.toString(), value),
    );
  }
  return null;
}


bool _looksLikeJsonEnvelope(String trimmed) {
  if (trimmed.length < 2) return false;
  if (!trimmed.startsWith('{')) return false;

  var end = trimmed.length - 1;
  while (end > 0) {
    final ch = trimmed.codeUnitAt(end);

    if (ch == 0x20 || ch == 0x09 || ch == 0x0A ||
        ch == 0x0D || ch == 0x00) {
      end--;
      continue;
    }
    break;
  }
  if (end <= 0) return false;
  return trimmed.codeUnitAt(end) == 0x7D;
}





@visibleForTesting
Map<String, dynamic>? tryDecodeJsonEnvelope(String buffer) {
  final trimmed = buffer.trim();
  if (!_looksLikeJsonEnvelope(trimmed)) {
    return null;
  }

  var endIdx = trimmed.length;
  while (endIdx > 0) {
    final ch = trimmed.codeUnitAt(endIdx - 1);
    if (ch == 0x7D) break;
    endIdx--;
  }
  final safe = endIdx == trimmed.length
      ? trimmed
      : trimmed.substring(0, endIdx);

  try {
    final decoded = jsonDecode(safe);
    return _asStringDynamicMap(decoded);
  } catch (e) {
    if (kDebugMode) {
      debugPrint(
        '[vault_chat_stream_parser] json_decode_failed '
        'len=${buffer.length} first_20='
        '${_safePreview(safe, 20)} '
        'error=${e.runtimeType}',
      );
    }
    return null;
  }
}


String _safePreview(String s, int maxLen) {
  final len = s.length;
  if (len <= maxLen) return s;
  return '${s.substring(0, maxLen)}…';
}




ChatMessage? parseVaultChatCardMessage(String buffer) {
  final decoded = tryDecodeJsonEnvelope(buffer);
  if (decoded == null) {

    return null;
  }

  final type = decoded['type']?.toString();
  final schema = decoded['schema']?.toString();
  final intent = decoded['intent']?.toString();
  final cardRaw = decoded['card'];
  final cardMap = _asStringDynamicMap(cardRaw) ?? const <String, dynamic>{};
  final cardType = cardMap['cardType']?.toString();


  if (kDebugMode) {
    debugPrint(
      '[vault_chat_stream_parser] envelope_scan '
      'len=${buffer.length} '
      'type=${type ?? "(missing)"} '
      'schema=${schema ?? "(missing)"} '
      'intent=${intent ?? "(missing)"} '
      'card_type=${cardType ?? "(missing)"}',
    );
  }






  if (type != 'vault_chat_card' &&
      type != 'vault_chat_response_v1' &&
      schema != 'vault_chat_response_v1') {
    if (kDebugMode) {
      debugPrint(
        '[vault_chat_stream_parser] not_a_vault_chat_card '
        'type=${type ?? "(missing)"} '
        'schema=${schema ?? "(missing)"}',
      );
    }
    return null;
  }




  if (cardType == null || cardType.isEmpty) {
    if (kDebugMode) {
      debugPrint(
        '[vault_chat_stream_parser] envelope_missing_card_type '
        'intent=${intent ?? "(missing)"}',
      );
    }
    return null;
  }

  final payload = <String, dynamic>{
    'intent': intent ?? '',
    'card':   cardMap,
    if (schema != null && schema.isNotEmpty) 'schema': schema,
  };


  final rawMessage = decoded['message']?.toString() ?? '';

  if (kDebugMode) {
    debugPrint(
      '[vault_chat_stream_parser] emit_vault_chat_card '
      'renderer=vault_chat_card intent=${intent ?? "(missing)"} '
      'card_type=$cardType message_len=${rawMessage.length}',
    );
  }

  return ChatMessage(
    'assistant',
    rawMessage,
    kind: ChatMessage.kVaultChatCard,
    payload: payload,
  );
}





@visibleForTesting
Map<String, dynamic>? decodeVaultChatEnvelopeForTest(String buffer) =>
    tryDecodeJsonEnvelope(buffer);
