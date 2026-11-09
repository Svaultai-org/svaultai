import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

void main() {
  String signedChatToken({int bits = 519}) => base64Url
      .encode(<int>[4, (bits >> 8) & 255, bits & 255,
        ...List<int>.filled(48, 7)])
      .replaceAll('=', '');

  test('chat offer is off until complete local readers are integrated', () {
    expect(kSignedPrivateChatClientEnabled, isFalse);
    expect(kSignedPrivateChatLocalReadersReady, isFalse);
  });

  test('client requires the exact v4 chat offer and complete read bits', () {
    final token = signedChatToken();
    final response = <String, dynamic>{
      'session_token': token,
      'pin_free_read_offers_signed': true,
      'pin_free_private_chat_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
    };
    expect(signedOfferTokenMatches(response, requirePrivateChatOffer: true),
        isTrue);
    expect(signedOfferTokenMatches(response), isFalse);
    response['session_token'] = signedChatToken(bits: 518);
    expect(signedOfferTokenMatches(response, requirePrivateChatOffer: true),
        isFalse);
    response['session_token'] = token;
    response['pin_free_private_chat_signed'] = false;
    expect(signedOfferTokenMatches(response, requirePrivateChatOffer: true),
        isFalse);
  });

  test('issued chat offer fences old chat before transport even without PIN',
      () async {
    final token = signedChatToken();
    final headers = <String, String>{'Authorization': 'Bearer $token'};
    expect(signedPrivateChatOfferedForToken(token), isTrue);
    for (final path in <String>[
      '/chat', '/chat/', '/vault-analysis/deep-answer',
      '/vault-analysis/deep-answer/job/poll',
      '/vault-analysis/deep-answer/job/debug',
      '/files/file-id/related',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'), headers,
          body: '{"pin":"synthetic-marker"}',
        ),
        throwsStateError,
      );
    }
    expect(
      () => assertOfferedReadPinFreeRequest(
        Uri.parse('https://synthetic.example/chat'), headers, body: '{}'),
      throwsStateError,
    );
    assertOfferedReadPinFreeRequest(
      Uri.parse('https://synthetic.example/update-secure-item'), headers,
      body: '{"pin":"synthetic-marker"}');

    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.chatStream(
        encryptedMessage: 'synthetic-ciphertext',
        vaultName: 'synthetic-vault',
        pin: 'synthetic-marker',
        authToken: token,
      ),
      emitsError(isA<StateError>()),
    );
    await expectLater(
      client.startDeepAnswer(pin: 'synthetic-marker', authToken: token),
      throwsA(isA<Exception>()),
    );
    expect(sent, isEmpty);
  });
}
