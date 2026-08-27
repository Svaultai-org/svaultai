import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  const requiredSymbols = <String>[
    'vaultai_opaque_client_start_registration',
    'vaultai_opaque_client_finish_registration',
    'vaultai_opaque_client_start_login',
    'vaultai_opaque_client_finish_login',
    'vaultai_pbkdf2_hmac_sha256',
    'vaultai_opaque_client_free_string',
  ];

  test('Release links OPAQUE into the shipping executable', () {
    final release = File('ios/Flutter/Release.xcconfig').readAsStringSync();
    expect(release, contains('ENABLE_DEBUG_DYLIB = NO'));
    expect(release, contains('DEAD_CODE_STRIPPING = NO'));
    expect(release, contains('STRIP_INSTALLED_PRODUCT = NO'));
    expect(release, contains('-force_load'));
    expect(release, contains('-Wl,-export_dynamic'));
    expect(release, contains('VaultAIOpaque.xcframework/ios-arm64/'));
    for (final symbol in requiredSymbols) {
      expect(release, contains('-Wl,-u,_$symbol'));
      expect(release, contains('-Wl,-exported_symbol,_$symbol'));
    }
  });

  test('Dart iOS bridge resolves OPAQUE from the process without fallback', () {
    final bridge =
        File('lib/services/opaque_client_native.dart').readAsStringSync();
    expect(bridge, contains('DynamicLibrary.process()'));
    expect(bridge, isNot(contains('legacy authentication')));
    for (final symbol in requiredSymbols) {
      expect(bridge, contains("'$symbol'"));
    }
  });
}
