import 'dart:typed_data';

import 'package:flutter/foundation.dart';


class MediaPlayer {
  final ValueNotifier<String?> errorNotifier =
      ValueNotifier<String?>(null);

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

  void dispose() {
    errorNotifier.dispose();
  }
}
