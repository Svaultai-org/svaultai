// Non-UI contracts for the authenticated chat protocol. These types carry
// protocol outcomes only; presentation and persistence remain application
// responsibilities.

sealed class ChatProtocolEvent {
  const ChatProtocolEvent();
}

enum ChatProtocolFailureCategory {
  cryptoContextUnavailable,
  cryptoContextMismatch,
  encryptionFailed,
  transportFailed,
  streamFailed,
  decryptFailed,
  protocolMalformed,
}

/// Safe, non-UI classification for failures at the shared protocol boundary.
/// It intentionally carries no exception text, credentials, or key material.
class ChatProtocolFailureInfo {
  final ChatProtocolFailureCategory category;
  final int? httpStatus;
  final String? backendCode;
  final String? requestId;

  const ChatProtocolFailureInfo({
    required this.category,
    this.httpStatus,
    this.backendCode,
    this.requestId,
  });
}

ChatProtocolFailureInfo classifyProtocolFailure(
  ChatProtocolFailureCategory category, {
  int? httpStatus,
  String? backendCode,
  String? requestId,
}) =>
    ChatProtocolFailureInfo(
      category: category,
      httpStatus: httpStatus,
      backendCode: backendCode,
      requestId: requestId,
    );

class ChatDecryptedChunk extends ChatProtocolEvent {
  final String text;
  const ChatDecryptedChunk(this.text);
}

class ChatMemoryProposal extends ChatProtocolEvent {
  final String jsonPayload;
  const ChatMemoryProposal(this.jsonPayload);
}

class ChatProtocolCompleted extends ChatProtocolEvent {
  const ChatProtocolCompleted();
}

class ChatProtocolCancelled extends ChatProtocolEvent {
  const ChatProtocolCancelled();
}

class ChatProtocolFailure extends ChatProtocolEvent {
  final Object error;
  final ChatProtocolFailureInfo? info;
  const ChatProtocolFailure(this.error, {this.info});
}

abstract interface class ChatRequestCancellation {
  bool accepts(String requestId);
  void cancel(String requestId);
}

class MemoryProposalStripResult {
  final String strippedBuffer;
  final String? jsonPayload;
  const MemoryProposalStripResult({
    required this.strippedBuffer,
    required this.jsonPayload,
  });
}

const String kMemoryProposalOpen = '<<VAULTAI_MEMORY_PROPOSAL>>';
const String kMemoryProposalClose = '<<END>>';

MemoryProposalStripResult extractAndStripMemoryProposal({
  required String buffer,
  required bool alreadyFinalized,
}) {
  final openIdx = buffer.indexOf(kMemoryProposalOpen);
  if (openIdx < 0) {
    return MemoryProposalStripResult(strippedBuffer: buffer, jsonPayload: null);
  }
  final closeIdx = buffer.indexOf(
    kMemoryProposalClose,
    openIdx + kMemoryProposalOpen.length,
  );
  if (closeIdx < 0) {
    return MemoryProposalStripResult(
      strippedBuffer: buffer.substring(0, openIdx),
      jsonPayload: null,
    );
  }
  final jsonStart = openIdx + kMemoryProposalOpen.length;
  final jsonPayload = buffer.substring(jsonStart, closeIdx);
  final afterClose = closeIdx + kMemoryProposalClose.length;
  final tail =
      buffer.substring(afterClose).replaceFirst(RegExp(r'^\r?\n\r?\n'), '');
  return MemoryProposalStripResult(
    strippedBuffer: buffer.substring(0, openIdx) + tail,
    jsonPayload: alreadyFinalized ? null : jsonPayload,
  );
}
