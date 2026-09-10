import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('native video preview is wired and deletes temporary plaintext',
      () async {
    final main = await File('lib/main.dart').readAsString();
    final native =
        await File('lib/services/native_video_viewer_io.dart').readAsString();
    expect(main, contains('showNativeVideoViewer('));
    expect(main,
        isNot(contains("reason: 'In-app playback is currently web-only.'")));
    expect(native, contains('VideoPlayerController.file'));
    expect(native, contains('await file.delete()'));
    expect(native, contains('await controller?.dispose()'));
  });
}
