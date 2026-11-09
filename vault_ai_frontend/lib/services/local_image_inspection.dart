/// Bounded, device-local inspection of one explicitly selected image.
/// This describes pixels only. It cannot identify people or objects.
library;

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:image/image.dart' as img;

class LocalColorShare {
  final String name;
  final int percent;

  const LocalColorShare(this.name, this.percent);
}

class LocalImageInspection {
  final int width;
  final int height;
  final int sampledPixels;
  final List<LocalColorShare> colors;

  const LocalImageInspection({
    required this.width,
    required this.height,
    required this.sampledPixels,
    required this.colors,
  });

  String get description {
    final colorsText = colors.isEmpty
        ? 'no visible pixel colors could be measured'
        : colors.map((color) => '${color.name} ${color.percent}%').join(', ');
    return 'Local image check: $width × $height pixels. '
        'Approximate sampled pixel colors: $colorsText. '
        'This does not identify people, clothing, or objects.';
  }
}

class LocalImageInspector {
  static const int maxEncodedBytes = 12 * 1024 * 1024;
  static const int maxPixels = 20 * 1000 * 1000;
  static const int maxSamples = 4096;

  const LocalImageInspector();

  LocalImageInspection? inspect(Uint8List bytes) {
    if (bytes.isEmpty || bytes.length > maxEncodedBytes) return null;
    final png = _isPng(bytes);
    final jpeg = _isJpeg(bytes);
    if (!png && !jpeg) return null;
    try {
      final info = png
          ? img.PngDecoder().startDecode(bytes)
          : img.JpegDecoder().startDecode(bytes);
      if (info == null ||
          info.numFrames != 1 ||
          info.width < 1 ||
          info.height < 1 ||
          info.width > 6000 ||
          info.height > 6000 ||
          info.width * info.height > maxPixels) {
        return null;
      }
      final image = png ? img.decodePng(bytes) : img.decodeJpg(bytes);
      if (image == null ||
          image.width != info.width ||
          image.height != info.height) {
        return null;
      }
      final step = math.max(
          1, math.sqrt((image.width * image.height) / maxSamples).ceil());
      final counts = <String, int>{};
      var sampled = 0;
      for (var y = 0; y < image.height && sampled < maxSamples; y += step) {
        for (var x = 0; x < image.width && sampled < maxSamples; x += step) {
          final pixel = image.getPixel(x, y);
          if (pixel.a < 128) continue;
          final name =
              _colorName(pixel.r.toInt(), pixel.g.toInt(), pixel.b.toInt());
          counts[name] = (counts[name] ?? 0) + 1;
          sampled++;
        }
      }
      if (sampled == 0) return null;
      final sorted = counts.entries.toList()
        ..sort((a, b) {
          final count = b.value.compareTo(a.value);
          return count == 0 ? a.key.compareTo(b.key) : count;
        });
      return LocalImageInspection(
        width: image.width,
        height: image.height,
        sampledPixels: sampled,
        colors: [
          for (final entry in sorted.take(3))
            LocalColorShare(entry.key, (entry.value * 100 / sampled).round()),
        ],
      );
    } catch (_) {
      return null;
    }
  }

  static bool _isPng(Uint8List bytes) =>
      bytes.length >= 24 &&
      bytes[0] == 137 &&
      bytes[1] == 80 &&
      bytes[2] == 78 &&
      bytes[3] == 71 &&
      bytes[4] == 13 &&
      bytes[5] == 10 &&
      bytes[6] == 26 &&
      bytes[7] == 10;

  static bool _isJpeg(Uint8List bytes) =>
      bytes.length >= 4 &&
      bytes[0] == 255 &&
      bytes[1] == 216 &&
      bytes[2] == 255;

  static String _colorName(int r, int g, int b) {
    final high = math.max(r, math.max(g, b));
    final low = math.min(r, math.min(g, b));
    final delta = high - low;
    if (high < 50) return 'black';
    if (low > 215 && delta < 30) return 'white';
    if (delta < 30 || delta / high < 0.18) return 'gray';
    final hue = high == r
        ? 60 * (((g - b) / delta) % 6)
        : high == g
            ? 60 * ((b - r) / delta + 2)
            : 60 * ((r - g) / delta + 4);
    final normalizedHue = hue < 0 ? hue + 360 : hue;
    if (normalizedHue < 15 || normalizedHue >= 345) return 'red';
    if (normalizedHue < 45) return high < 180 ? 'brown' : 'orange';
    if (normalizedHue < 70) return 'yellow';
    if (normalizedHue < 165) return 'green';
    if (normalizedHue < 200) return 'cyan';
    if (normalizedHue < 260) return 'blue';
    if (normalizedHue < 320) return 'purple';
    return 'pink';
  }
}

/// Suitable for Flutter's `compute`: only a short description crosses back
/// from the worker, and no network transport is involved.
String? inspectLocalImageDescription(Uint8List bytes) =>
    const LocalImageInspector().inspect(bytes)?.description;
