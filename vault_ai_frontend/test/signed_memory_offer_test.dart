import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

void main() {
  String token(int bits) => base64UrlEncode(<int>[
        4, bits >> 8, bits & 255, ...List<int>.filled(48, 7),
      ]);

  test('Memory offer requires exact signed wide bearer and server readiness', () {
    final ready = <String, dynamic>{
      'session_token': token(1024),
      'pin_free_read_offers_signed': true,
      'pin_free_memory_signed': true,
      'pin_free_memory_v2': true,
      'pin_free_legacy_item_read': false,
      'pin_free_legacy_file_list': false,
      'pin_free_legacy_file_download': false,
    };
    expect(signedOfferTokenMatches(ready, requireMemoryOffer: true), isTrue);
    expect(signedOfferTokenMatches(ready), isFalse);
    expect(signedOfferTokenMatches({...ready, 'session_token': token(512)},
        requireMemoryOffer: true), isFalse);
    final oldVault = <String, dynamic>{
      ...ready,
      'session_token': base64UrlEncode(<int>[
        3, 0, ...List<int>.filled(48, 7),
      ]),
      'pin_free_memory_v2': false,
    };
    expect(signedOfferTokenMatches(oldVault, requireMemoryOffer: true), isTrue);
    final allOffers = <String, dynamic>{
      ...ready,
      'session_token': token(2047),
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
      'pin_free_v2_file_upload': true,
      'pin_free_file_create_signed': true,
      'pin_free_file_mutation_signed': true,
      'pin_free_password_analysis_signed': true,
      'pin_free_beneficiary_signed': true,
      'pin_free_beneficiary_v2': true,
      'pin_free_auth_device_signed': true,
      'pin_free_import_signed': true,
      'pin_free_private_chat_signed': true,
    };
    expect(signedOfferTokenMatches(
      allOffers,
      requireFileCreateOffer: true,
      requireFileMutationOffer: true,
      requirePrivateChatOffer: true,
      requirePasswordAnalysisOffer: true,
      requireBeneficiaryOffer: true,
      requireAuthDeviceOffer: true,
      requireImportOffer: true,
      requireMemoryOffer: true,
    ), isTrue);
  });

  test('offered Memory session blocks legacy PIN body before transport', () {
    final offered = token(1024);
    for (final path in <String>[
      '/memory/list', '/memory/create', '/memory/update', '/memory/delete',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://example.invalid$path'),
          {'Authorization': 'Bearer $offered', 'Content-Type': 'application/json'},
          body: jsonEncode({'pin': 'synthetic-pin'}),
        ),
        throwsStateError,
      );
    }
  });
}
