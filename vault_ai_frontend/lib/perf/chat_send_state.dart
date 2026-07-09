
import 'package:flutter/foundation.dart';

import 'perf_trace.dart';




enum ChatSendPhase {
  idle,
  userBubbleShown,
  thinking,
  streaming,
  done,
  error,
}


@immutable
class ChatSendState {
  final ChatSendPhase phase;
  final String? userMessagePreview;
  final int? elapsedMsSinceSend;
  final String? errorCode;

  const ChatSendState({
    required this.phase,
    this.userMessagePreview,
    this.elapsedMsSinceSend,
    this.errorCode,
  });

  static const ChatSendState idle = ChatSendState(
    phase: ChatSendPhase.idle,
  );

  ChatSendState copyWith({
    ChatSendPhase? phase,
    String? userMessagePreview,
    int? elapsedMsSinceSend,
    String? errorCode,
  }) {
    return ChatSendState(
      phase: phase ?? this.phase,
      userMessagePreview:
          userMessagePreview ?? this.userMessagePreview,
      elapsedMsSinceSend:
          elapsedMsSinceSend ?? this.elapsedMsSinceSend,
      errorCode: errorCode ?? this.errorCode,
    );
  }
}


class ChatSendController extends ValueNotifier<ChatSendState> {
  ChatSendController() : super(ChatSendState.idle);

  DateTime Function() nowClock = () => DateTime.now();

  DateTime? _sentAt;

  bool _looksSensitive(String s) {
    final low = s.toLowerCase();
    const banned = <String>[
      'seed phrase', 'mnemonic', 'private key',
      'spend key', 'view key', 'pin ', 'password',
      'bearer ', 'authorization',
      'api key', 'auth_token', 'session_token',
      'encrypted_data', 'pin_verifier',
    ];
    for (final b in banned) {
      if (low.contains(b)) return true;
    }
    return false;
  }

  String _sanitizePreview(String raw) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) return '';
    final firstLine = trimmed.split('\n').first;
    final capped = firstLine.length > 60
        ? '${firstLine.substring(0, 60)}…'
        : firstLine;
    if (_looksSensitive(capped)) return '';
    return capped;
  }


  void onUserSendClicked(String rawUserMessage) {
    _sentAt = nowClock();
    final preview = _sanitizePreview(rawUserMessage);
    value = ChatSendState(
      phase: ChatSendPhase.userBubbleShown,
      userMessagePreview: preview,
      elapsedMsSinceSend: 0,
    );
    PerfTrace.instance.recordRequest(kSpanChatSendClicked);
  }


  void onAssistantThinking() {
    if (_sentAt == null) return;
    final now = nowClock();
    value = value.copyWith(
      phase: ChatSendPhase.thinking,
      elapsedMsSinceSend: now.difference(_sentAt!).inMilliseconds,
    );
  }


  void onAssistantFirstResponse() {
    if (_sentAt == null) return;
    final now = nowClock();
    value = value.copyWith(
      phase: ChatSendPhase.streaming,
      elapsedMsSinceSend: now.difference(_sentAt!).inMilliseconds,
    );
    PerfTrace.instance.recordRequest(
      kSpanChatFirstAssistantResponse,
    );
  }


  void onAssistantDone() {
    if (_sentAt == null) return;
    final now = nowClock();
    value = value.copyWith(
      phase: ChatSendPhase.done,
      elapsedMsSinceSend: now.difference(_sentAt!).inMilliseconds,
    );
    PerfTrace.instance.recordRequest(kSpanChatTotalResponse);
  }


  void onAssistantError(String? errorCode) {
    final now = nowClock();
    value = value.copyWith(
      phase: ChatSendPhase.error,
      elapsedMsSinceSend: _sentAt == null
          ? null
          : now.difference(_sentAt!).inMilliseconds,
      errorCode: errorCode,
    );
  }


  void reset() {
    _sentAt = null;
    value = ChatSendState.idle;
  }

  int? elapsedMsSinceSend() {
    final at = _sentAt;
    if (at == null) return null;
    return nowClock().difference(at).inMilliseconds;
  }
}
