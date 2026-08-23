import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('vault deletion clearly preserves Apple subscription management', () {
    final source = File('lib/delete_vault_flow.dart').readAsStringSync();

    expect(source, contains('Deleting this vault does not cancel it.'));
    expect(source, contains('Manage Apple subscription'));
    expect(
      source,
      contains('https://apps.apple.com/account/subscriptions'),
    );
  });

  test('help center does not claim vault deletion closes subscriptions', () {
    final source =
        File('lib/help_center_content_i18n.dart').readAsStringSync();

    expect(source, isNot(contains('Any active storage subscription is closed.')));
    expect(
      source,
      contains('App Store subscriptions are managed separately by Apple'),
    );
  });
}
