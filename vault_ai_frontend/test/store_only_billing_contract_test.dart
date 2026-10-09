import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';

void main() {
  const client = VaultAIClient(baseUrl: 'https://api.example.invalid');

  test('Apple verifier posts the signed transaction to the server contract',
      () async {
    final mock = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/billing/apple/verify-transaction');
      expect(request.headers['Authorization'], 'Bearer test-session');
      expect(jsonDecode(request.body), {'signed_transaction': 'signed-jws'});
      return http.Response(jsonEncode({'verified': true}), 200);
    });
    final result = await http.runWithClient(
      () => client.verifyAppleStoragePurchase(
        authToken: 'test-session',
        signedTransaction: 'signed-jws',
      ),
      () => mock,
    );
    expect(result['verified'], isTrue);
  });

  test('Apple verification never treats a rejected transaction as verified',
      () async {
    final mock = MockClient((_) async => http.Response(
          jsonEncode({
            'detail': {'code': 'apple_transaction_invalid'}
          }),
          400,
        ));
    await expectLater(
      http.runWithClient(
        () => client.verifyAppleStoragePurchase(
          authToken: 'test-session',
          signedTransaction: 'invalid-jws',
        ),
        () => mock,
      ),
      throwsException,
    );
  });

  test('authenticated provider catalog returns the opaque Apple binding token',
      () async {
    final mock = MockClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/billing/providers');
      expect(request.headers['Authorization'], 'Bearer test-session');
      return http.Response(
          jsonEncode({
            'apple': {'app_account_token': 'opaque-store-token'},
            'google_play': {
              'product_ids': ['svaultai_storage_50gb']
            },
          }),
          200);
    });
    final result = await http.runWithClient(
      () => client.getBillingProviders(authToken: 'test-session'),
      () => mock,
    );
    expect((result['apple'] as Map)['app_account_token'], 'opaque-store-token');
  });

  test('payment integrations expose store verification without card endpoints',
      () {
    final api = File('lib/api_client.dart').readAsStringSync();
    final storage = File('lib/storage_page.dart').readAsStringSync();
    for (final retired in [
      'createStripeCheckoutSession',
      'createStripePortalSession',
      '/billing/checkout-session',
      '/billing/portal-session',
      'buildCheckoutRedirectUrl',
      'buildPortalReturnUrl',
      '_runPostCheckoutPoll',
      '_checkoutBanner',
    ]) {
      expect(api + storage, isNot(contains(retired)));
    }
    expect(storage, contains("apple['app_account_token']"));
    expect(storage, contains('appAccountToken: appAccountToken'));
    expect(storage, isNot(contains('accountId: accountId')));
    expect(storage, contains('onBuyStorage: supportsAppleIap'));
    expect(storage, contains('https://apps.apple.com/account/subscriptions'));
    expect(storage,
        contains('https://play.google.com/store/account/subscriptions'));
  });
}
