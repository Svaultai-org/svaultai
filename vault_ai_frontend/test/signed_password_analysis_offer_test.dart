import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

String _signedToken(int bits) => base64Url
    .encode(<int>[3, bits, ...List<int>.filled(48, 7)])
    .replaceAll('=', '');

void main() {
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
}
