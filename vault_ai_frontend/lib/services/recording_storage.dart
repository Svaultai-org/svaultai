import 'dart:typed_data';

import 'recording_storage_stub.dart'
    if (dart.library.html) 'recording_storage_web.dart'
    if (dart.library.io) 'recording_storage_io.dart';

abstract class RecordingStorage {
  Future<String> audioPath(String fileName);
  Future<Uint8List> readAndMaybeDelete(String path);
}

RecordingStorage createRecordingStorage() => createPlatformRecordingStorage();
