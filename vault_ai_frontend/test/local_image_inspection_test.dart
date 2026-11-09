import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vault_ai_frontend/services/local_image_inspection.dart';

void main() {
  const inspector = LocalImageInspector();

  test('red and black PNG stays a bounded local pixel description', () {
    final image = img.Image(width: 20, height: 10);
    for (var y = 0; y < image.height; y++) {
      for (var x = 0; x < image.width; x++) {
        image.setPixelRgba(x, y, x < 10 ? 255 : 0, 0, 0, 255);
      }
    }
    final result = inspector.inspect(Uint8List.fromList(img.encodePng(image)));
    expect(result, isNotNull);
    expect(result!.width, 20);
    expect(result.height, 10);
    expect(result.sampledPixels,
        lessThanOrEqualTo(LocalImageInspector.maxSamples));
    expect(result.colors.map((c) => c.name), containsAll(['red', 'black']));
    expect(result.description, contains('does not identify people'));
    expect(result.description, isNot(contains('shirt')));
  });

  test('JPEG dimensions and colors are inspected without a service call', () {
    final image = img.Image(width: 8, height: 8);
    img.fill(image, color: img.ColorRgb8(0, 0, 255));
    final result = inspector.inspect(Uint8List.fromList(img.encodeJpg(image)));
    expect(result?.width, 8);
    expect(result?.height, 8);
    expect(result?.colors.first.name, 'blue');
  });

  test('rejects invalid and oversized images before pixel decoding', () {
    expect(inspector.inspect(Uint8List.fromList([1, 2, 3, 4])), isNull);
    expect(
        inspector.inspect(Uint8List(LocalImageInspector.maxEncodedBytes + 1)),
        isNull);
    final tooWide = img.Image(width: 6001, height: 1);
    expect(
        inspector.inspect(Uint8List.fromList(img.encodePng(tooWide))), isNull);
  });

}
