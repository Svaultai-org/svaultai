import 'dart:async';

import '../../services/chat_protocol_contracts.dart';

enum ChatRequestState { pending, completed, cancelled }

class ChatRequestTicket {
  final String requestId;
  final String userMessageId;
  final String assistantMessageId;
  ChatRequestState state;

  ChatRequestTicket({
    required this.requestId,
    required this.userMessageId,
    required this.assistantMessageId,
    this.state = ChatRequestState.pending,
  });
}

/// Owns immutable request/message identities and rejects stale callbacks.
class ChatRequestCoordinator {
  int _sequence = 0;
  final Map<String, ChatRequestTicket> _tickets = {};

  ChatRequestTicket begin({int? nowMicros}) {
    final requestId =
        'chat_${nowMicros ?? DateTime.now().microsecondsSinceEpoch}_${++_sequence}';
    final ticket = ChatRequestTicket(
      requestId: requestId,
      userMessageId: 'user_$requestId',
      assistantMessageId: 'assistant_$requestId',
    );
    _tickets[requestId] = ticket;
    return ticket;
  }

  ChatRequestTicket retry(String previousRequestId, {int? nowMicros}) {
    cancel(previousRequestId);
    return begin(nowMicros: nowMicros);
  }

  bool acceptsEvents(String requestId) =>
      _tickets[requestId]?.state == ChatRequestState.pending;

  void complete(String requestId) {
    final ticket = _tickets[requestId];
    if (ticket?.state == ChatRequestState.pending) {
      ticket!.state = ChatRequestState.completed;
    }
  }

  void cancel(String requestId) {
    final ticket = _tickets[requestId];
    if (ticket != null) ticket.state = ChatRequestState.cancelled;
  }
}

/// Testable owner for the request registry and active stream lifecycle.
/// It deliberately contains no protocol, crypto, or UI behavior.
class ChatRequestRuntime implements ChatRequestCancellation {
  final ChatRequestCoordinator coordinator;
  Object? _activeIterator;
  String? _activeRequestId;

  ChatRequestRuntime({ChatRequestCoordinator? coordinator})
      : coordinator = coordinator ?? ChatRequestCoordinator();

  ChatRequestTicket begin({int? nowMicros}) =>
      coordinator.begin(nowMicros: nowMicros);
  ChatRequestTicket retry(String id, {int? nowMicros}) =>
      coordinator.retry(id, nowMicros: nowMicros);
  bool acceptsEvents(String id) => coordinator.acceptsEvents(id);
  @override
  bool accepts(String id) => coordinator.acceptsEvents(id);
  void complete(String id) => coordinator.complete(id);
  @override
  void cancel(String id) => coordinator.cancel(id);

  bool get hasActiveIterator => _activeIterator != null;
  String? get activeRequestId => _activeRequestId;
  Object? get activeIterator => _activeIterator;
  void assignIterator(String requestId, Object iterator) {
    _activeRequestId = requestId;
    _activeIterator = iterator;
  }

  T? takeIterator<T>() {
    final value = _activeIterator;
    _activeIterator = null;
    _activeRequestId = null;
    return value is T ? value : null;
  }

  void clearIterator() {
    _activeIterator = null;
    _activeRequestId = null;
  }

  Future<void> cancelActiveIterator() async {
    final value = _activeIterator;
    clearIterator();
    if (value is StreamIterator<String>) await value.cancel();
  }
}
