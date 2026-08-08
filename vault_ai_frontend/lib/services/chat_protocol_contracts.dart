// Non-UI contracts for the authenticated chat protocol. These types carry
// protocol outcomes only; presentation and persistence remain application
// responsibilities.

sealed class ChatProtocolEvent {
  const ChatProtocolEvent();
}

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
  const ChatProtocolFailure(this.error);
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
  final tail = buffer
      .substring(afterClose)
      .replaceFirst(RegExp(r'^\r?\n\r?\n'), '');
  return MemoryProposalStripResult(
    strippedBuffer: buffer.substring(0, openIdx) + tail,
    jsonPayload: alreadyFinalized ? null : jsonPayload,
  );
}
