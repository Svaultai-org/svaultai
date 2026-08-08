import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/chat_protocol_contracts.dart';

void main() {
  test('typed failure boundary preserves safe protocol distinctions', () {
    final categories = ChatProtocolFailureCategory.values;
    expect(categories,
        contains(ChatProtocolFailureCategory.cryptoContextMismatch));
    final failure = classifyProtocolFailure(
      ChatProtocolFailureCategory.transportFailed,
      httpStatus: 503,
      backendCode: 'provider_unavailable',
      requestId: 'chat_test',
    );
    expect(failure.httpStatus, 503);
    expect(failure.backendCode, 'provider_unavailable');
    expect(failure.requestId, 'chat_test');
    expect(failure.toString(), isNot(contains('secret')));
  });

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
    expect(
        extractAndStripMemoryProposal(
          buffer: 'before<<VAULTAI_MEMORY_PROPOSAL>>{"x":1}<<END>>',
          alreadyFinalized: true,
        ).jsonPayload,
        isNull);
  });
}
