import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart';

void main() {
  test('parses a generated-login draft without UI widgets', () {
    final card = VaultChatCard.fromJson({
      'cardType': kVcrCardGeneratedLogin,
      'data': {
        'view': 'create_draft',
        'draft_id': 'draft-qa-1',
        'service': 'Example',
        'username': 'synthetic-user',
        'password': 'synthetic-password',
        'expires_at': 2000000000,
      },
    });
    final parsed = GeneratedLoginPayload.tryParse(card);
    expect(parsed, isNotNull);
    expect(parsed!.draftId, 'draft-qa-1');
    expect(parsed.service, 'Example');
    expect(parsed.username, 'synthetic-user');
    expect(parsed.password, 'synthetic-password');
  });

  test('rejects unrelated and malformed cards', () {
    expect(GeneratedLoginPayload.tryParse(
      VaultChatCard.fromJson({'cardType': 'unknown', 'data': {}}),
    ), isNull);
    expect(GeneratedLoginPayload.tryParse(
      VaultChatCard.fromJson({
        'cardType': kVcrCardGeneratedLogin,
        'data': {'view': 'create_draft', 'service': 'Missing ID'},
      }),
    ), isNull);
  });
}
