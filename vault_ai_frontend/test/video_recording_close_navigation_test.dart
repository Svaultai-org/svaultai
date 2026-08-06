import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  late String source;

  setUpAll(() async {
    source = await File('lib/web_video_recorder_dialog.dart').readAsString();
  });

  test('recording exposes a visible close control and Escape action', () {
    expect(source, contains("Key('web_video_close')"));
    expect(source, contains("tooltip: 'Close recorder'"));
    expect(
      source,
      contains('SingleActivator(LogicalKeyboardKey.escape)'),
    );
    expect(source, contains('_requestExit'));
  });

  test('active recording requires explicit discard confirmation', () {
    expect(source, contains("Key('web_video_discard_dialog')"));
    expect(source, contains("Key('web_video_keep_recording')"));
    expect(source, contains("Key('web_video_discard_exit')"));
    expect(source, contains('barrierDismissible: false'));
    expect(source, contains('if (discard != true) {'));
  });

  test('review media cannot intercept discard confirmation actions', () async {
    final recorder = await File('lib/video_recorder_web.dart').readAsString();
    expect(source, contains('setReviewInteractionEnabled(false)'));
    expect(source, contains('setReviewInteractionEnabled(true)'));
    expect(recorder, contains("pointerEvents = enabled ? 'auto' : 'none'"));
  });

  test('confirmed discard releases recorder and clears preview state', () {
    expect(source, contains('_timer?.cancel();'));
    expect(source, contains('widget.recorder.cancel();'));
    expect(source, contains('Navigator.of(context).pop();'));
  });

  test('web recorder stops every acquired MediaStream track', () async {
    final recorder = await File('lib/video_recorder_web.dart').readAsString();
    expect(recorder, contains('for (final track in stream.getTracks())'));
    expect(recorder, contains('track.stop();'));
    expect(recorder, contains('_stream = null;'));
    expect(recorder, contains('_recorder = null;'));
  });
}
