// 2026-07-13: local-only QR decoder for a picked / captured image.
//
// The whole decode pipeline runs inside the client — the picked
// image bytes are handed to the `image` package for pixel decoding
// and to `zxing2` for QR extraction, then discarded. Nothing is
// uploaded, nothing is retained, nothing is logged.
//
// The decoder is intentionally strict:
//   * Exactly ONE QR must be found. Zero or many → ambiguity.
//   * The QR must be non-empty text.
//   * Parsing / network validation is delegated to
//     `RecipientQrParser` — this file does NOT know or care about
//     wallet-address shapes.
//
// The picked image is decoded to a luminance grid then run through
// zxing2's QRCodeReader. If the reader can't lock onto a QR at the
// primary resolution we downscale once and retry (helps camera-
// captured photos with excessive resolution).

import 'dart:async';
import 'dart:typed_data';

import 'package:image/image.dart' as img;
import 'package:zxing2/qrcode.dart';


enum QrImageDecodeCategory {
  ok,
  noQrFound,
  multipleQrFound,
  decodeError,
}


class QrImageDecodeResult {
  final QrImageDecodeCategory category;
  final String? text;
  final String? errorHint;

  const QrImageDecodeResult._({
    required this.category,
    this.text,
    this.errorHint,
  });

  factory QrImageDecodeResult.ok(String text) =>
      QrImageDecodeResult._(category: QrImageDecodeCategory.ok, text: text);

  factory QrImageDecodeResult.noQr() =>
      const QrImageDecodeResult._(
        category: QrImageDecodeCategory.noQrFound,
      );

  factory QrImageDecodeResult.multiple() =>
      const QrImageDecodeResult._(
        category: QrImageDecodeCategory.multipleQrFound,
      );

  factory QrImageDecodeResult.decodeError(String hint) =>
      QrImageDecodeResult._(
        category: QrImageDecodeCategory.decodeError,
        errorHint: hint,
      );

  bool get ok => category == QrImageDecodeCategory.ok;
}


/// A tiny abstraction so widget tests inject a fake decoder and
/// don't need to load a real image + zxing binary.
abstract class QrImageDecoder {
  Future<QrImageDecodeResult> decode(Uint8List bytes);
}


/// Production decoder — pure-Dart pipeline, no I/O, no network.
class ZxingQrImageDecoder implements QrImageDecoder {
  const ZxingQrImageDecoder();

  @override
  Future<QrImageDecodeResult> decode(Uint8List bytes) async {
    try {
      final decoded = img.decodeImage(bytes);
      if (decoded == null) {
        return QrImageDecodeResult.decodeError(
          'image-decode-failed',
        );
      }
      // Try full-resolution first, then a single downscale pass at
      // 1024 px on the long edge. Downscaling helps when a phone
      // camera capture is 4032 x 3024 — zxing's binary quantiser can
      // stall on that much data.
      final firstAttempt = _tryDecodePixels(decoded);
      if (firstAttempt.category != QrImageDecodeCategory.decodeError) {
        return firstAttempt;
      }
      final resized = _downscaleIfLarge(decoded);
      if (resized == null) return firstAttempt;
      return _tryDecodePixels(resized);
    } catch (e) {
      return QrImageDecodeResult.decodeError(
        _shortHint(e.toString()),
      );
    }
  }

  QrImageDecodeResult _tryDecodePixels(img.Image src) {
    // Build a 32-bit ARGB luminance source array the way zxing2
    // expects.
    final pixels = _toArgb32(src);
    final source = RGBLuminanceSource(
      src.width, src.height, pixels,
    );
    final bitmap = BinaryBitmap(HybridBinarizer(source));
    final reader = QRCodeReader();
    // First try: single-decode. Multiple-decode below.
    try {
      final result = reader.decode(bitmap);
      final text = result.text;
      // Check for a second QR by re-scanning with 'GenericMulti'
      // hints — if the image has TWO QRs we must refuse.
      final multi = _findAnotherQr(src, ignoreText: text);
      if (multi != null && multi != text) {
        return QrImageDecodeResult.multiple();
      }
      if (text.isEmpty) {
        return QrImageDecodeResult.decodeError('empty-payload');
      }
      return QrImageDecodeResult.ok(text);
    } on NotFoundException {
      return QrImageDecodeResult.noQr();
    } catch (e) {
      return QrImageDecodeResult.decodeError(
        _shortHint(e.toString()),
      );
    }
  }

  /// Very cheap "is there a SECOND QR" check — the primary decoder
  /// only returns one; we quarter the image and try again. Not a
  /// perfect multi-QR detector but sufficient for the safety
  /// requirement "refuse if multiple QRs".
  String? _findAnotherQr(img.Image src, {required String ignoreText}) {
    final halfW = src.width ~/ 2;
    final halfH = src.height ~/ 2;
    if (halfW < 60 || halfH < 60) return null;
    final quadrants = <List<int>>[
      [0, 0, halfW, halfH],
      [halfW, 0, halfW, halfH],
      [0, halfH, halfW, halfH],
      [halfW, halfH, halfW, halfH],
    ];
    for (final q in quadrants) {
      try {
        final sub = img.copyCrop(
          src, x: q[0], y: q[1], width: q[2], height: q[3],
        );
        final source = RGBLuminanceSource(
          sub.width, sub.height, _toArgb32(sub),
        );
        final bitmap = BinaryBitmap(HybridBinarizer(source));
        final r = QRCodeReader().decode(bitmap);
        if (r.text != ignoreText && r.text.isNotEmpty) {
          return r.text;
        }
      } catch (_) {
        // NotFound in a quadrant is expected and not an error.
      }
    }
    return null;
  }

  Int32List _toArgb32(img.Image src) {
    // zxing2's RGBLuminanceSource expects 32-bit ARGB pixels.
    final out = Int32List(src.width * src.height);
    var i = 0;
    for (var y = 0; y < src.height; y++) {
      for (var x = 0; x < src.width; x++) {
        final p = src.getPixel(x, y);
        final r = p.r.toInt();
        final g = p.g.toInt();
        final b = p.b.toInt();
        out[i++] = (0xff << 24) | (r << 16) | (g << 8) | b;
      }
    }
    return out;
  }

  img.Image? _downscaleIfLarge(img.Image src) {
    final longEdge = src.width > src.height ? src.width : src.height;
    if (longEdge <= 1024) return null;
    if (src.width >= src.height) {
      return img.copyResize(src, width: 1024);
    }
    return img.copyResize(src, height: 1024);
  }

  String _shortHint(String s) {
    final oneLine = s.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (oneLine.length <= 120) return oneLine;
    return '${oneLine.substring(0, 117)}...';
  }
}
