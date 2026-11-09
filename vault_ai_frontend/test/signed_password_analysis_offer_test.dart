import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

String _signedToken(int bits) => base64Url
    .encode(<int>[3, bits, ...List<int>.filled(48, 7)])
    .replaceAll('=', '');

String _signedChatToken(int bits) => base64Url
    .encode(<int>[4, (bits >> 8) & 255, bits & 255,
      ...List<int>.filled(48, 7)])
    .replaceAll('=', '');

void main() {
  tearDown(ZkActiveMvk.clear);

  test('password-analysis offer is opt in until the server is ready', () {
    expect(kSignedPasswordAnalysisClientEnabled, isFalse);
  });

  test('client requires exact signed password-analysis capability', () {
    final response = <String, dynamic>{
      'session_token': _signedToken(23),
      'pin_free_read_offers_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
      'pin_free_password_analysis_signed': true,
    };
    expect(
      signedOfferTokenMatches(
        response,
        requirePasswordAnalysisOffer: true,
      ),
      isTrue,
    );
    expect(signedOfferTokenMatches(response), isFalse);

    response['session_token'] = _signedToken(7);
    expect(
      signedOfferTokenMatches(
        response,
        requirePasswordAnalysisOffer: true,
      ),
      isFalse,
    );
    response['session_token'] = _signedToken(23);
    response['pin_free_password_analysis_signed'] = false;
    expect(
      signedOfferTokenMatches(
        response,
        requirePasswordAnalysisOffer: true,
      ),
      isFalse,
    );
  });

  test('signed analyzer offer rejects a raw PIN before HTTP send', () async {
    final token = _signedToken(23);
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    expect(signedPasswordAnalysisOfferedForToken(token), isTrue);
    await expectLater(
      client.analyzePasswords(
        authToken: token,
        vaultName: 'Synthetic vault',
        pin: '7319462085',
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
  });

  test('unoffered active OPAQUE key also rejects server PIN analysis', () async {
    final sent = <http.Request>[];
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 17)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-handle',
    );
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.analyzePasswords(
        authToken: 'unsigned-synthetic-token',
        vaultName: 'Synthetic vault',
        pin: '7319462085',
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
  });

  test('read-only offer alone does not claim local analyzer support', () {
    expect(signedPasswordAnalysisOfferedForToken(_signedToken(7)), isFalse);
  });

  test('combined private-chat and analyzer offer keeps both signed bits', () {
    final token = _signedChatToken(535);
    final response = <String, dynamic>{
      'session_token': token,
      'pin_free_read_offers_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
      'pin_free_private_chat_signed': true,
      'pin_free_password_analysis_signed': true,
    };
    expect(
      signedOfferTokenMatches(
        response,
        requirePrivateChatOffer: true,
        requirePasswordAnalysisOffer: true,
      ),
      isTrue,
    );
    expect(signedPasswordAnalysisOfferedForToken(token), isTrue);
  });
}
