import 'dart:io' as io;

import 'package:image_picker/image_picker.dart';

import 'native_media_capture.dart';

class _IoNativeMediaCaptureService implements NativeMediaCaptureService {
  final ImagePicker _picker;

  _IoNativeMediaCaptureService({ImagePicker? picker})
      : _picker = picker ?? ImagePicker();

  @override
  bool get isSupported => io.Platform.isAndroid || io.Platform.isIOS;

  @override
  Future<CapturedMedia?> capturePhoto() async {
    if (!isSupported) return null;
    final picked = await _picker.pickImage(
      source: ImageSource.camera,
      requestFullMetadata: false,
    );
    if (picked == null) return null;
    final bytes = await picked.readAsBytes();
    if (bytes.isEmpty) return null;
    return CapturedMedia(
      name: _safeName(picked.name, fallbackPrefix: 'photo', extension: 'jpg'),
      kind: 'image',
      mimeType: picked.mimeType?.trim().isNotEmpty == true
          ? picked.mimeType!.trim()
          : 'image/jpeg',
      bytes: bytes,
    );
  }

  @override
  Future<CapturedMedia?> captureVideo() async {
    if (!isSupported) return null;
    final picked = await _picker.pickVideo(
      source: ImageSource.camera,
      maxDuration: const Duration(minutes: 10),
    );
    if (picked == null) return null;
    final bytes = await picked.readAsBytes();
    if (bytes.isEmpty) return null;
    return CapturedMedia(
      name: _safeName(picked.name, fallbackPrefix: 'video', extension: 'mp4'),
      kind: 'video',
      mimeType: picked.mimeType?.trim().isNotEmpty == true
          ? picked.mimeType!.trim()
          : 'video/mp4',
      bytes: bytes,
    );
  }

  String _safeName(
    String raw, {
    required String fallbackPrefix,
    required String extension,
  }) {
    final trimmed = raw.trim();
    final cleaned = trimmed.replaceAll(RegExp(r'[\\/:*?"<>|]+'), '_');
    if (cleaned.isNotEmpty) return cleaned;
    return '${fallbackPrefix}_${DateTime.now().millisecondsSinceEpoch}.$extension';
  }
}

NativeMediaCaptureService createPlatformNativeMediaCaptureService() =>
    _IoNativeMediaCaptureService();
