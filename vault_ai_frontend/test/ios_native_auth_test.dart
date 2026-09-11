import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final loader =
      File('lib/services/opaque_client_native.dart').readAsStringSync();
  final podfile = File('ios/Podfile').readAsStringSync();
  final podspec =
      File('native/opaque_client/ios/VaultAIOpaque.podspec').readAsStringSync();
  final buildScript =
      File('native/opaque_client/build-ios.sh').readAsStringSync();
  final debugConfig = File('ios/Flutter/Debug.xcconfig').readAsStringSync();
  final releaseConfig = File('ios/Flutter/Release.xcconfig').readAsStringSync();

  const ffiSymbols = <String>[
    'vaultai_opaque_client_start_registration',
    'vaultai_opaque_client_finish_registration',
    'vaultai_opaque_client_start_login',
    'vaultai_opaque_client_finish_login',
    'vaultai_opaque_client_free_string',
    'vaultai_pbkdf2_hmac_sha256',
  ];

  test('iOS resolves statically linked native symbols from process image', () {
    expect(loader, contains('Platform.isIOS'));
    expect(loader, contains('DynamicLibrary.process()'));
    expect(
        loader, contains("DynamicLibrary.open('libvaultai_opaque_client.so')"));
    expect(
      File('ios/Runner/AppDelegate.swift').readAsStringSync(),
      contains('vaultai_opaque_client_link_anchor()'),
    );
  });

  test('CocoaPods links the generated XCFramework', () {
    expect(podfile, contains("pod 'VaultAIOpaque'"));
    expect(podspec,
        contains("s.vendored_frameworks = 'VaultAIOpaque.xcframework'"));
  });

  test('all dynamically resolved FFI symbols are retained by the iOS linker',
      () {
    for (final symbol in ffiSymbols) {
      expect(debugConfig, contains('-Wl,-u,_$symbol'));
      expect(releaseConfig, contains('-Wl,-u,_$symbol'));
      expect(debugConfig, contains('-Wl,-exported_symbol,_$symbol'));
      expect(releaseConfig, contains('-Wl,-exported_symbol,_$symbol'));
    }
    expect(releaseConfig, contains('STRIP_INSTALLED_PRODUCT=NO'));
  });

  test('build script creates device and Apple Silicon simulator slices', () {
    expect(buildScript, contains('aarch64-apple-ios'));
    expect(buildScript, contains('aarch64-apple-ios-sim'));
    expect(buildScript, contains('x86_64-apple-ios'));
    expect(buildScript, contains('lipo -create'));
    expect(buildScript, contains('xcodebuild -create-xcframework'));
  });
}
