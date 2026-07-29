import 'dart:typed_data';

import 'recording_storage.dart';

class _UnsupportedRecordingStorage implements RecordingStorage {
  const _UnsupportedRecordingStorage();

  @override
  Future<String> audioPath(String fileName) async => fileName;

  @override
  Future<Uint8List> readAndMaybeDelete(String path) async {
    throw UnsupportedError('Recording storage is unavailable.');
  }
}

RecordingStorage createPlatformRecordingStorage() =>
    const _UnsupportedRecordingStorage();
