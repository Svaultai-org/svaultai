import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/chat_protocol_contracts.dart';

void main() {
  test('represents decrypted, terminal, and failure events without UI', () {
    expect(ChatDecryptedChunk('safe').text, 'safe');
    expect(const ChatProtocolCompleted(), isA<ChatProtocolEvent>());
    expect(const ChatProtocolCancelled(), isA<ChatProtocolEvent>());
    expect(ChatProtocolFailure(StateError('x')), isA<ChatProtocolEvent>());
  });

  test('memory proposal stripping preserves sentinel semantics', () {
    final partial = extractAndStripMemoryProposal(
      buffer: 'before<<VAULTAI_MEMORY_PROPOSAL>>',
      alreadyFinalized: false,
    );
    expect(partial.strippedBuffer, 'before');
    expect(partial.jsonPayload, isNull);

    final complete = extractAndStripMemoryProposal(
      buffer: 'before<<VAULTAI_MEMORY_PROPOSAL>>{"x":1}<<END>>\n\nafter',
      alreadyFinalized: false,
    );
    expect(complete.strippedBuffer, 'beforeafter');
    expect(complete.jsonPayload, '{"x":1}');
    expect(extractAndStripMemoryProposal(
      buffer: 'before<<VAULTAI_MEMORY_PROPOSAL>>{"x":1}<<END>>',
      alreadyFinalized: true,
    ).jsonPayload, isNull);
  });
}
