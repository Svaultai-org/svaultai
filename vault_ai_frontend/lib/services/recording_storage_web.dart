import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'recording_storage.dart';

class _WebRecordingStorage implements RecordingStorage {
  const _WebRecordingStorage();

  @override
  Future<String> audioPath(String fileName) async => fileName;

  @override
  Future<Uint8List> readAndMaybeDelete(String path) async {
    final response = await http.get(Uri.parse(path));
    return response.bodyBytes;
  }
}

RecordingStorage createPlatformRecordingStorage() =>
    const _WebRecordingStorage();
