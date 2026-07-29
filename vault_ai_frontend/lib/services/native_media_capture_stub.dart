import 'native_media_capture.dart';

class _UnsupportedNativeMediaCaptureService
    implements NativeMediaCaptureService {
  const _UnsupportedNativeMediaCaptureService();

  @override
  bool get isSupported => false;

  @override
  Future<CapturedMedia?> capturePhoto() async => null;

  @override
  Future<CapturedMedia?> captureVideo() async => null;
}

NativeMediaCaptureService createPlatformNativeMediaCaptureService() =>
    const _UnsupportedNativeMediaCaptureService();
