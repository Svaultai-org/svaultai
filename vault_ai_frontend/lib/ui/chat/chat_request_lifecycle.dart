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
