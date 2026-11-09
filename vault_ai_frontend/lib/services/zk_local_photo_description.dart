/// Reads a creator-authored JPEG description on the unlocked device.
/// This is metadata, not an inference about the visible objects or scene.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:image/image.dart' as img;

const int maxLocalPhotoDescriptionBytes = 2 * 1024 * 1024;
const int maxLocalPhotoDescriptionTextBytes = 1024;

String? readEmbeddedJpegDescription(
  Uint8List bytes, {
  required bool Function() accessIsCurrent,
}) {
  if (!accessIsCurrent()) throw StateError('Vault access changed');
  if (bytes.length > maxLocalPhotoDescriptionBytes) {
    throw const FormatException('Photo exceeds local description scan limit');
  }
  if (bytes.length < 4 ||
      bytes[0] != 0xff ||
      bytes[1] != 0xd8 ||
      bytes[2] != 0xff) {
    return null;
  }
  String? raw;
  try {
    raw = img.decodeJpgExif(bytes)?.imageIfd.imageDescription;
  } catch (_) {
    // A malformed or unsupported JPEG must not become search evidence.
    return null;
  } finally {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }
  if (raw == null ||
      raw.length > maxLocalPhotoDescriptionTextBytes ||
      RegExp(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]').hasMatch(raw)) {
    return null;
  }
  final description = raw.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (description.isEmpty ||
      utf8.encode(description).length > maxLocalPhotoDescriptionTextBytes) {
    return null;
  }
  return description;
}
