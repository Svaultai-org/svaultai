import 'dart:async';

enum ChatOperationKind { read, mutation }

enum ChatOperationPhase { enqueued, started, terminalSuccess, terminalFailure }

class ChatOperationTrace {
  final String operationId;
  final ChatOperationKind kind;
  final ChatOperationPhase phase;
  final int timestampMicros;

  const ChatOperationTrace({
    required this.operationId,
    required this.kind,
    required this.phase,
    required this.timestampMicros,
  });
}

typedef ChatOperationTraceSink = void Function(ChatOperationTrace trace);

/// Strictly orders shared chat operations without inspecting their payloads.
///
/// A slot is reserved synchronously, before the caller's first asynchronous
/// gap. This prevents a card/quick-prompt mutation from being overtaken by a
/// dependent lookup. The next slot starts only after the preceding operation
/// reaches authoritative success or failure.
class ChatOperationQueue {
  Future<void> _tail = Future<void>.value();
  int _sequence = 0;
  int _pendingCount = 0;
  int _pendingMutationCount = 0;

  final int Function() _nowMicros;
  final ChatOperationTraceSink? onTrace;

  ChatOperationQueue({int Function()? nowMicros, this.onTrace})
    : _nowMicros = nowMicros ?? (() => DateTime.now().microsecondsSinceEpoch);

  int get pendingCount => _pendingCount;
  bool get isBusy => _pendingCount != 0;
  bool get hasPendingMutation => _pendingMutationCount != 0;

  Future<void> get settled => _tail;

  Future<T> enqueue<T>({
    required ChatOperationKind kind,
    required Future<T> Function() operation,
  }) {
    final operationId = 'chatop_${_nowMicros()}_${++_sequence}';
    final predecessor = _tail;
    final terminal = Completer<void>();
    final result = Completer<T>();

    // Reserve the tail synchronously. A later caller will observe this
    // terminal future even if this operation has not started executing yet.
    _tail = terminal.future;
    _pendingCount++;
    if (kind == ChatOperationKind.mutation) _pendingMutationCount++;
    _emit(operationId, kind, ChatOperationPhase.enqueued);

    unawaited(() async {
      try {
        await predecessor;
        _emit(operationId, kind, ChatOperationPhase.started);
        final value = await operation();
        _emit(operationId, kind, ChatOperationPhase.terminalSuccess);
        result.complete(value);
      } catch (error, stackTrace) {
        _emit(operationId, kind, ChatOperationPhase.terminalFailure);
        result.completeError(error, stackTrace);
      } finally {
        _pendingCount--;
        if (kind == ChatOperationKind.mutation) _pendingMutationCount--;
        terminal.complete();
      }
    }());

    return result.future;
  }

  void _emit(
    String operationId,
    ChatOperationKind kind,
    ChatOperationPhase phase,
  ) {
    onTrace?.call(
      ChatOperationTrace(
        operationId: operationId,
        kind: kind,
        phase: phase,
        timestampMicros: _nowMicros(),
      ),
    );
  }
}

/// Conservative, data-independent classification for operations that can
/// change vault-visible state. It does not parse or expose credential values.
bool isAuthoritativeVaultMutationCommand(
  String text, {
  bool hasAttachments = false,
  bool hasPrivateBackendCommand = false,
}) {
  if (hasAttachments || hasPrivateBackendCommand) return true;
  final normalized = text.trim().toLowerCase();
  if (normalized.isEmpty) return false;

  if (RegExp(
    r'^(?:please\s+)?(?:save|store|remember|keep|upload|add|delete|remove|erase|forget)\b',
  ).hasMatch(normalized)) {
    return true;
  }
  if (RegExp(
    r'^(?:please\s+)?(?:edit|update|change|rename)\b.*\b(?:login|credential|password|username|memory|file|document)\b',
  ).hasMatch(normalized)) {
    return true;
  }
  return RegExp(
    r'^(?:yes[, ]+)?(?:save|store|delete|remove)\s+(?:it|this|that|them)(?:\s+now)?[.!?]*$',
  ).hasMatch(normalized);
}
