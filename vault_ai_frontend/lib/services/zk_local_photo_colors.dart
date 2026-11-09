/// Bounded photo-color observation on the unlocked device.
///
/// This is pixel analysis, not object recognition. It never identifies a
/// person, garment, scene, or spoken content. The caller owns the decrypted
/// bytes and must clear them after this function returns.

import 'dart:typed_data';
import 'dart:ui' as ui;
import 'dart:math' as math;

const int maxLocalPhotoColorBytes = 2 * 1024 * 1024;
const int maxLocalPhotoPixels = 16 * 1024 * 1024;

Future<Set<String>> observePhotoColors(
  Uint8List encoded, {
  required bool Function() accessIsCurrent,
}) async {
  if (!accessIsCurrent()) throw StateError('Vault access changed');
  if (encoded.isEmpty || encoded.length > maxLocalPhotoColorBytes) {
    throw const FormatException('Photo exceeds local color scan limit');
  }
  final buffer = await ui.ImmutableBuffer.fromUint8List(encoded);
  ui.ImageDescriptor? descriptor;
  ui.Codec? codec;
  try {
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    final width = descriptor.width;
    final height = descriptor.height;
    if (width < 1 || height < 1 || width > 6000 || height > 6000 ||
        width * height > maxLocalPhotoPixels) {
      throw const FormatException('Photo dimensions exceed local scan limit');
    }
    final scale = math.min(1.0, math.min(64 / width, 64 / height));
    codec = await descriptor.instantiateCodec(
      targetWidth: math.max(1, (width * scale).round()),
      targetHeight: math.max(1, (height * scale).round()),
    );
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    final frame = await codec.getNextFrame();
    try {
      if (!accessIsCurrent()) throw StateError('Vault access changed');
      final pixels = await frame.image.toByteData(
        format: ui.ImageByteFormat.rawRgba,
      );
      if (!accessIsCurrent()) throw StateError('Vault access changed');
      if (pixels == null || frame.image.width > 64 ||
          frame.image.height > 64) {
        throw const FormatException('Photo cannot be sampled safely');
      }
      return classifyPhotoColors(
        pixels.buffer.asUint8List(
          pixels.offsetInBytes, pixels.lengthInBytes,
        ),
      );
    } finally {
      frame.image.dispose();
    }
  } finally {
    codec?.dispose();
    descriptor?.dispose();
    buffer.dispose();
  }
}

/// Pure color classifier for RGBA samples. A label requires at least 8% of
/// visible pixels; a few incidental pixels do not establish a photo color.
Set<String> classifyPhotoColors(Uint8List rgba) {
  if (rgba.isEmpty || rgba.length % 4 != 0 || rgba.length > 64 * 64 * 4) {
    throw const FormatException('Invalid local photo sample');
  }
  final counts = <String, int>{};
  var visible = 0;
  for (var i = 0; i < rgba.length; i += 4) {
    if (rgba[i + 3] < 128) continue;
    visible++;
    final r = rgba[i] / 255;
    final g = rgba[i + 1] / 255;
    final b = rgba[i + 2] / 255;
    final max = r >= g && r >= b ? r : g >= b ? g : b;
    final min = r <= g && r <= b ? r : g <= b ? g : b;
    final delta = max - min;
    final saturation = max == 0 ? 0.0 : delta / max;
    String color;
    if (max < 0.22) {
      color = 'black';
    } else if (saturation < 0.18) {
      color = max >= 0.83 ? 'white' : 'gray';
    } else {
      var hue = max == r
          ? ((g - b) / delta) % 6
          : max == g
              ? (b - r) / delta + 2
              : (r - g) / delta + 4;
      hue *= 60;
      if (hue < 0) hue += 360;
      color = hue < 15 || hue >= 345
          ? 'red'
          : hue < 45
              ? 'orange'
              : hue < 70
                  ? 'yellow'
                  : hue < 170
                      ? 'green'
                      : hue < 260
                          ? 'blue'
                          : hue < 315
                              ? 'purple'
                              : 'pink';
    }
    counts[color] = (counts[color] ?? 0) + 1;
  }
  if (visible == 0) return const <String>{};
  return counts.entries
      .where((entry) => entry.value / visible >= 0.08)
      .map((entry) => entry.key)
      .toSet();
}
