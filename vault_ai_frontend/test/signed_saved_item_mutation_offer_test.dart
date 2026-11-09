import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

void main() {
  String token(int bits) => base64UrlEncode(<int>[
    4,
    bits >> 8,
    bits & 255,
    ...List<int>.filled(48, 7),
  ]);

  test('item mutation needs its exact signed bit and readiness', () {
    final response = <String, dynamic>{
      'session_token': token(2049),
      'pin_free_read_offers_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': false,
      'pin_free_legacy_file_download': false,
      'pin_free_saved_item_mutation_signed': true,
      'pin_free_saved_item_mutation_ready': true,
    };
    expect(
      signedOfferTokenMatches(response, requireSavedItemMutationOffer: true),
      isTrue,
    );
    expect(signedOfferTokenMatches(response), isFalse);
    expect(
      signedOfferTokenMatches({
        ...response,
        'session_token': token(1),
      }, requireSavedItemMutationOffer: true),
      isFalse,
    );
    expect(signedSavedItemMutationOfferedForToken(token(2049)), isTrue);
    expect(signedSavedItemMutationOfferedForToken(token(1025)), isFalse);
    expect(hasSignedBeneficiaryOffer(token(2049)), isFalse);
  });

  test('offered item mutation never sends old PIN routes', () {
    final offered = token(2049);
    for (final path in <String>['/update-secure-item', '/delete-secure-item']) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://example.invalid$path'),
          {
            'Authorization': 'Bearer $offered',
            'Content-Type': 'application/json',
          },
          body: jsonEncode({'pin': 'synthetic-pin'}),
        ),
        throwsStateError,
      );
    }
  });
}
