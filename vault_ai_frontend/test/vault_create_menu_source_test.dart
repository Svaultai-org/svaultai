import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('authenticated dashboard Create menu exposes only Login, File, Memory',
      () {
    final src = File('lib/main.dart').readAsStringSync();
    final menuStart = src.indexOf('key: const Key(\'vault_create_menu\')');
    expect(menuStart, greaterThanOrEqualTo(0));
    final menuEnd = src.indexOf('key: const Key(\'create_menu_cancel\')');
    expect(menuEnd, greaterThan(menuStart));
    final menu = src.substring(menuStart, menuEnd);

    expect(menu, contains("title: 'Login'"));
    expect(menu, contains("title: 'File'"));
    expect(menu, contains("title: 'Memory'"));
    expect(RegExp(r"create_choice_").allMatches(menu), hasLength(3));

    for (final forbidden in const [
      'Bank Account',
      'Payment Card',
      'API Key',
      'Passport',
      'Identity',
      'Medical Record',
      'Crypto Wallet',
      'Secure Note',
      'Insurance',
    ]) {
      expect(menu, isNot(contains("title: '$forbidden'")));
    }
  });
}
