// 2026-07-13: Injectable image-picker adapter for the recipient
// QR-scan flow.
//
// Production uses `file_picker` which on iPhone Safari opens the
// native "Take Photo / Photo Library / Choose File" chooser via
// the <input type="file" accept="image/*"> element. On other web
// browsers the same element is used; on native (iOS/Android app
// builds) file_picker delegates to the OS.
//
// Widget tests inject a fake that returns pre-canned bytes so the
// picker is never actually opened. Cancellation returns null.
//
// The picker is local-only:
//   * bytes stay in memory,
//   * are handed to `QrImageDecoder`,
//   * are then dropped.
// The Send flow NEVER uploads image bytes to the backend.

import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';


abstract class QrImagePicker {
  /// Prompt the user to pick or capture an image. Returns the
  /// selected image bytes, or null if they cancelled.
  Future<Uint8List?> pickImageBytes();
}


class FilePickerQrImagePicker implements QrImagePicker {
  const FilePickerQrImagePicker();

  @override
  Future<Uint8List?> pickImageBytes() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      // withData=true forces bytes on web (no filesystem access)
      // and returns bytes on native too, so downstream code has one
      // path.
      withData: true,
      allowMultiple: false,
    );
    if (result == null || result.files.isEmpty) return null;
    return result.files.first.bytes;
  }
}
