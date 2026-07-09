import 'dart:typed_data';


class MediaPlayer {
  static bool canPlay({required String? mimeType, required bool isVideo}) =>
      false;

  bool register({
    required String viewType,
    required Uint8List bytes,
    required String? mimeType,
    required bool isVideo,
  }) {
    return false;
  }

  void dispose() {}
}
