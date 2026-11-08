import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

void main() {
  final token = base64Url.encode(<int>[
    4, 1, 7, ...List<int>.filled(48, 7),
  ]).replaceAll('=', ''); // v4, signed import plus three read offers.
  final headers = <String, String>{'Authorization': 'Bearer $token'};

  test('client accepts exact signed import offer and rejects absent offer', () {
    final response = <String, dynamic>{
      'session_token': token,
      'pin_free_read_offers_signed': true,
      'pin_free_import_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
    };
    expect(signedOfferTokenMatches(response, requireImportOffer: true), isTrue);
    expect(signedOfferTokenMatches(response), isFalse);
    expect(signedImportOfferedForToken(token), isTrue);
    response['session_token'] = base64Url.encode(<int>[
      4, 1, 6, ...List<int>.filled(48, 7),
    ]).replaceAll('=', '');
    expect(signedOfferTokenMatches(response, requireImportOffer: true), isFalse);
    // An import-capable session may have old saved items/files that prevent
    // separate read offers. It must still be able to log in and use imports.
    response['session_token'] = base64Url.encode(<int>[
      4, 1, 0, ...List<int>.filled(48, 7),
    ]).replaceAll('=', '');
    response['pin_free_legacy_item_read'] = false;
    response['pin_free_legacy_file_list'] = false;
    response['pin_free_legacy_file_download'] = false;
    expect(signedOfferTokenMatches(response, requireImportOffer: true), isTrue);
  });

  test('combined auth, import and chat offer keeps all three capabilities', () {
    final combined = base64Url.encode(<int>[
      4, 3, 135, ...List<int>.filled(48, 7),
    ]).replaceAll('=', ''); // 128 + 256 + 512 + 7.
    final response = <String, dynamic>{
      'session_token': combined,
      'pin_free_read_offers_signed': true,
      'pin_free_auth_device_signed': true,
      'pin_free_import_signed': true,
      'pin_free_private_chat_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
    };
    expect(signedOfferTokenMatches(response,
        requireAuthDeviceOffer: true, requireImportOffer: true,
        requirePrivateChatOffer: true), isTrue);
    expect(signedAuthDeviceOfferedForToken(combined), isTrue);
    expect(signedImportOfferedForToken(combined), isTrue);
    expect(signedPrivateChatOfferedForToken(combined), isTrue);
  });

  test('offered old imports stop before transport, even with empty body',
      () async {
    for (final path in <String>[
      '/imports/start', '/imports/id/cancel', '/imports/id/complete',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'), headers, body: '{}',
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
      client.startImport(vaultName: 'private', pin: '123456',
          authToken: token),
      throwsA(isA<StateError>()),
    );
    await expectLater(
      client.cancelImport(vaultName: 'private', pin: '123456',
          authToken: token, importId: 'id'),
      throwsA(isA<StateError>()),
    );
    await expectLater(
      client.completeImport(vaultName: 'private', pin: '123456',
          authToken: token, importId: 'id'),
      throwsA(isA<StateError>()),
    );
    expect(sent, isEmpty);
  });

  test('offered import session actions send no PIN or vault name', () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{"import_id":"id"}', 200);
      }),
    );
    await client.startImport(vaultName: 'private', pin: null,
        authToken: token, zkSessionOnly: true, totalFiles: 2);
    await client.cancelImport(vaultName: 'private', pin: null,
        authToken: token, importId: 'id', zkSessionOnly: true);
    await client.completeImport(vaultName: 'private', pin: null,
        authToken: token, importId: 'id', zkSessionOnly: true);
    expect(sent.map((r) => r.url.path), <String>[
      '/imports/session/start', '/imports/session/id/cancel',
      '/imports/session/id/complete',
    ]);
    for (final request in sent) {
      expect(jsonDecode(request.body), isNot(containsPair('pin', anything)));
      expect(jsonDecode(request.body),
          isNot(containsPair('vault_name', anything)));
    }
  });
}
