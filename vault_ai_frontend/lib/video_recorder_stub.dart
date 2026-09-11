import 'dart:typed_data';


class VideoRecorder {
  Future<bool> requestPermission() async => false;
  void registerPreview(String viewType) {}
  void start() {}
  Future<Uint8List?> stop() async => null;
  void cancel() {}
  void dispose() {}
}
