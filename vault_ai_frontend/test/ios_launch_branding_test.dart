import 'dart:io';

import 'package:image/image.dart' as img;
import 'package:flutter_test/flutter_test.dart';

void main() {
  const canonicalAsset = 'assets/branding/vaultai-icon-1024.png';
  const launchAssetDir = 'ios/Runner/Assets.xcassets/LaunchImage.imageset';

  test('iOS launch images use the canonical dark SVaultAI artwork', () {
    final canonical = img.decodePng(File(canonicalAsset).readAsBytesSync());
    expect(canonical, isNotNull);

    for (final name in <String>[
      'LaunchImage.png',
      'LaunchImage@2x.png',
      'LaunchImage@3x.png',
      'LaunchImageDark.png',
      'LaunchImageDark@2x.png',
      'LaunchImageDark@3x.png',
    ]) {
      final launch = img.decodePng(
        File('$launchAssetDir/$name').readAsBytesSync(),
      );
      expect(launch, isNotNull, reason: '$name must be a readable PNG');

      final corner = launch!.getPixel(0, 0);
      expect(corner.r, lessThan(40),
          reason: '$name must not have a white tile');
      expect(corner.g, lessThan(40),
          reason: '$name must not have a white tile');
      expect(corner.b, lessThan(40),
          reason: '$name must not have a white tile');
    }
  });

  test('native launch and first Flutter frame reference canonical branding',
      () {
    final storyboard = File('ios/Runner/Base.lproj/LaunchScreen.storyboard')
        .readAsStringSync();
    final plist = File('ios/Runner/Info.plist').readAsStringSync();
    final main = File('lib/main.dart').readAsStringSync();
    final pubspec = File('pubspec.yaml').readAsStringSync();

    expect(storyboard, contains('image="LaunchImage"'));
    expect(storyboard, contains('image="LaunchBackground"'));
    expect(plist, contains('<string>LaunchScreen</string>'));
    expect(main, contains("kCanonicalBrandLogoAsset = '$canonicalAsset'"));
    expect(main, contains('top_nav_canonical_logo'));
    expect(pubspec, contains('image:            "$canonicalAsset"'));
  });
}
