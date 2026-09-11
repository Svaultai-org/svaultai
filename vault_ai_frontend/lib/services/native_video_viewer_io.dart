import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:video_player/video_player.dart';

Future<bool> showNativeVideoViewer(
  BuildContext context, {
  required String fileName,
  required Uint8List bytes,
}) async {
  final tempDir = await getTemporaryDirectory();
  final safeExtension =
      fileName.toLowerCase().endsWith('.mov') ? '.mov' : '.mp4';
  final file = File(
    '${tempDir.path}/svaultai-preview-${DateTime.now().microsecondsSinceEpoch}$safeExtension',
  );
  VideoPlayerController? controller;
  try {
    await file.writeAsBytes(bytes, flush: true);
    controller = VideoPlayerController.file(file);
    await controller.initialize();
    await controller.setLooping(false);
    if (!context.mounted) return false;
    await showDialog<void>(
      context: context,
      useRootNavigator: false,
      builder: (dialogContext) => AlertDialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
        title: Text(fileName, maxLines: 2, overflow: TextOverflow.ellipsis),
        content: AspectRatio(
          aspectRatio: controller!.value.aspectRatio == 0
              ? 16 / 9
              : controller.value.aspectRatio,
          child: Stack(
            alignment: Alignment.center,
            children: [
              VideoPlayer(controller),
              ValueListenableBuilder<VideoPlayerValue>(
                valueListenable: controller,
                builder: (_, value, __) => IconButton.filled(
                  key: const Key('native_video_play_pause'),
                  iconSize: 36,
                  onPressed: () => value.isPlaying
                      ? controller!.pause()
                      : controller!.play(),
                  icon: Icon(value.isPlaying ? Icons.pause : Icons.play_arrow),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            key: const Key('native_video_close'),
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Close'),
          ),
        ],
      ),
    );
    return true;
  } finally {
    await controller?.pause();
    await controller?.dispose();
    if (await file.exists()) {
      await file.delete();
    }
  }
}
