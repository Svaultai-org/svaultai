import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final apiSource = File('lib/api_client.dart').readAsStringSync();
  final storageSource = File('lib/storage_page.dart').readAsStringSync();

  test('checkout API allowlists product messages and hides Stripe internals',
      () {
    expect(apiSource, contains('class BillingCheckoutException'));
    expect(apiSource, contains('_safeBillingCheckoutError(response.body)'));
    expect(apiSource, contains("'downgrade_not_supported'"));
    expect(apiSource, contains("'enterprise_required'"));
    expect(
      apiSource,
      contains("We couldn't start checkout. Please try again."),
    );

    final helperStart = apiSource.indexOf(
      'BillingCheckoutException _safeBillingCheckoutError',
    );
    expect(helperStart, greaterThan(-1));
    final helperEnd = apiSource.indexOf(
      'Future<Map<String, dynamic>> createStripePortalSession',
      helperStart,
    );
    expect(helperEnd, greaterThan(helperStart));
    final helper = apiSource.substring(helperStart, helperEnd);
    expect(helper, isNot(contains('stripe_message')));
    expect(helper, isNot(contains('stripe_type')));
    expect(helper, isNot(contains('stripe_param')));
    expect(helper, isNot(contains('request_id')));
  });

  test('storage dialog receives only the sanitized checkout message', () {
    expect(storageSource, contains('_friendlyCheckoutErrorMessage(e)'));
    expect(
      storageSource,
      isNot(contains('_UpgradeErrorDialog(message: e.toString())')),
    );
    expect(
      storageSource,
      contains("We couldn't start checkout. Please try again."),
    );
  });
}
