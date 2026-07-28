import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/route_guard.dart';

void main() {
  final mainSource = File('lib/main.dart').readAsStringSync();
  final zkSource = File('lib/services/zk_auth_service.dart').readAsStringSync();
  final nativeSource =
      File('lib/services/opaque_client_native.dart').readAsStringSync();
  final rustSource = File('native/opaque_client/src/lib.rs').readAsStringSync();
  final cargoSource =
      File('native/opaque_client/Cargo.toml').readAsStringSync();
  final buildScript =
      File('native/opaque_client/build-android.ps1').readAsStringSync();
  final gradleSource = File('android/app/build.gradle.kts').readAsStringSync();

  test('Android bypasses only the public marketing landing page', () {
    expect(
      shouldBypassPublicLandingForAuth(
        isWeb: false,
        platform: TargetPlatform.android,
      ),
      isTrue,
    );
    expect(
      shouldBypassPublicLandingForAuth(
        isWeb: true,
        platform: TargetPlatform.android,
      ),
      isFalse,
    );
    expect(
      shouldBypassPublicLandingForAuth(
        isWeb: false,
        platform: TargetPlatform.iOS,
      ),
      isFalse,
    );
    expect(mainSource, contains("pushReplacementNamed('/login')"));
    expect(
      mainSource,
      contains("lockedRoute: shouldBypassPublicLandingForAuth() ? '/unlock'"),
    );
    expect(
      resolveLandingRedirect(
        authed: true,
        unlocked: false,
        lockedRoute: '/unlock',
      ),
      '/unlock',
    );
  });

  test('native Android auth imports the FFI OPAQUE client, not the stub', () {
    expect(
      mainSource,
      contains(
        "import 'services/opaque_client.dart'\n"
        "    if (dart.library.io) 'services/opaque_client_native.dart';",
      ),
    );
    expect(
      zkSource,
      contains(
        "import 'opaque_client.dart' if (dart.library.io) "
        "'opaque_client_native.dart';",
      ),
    );
    expect(mainSource, isNot(contains('opaque_client_stub.dart')));
    expect(zkSource, isNot(contains('opaque_client_stub.dart')));
  });

  test('native client loads the packaged Android library and fails closed', () {
    expect(nativeSource,
        contains("DynamicLibrary.open('libvaultai_opaque_client.so')"));
    expect(nativeSource, contains('Platform.isAndroid'));
    expect(nativeSource, contains('OpaqueAuthenticationFailed'));
    expect(nativeSource, contains("error == 'auth_failed'"));
    expect(nativeSource, isNot(contains('authLogin')));
    expect(nativeSource, isNot(contains('dart:html')));
    expect(nativeSource, isNot(contains('dart:js')));
  });

  test('native wrapper exposes OPAQUE through Rust C FFI without logging', () {
    expect(cargoSource, contains('opaque-ke = { version = "4.0"'));
    expect(rustSource, contains('type OprfCs = Ristretto255'));
    expect(rustSource, contains('TripleDh<Ristretto255, Sha512>'));
    expect(rustSource, contains("type Ksf = argon2::Argon2<'static>"));
    expect(rustSource, contains('vaultai_opaque_client_start_login'));
    expect(rustSource, contains('vaultai_opaque_client_finish_login'));
    expect(rustSource, contains('vaultai_opaque_client_start_registration'));
    expect(rustSource, contains('vaultai_opaque_client_finish_registration'));
    expect(rustSource, contains('err("auth_failed")'));
    expect(rustSource, contains('vaultai_opaque_client_free_string'));
    expect(cargoSource, contains('zeroize = "1"'));
    expect(rustSource, contains('use zeroize::{Zeroize, Zeroizing};'));
    expect(rustSource, contains('bytes.zeroize();'));
    expect(nativeSource, contains('clearAndFree'));
    expect(nativeSource, contains('pointer[i] = 0;'));
    expect(rustSource, isNot(contains('println!')));
    expect(rustSource, isNot(contains('eprintln!')));
    expect(rustSource, isNot(contains('/auth/login')));
  });

  test('Android OPAQUE native build covers production ABIs', () {
    for (final abi in const ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86']) {
      expect(gradleSource, contains(abi));
    }
    for (final triple in const [
      'aarch64-linux-android',
      'armv7-linux-androideabi',
      'i686-linux-android',
      'x86_64-linux-android',
    ]) {
      expect(buildScript, contains(triple));
    }
    for (final abi in const ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86']) {
      expect(
        File(
          'android/app/src/main/jniLibs/$abi/libvaultai_opaque_client.so',
        ).existsSync(),
        isTrue,
        reason: '$abi native OPAQUE library must be packaged',
      );
    }
    expect(gradleSource, isNot(contains('externalNativeBuild')));
  });

  test('production auth errors do not render internal diagnostic payloads', () {
    expect(mainSource, isNot(contains('[diagnostic:')));
    expect(mainSource, contains(kAuthDeviceSafeError));
    expect(mainSource, contains(kUnlockDeviceSafeError));
    expect(mainSource, contains('debugAuthFailureTrace'));
  });

  test('debug auth logs redact vault names and sensitive values', () {
    expect(mainSource, contains('_safeVlogValue'));
    expect(mainSource, contains("lowerKey.contains('vaultname')"));
    expect(mainSource, contains("lowerKey.contains('vault_name')"));
    expect(mainSource, contains("lowerKey.contains('token')"));
    expect(mainSource, contains("lowerKey.contains('ciphertext')"));
    expect(mainSource, contains("return '<redacted>';"));
  });
}
