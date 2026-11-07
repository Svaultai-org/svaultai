import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

String _signedToken(int bits) => base64Url
    .encode(bits > 255
        ? <int>[4, (bits >> 8) & 255, bits & 255, ...List<int>.filled(48, 7)]
        : <int>[3, bits, ...List<int>.filled(48, 7)])
    .replaceAll('=', '');

Map<String, dynamic> _response(
  String token, {
  bool chat = false,
  bool passwordAnalysis = false,
  bool beneficiaryReady = true,
  bool reads = true,
}) =>
    <String, dynamic>{
      'session_token': token,
      'pin_free_read_offers_signed': true,
      'pin_free_legacy_item_read': reads,
      'pin_free_legacy_file_list': reads,
      'pin_free_legacy_file_download': reads,
      'pin_free_private_chat_signed': chat,
      'pin_free_password_analysis_signed': passwordAnalysis,
      'pin_free_beneficiary_signed': true,
      'pin_free_beneficiary_v2': beneficiaryReady,
    };

void main() {
  test('beneficiary offer is disabled in the default build', () {
    expect(kSignedBeneficiaryClientEnabled, isFalse);
  }, skip: kSignedBeneficiaryClientEnabled);

  test('beneficiary offer is exact in v3/v4 combinations', () {
    expect(hasSignedBeneficiaryOffer(_signedToken(64)), isTrue);
    expect(
        signedOfferTokenMatches(
          _response(_signedToken(64), reads: false),
          requireBeneficiaryOffer: true,
        ),
        isTrue);
    final v3 = _signedToken(7 | 16 | 64);
    expect(hasSignedBeneficiaryOffer(v3), isTrue);
    final unrequested = _response(_signedToken(7));
    unrequested['pin_free_beneficiary_signed'] = false;
    expect(signedOfferTokenMatches(unrequested), isFalse);
    expect(
        signedOfferTokenMatches(
          _response(v3, passwordAnalysis: true),
          requirePasswordAnalysisOffer: true,
          requireBeneficiaryOffer: true,
        ),
        isTrue);
    expect(
        signedOfferTokenMatches(
          _response(_signedToken(7 | 16), passwordAnalysis: true),
          requirePasswordAnalysisOffer: true,
          requireBeneficiaryOffer: true,
        ),
        isFalse);
    expect(
        signedOfferTokenMatches(
          _response(v3, passwordAnalysis: true),
          requireBeneficiaryOffer: true,
        ),
        isFalse);
    final v4 = _signedToken(519 | 16 | 64);
    expect(hasSignedBeneficiaryOffer(v4), isTrue);
    expect(
        signedOfferTokenMatches(
          _response(v4, chat: true, passwordAnalysis: true),
          requirePrivateChatOffer: true,
          requirePasswordAnalysisOffer: true,
          requireBeneficiaryOffer: true,
        ),
        isTrue);
    expect(
        signedOfferTokenMatches(
          _response(_signedToken(519 | 16), chat: true, passwordAnalysis: true),
          requirePrivateChatOffer: true,
          requirePasswordAnalysisOffer: true,
          requireBeneficiaryOffer: true,
        ),
        isFalse);
    expect(hasSignedBeneficiaryOffer(_signedToken(519 | 16)), isFalse);
    expect(
        signedOfferTokenMatches(
          _response(_signedToken(7 | 16),
              passwordAnalysis: true, beneficiaryReady: false),
          requirePasswordAnalysisOffer: true,
          requireBeneficiaryOffer: true,
        ),
        isTrue);
  });

  test('offered legacy beneficiary PIN actions never reach HTTP transport',
      () async {
    final token = _signedToken(7 | 64);
    final headers = {'Authorization': 'Bearer $token'};
    for (final path in [
      '/beneficiary/create',
      '/beneficiary/link',
      '/beneficiary/claim-transfer',
      '/beneficiary/create/',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          headers,
          body: '{"pin":"synthetic-marker"}',
        ),
        throwsStateError,
      );
    }
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.createBeneficiary(
        vaultName: 'synthetic',
        pin: 'synthetic-marker',
        label: 'Person',
        authToken: token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.linkBeneficiary(
        vaultName: 'synthetic',
        pin: 'synthetic-marker',
        pairingCode: 'synthetic-code',
        authToken: token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.claimTransfer(
        linkId: 1,
        vaultName: 'synthetic',
        pin: 'synthetic-marker',
        authToken: token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.listBeneficiaries(
        vaultName: 'synthetic',
        pin: 'synthetic-marker',
        authToken: token,
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
  });

  test('private V2 pairing sends ciphertext and proof without PIN', () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    final token = _signedToken(7 | 64);
    await client.createZkBeneficiary(
      passerLabelCiphertext: 'synthetic-ciphertext',
      zkProofToken: 'synthetic-proof',
      authToken: token,
    );
    await client.linkZkBeneficiary(
      pairingCode: 'synthetic-code',
      zkProofToken: 'synthetic-proof',
      authToken: token,
    );
    expect(sent.map((r) => r.url.path),
        ['/beneficiary/zk-create', '/beneficiary/zk-link']);
    for (final request in sent) {
      expect(request.body, isNot(contains('"pin"')));
      expect(request.body, isNot(contains('vault_name')));
      expect(jsonDecode(request.body)['zk_proof_token'], 'synthetic-proof');
    }
  });
}
