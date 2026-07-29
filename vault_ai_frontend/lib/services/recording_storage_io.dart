import 'dart:io' as io;
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';

import 'recording_storage.dart';

class _IoRecordingStorage implements RecordingStorage {
  const _IoRecordingStorage();

  @override
  Future<String> audioPath(String fileName) async {
    final dir = await getTemporaryDirectory();
    return '${dir.path}${io.Platform.pathSeparator}${_safeFileName(fileName)}';
  }

  @override
  Future<Uint8List> readAndMaybeDelete(String path) async {
    final file = io.File(path);
    final bytes = await file.readAsBytes();
    try {
      if (await file.exists()) {
        await file.delete();
      }
    } catch (_) {}
    return bytes;
  }

  String _safeFileName(String fileName) {
    final trimmed = fileName.trim();
    final cleaned = trimmed.replaceAll(RegExp(r'[\\/:*?"<>|]+'), '_');
    return cleaned.isEmpty ? 'recording.m4a' : cleaned;
  }
}

RecordingStorage createPlatformRecordingStorage() => const _IoRecordingStorage();
