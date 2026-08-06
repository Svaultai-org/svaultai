import 'dart:typed_data';
import 'dart:async';

class VideoCaptureDevice {
  final String deviceId;
  final String label;
  final String kind;

  const VideoCaptureDevice({
    required this.deviceId,
    required this.label,
    required this.kind,
  });
}

class VideoRecorder {
  Stream<String> get mediaErrors => const Stream.empty();
  String get lastErrorMessage =>
      'Camera recording is not supported on this platform.';
  Future<bool> requestPermission({
    String? videoDeviceId,
    String? audioDeviceId,
    int? width,
    int? height,
    String? facingMode,
    int? frameRate,
  }) async =>
      false;
  Future<List<VideoCaptureDevice>> enumerateDevices() async => const [];
  void registerPreview(String viewType) {}
  void registerRecordingPreview(
    String viewType,
    Uint8List bytes, {
    String mimeType = 'video/webm',
  }) {}
  void start() {}
  Future<Uint8List?> stop() async => null;
  void setCameraEnabled(bool enabled) {}
  void setMicrophoneEnabled(bool enabled) {}
  void setReviewInteractionEnabled(bool enabled) {}
  List<String> get trackStates => const [];
  void cancel() {}
  void dispose() {}
}
