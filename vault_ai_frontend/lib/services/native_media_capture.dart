import 'dart:typed_data';

import 'native_media_capture_stub.dart'
    if (dart.library.io) 'native_media_capture_io.dart';

class CapturedMedia {
  final String name;
  final String kind;
  final String mimeType;
  final Uint8List bytes;

  const CapturedMedia({
    required this.name,
    required this.kind,
    required this.mimeType,
    required this.bytes,
  });
}

abstract class NativeMediaCaptureService {
  bool get isSupported;
  Future<CapturedMedia?> capturePhoto();
  Future<CapturedMedia?> captureVideo();
}

NativeMediaCaptureService createNativeMediaCaptureService() =>
    createPlatformNativeMediaCaptureService();
