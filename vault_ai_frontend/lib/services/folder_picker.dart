

import 'dart:typed_data';

import 'folder_picker_stub.dart'
    if (dart.library.html) 'folder_picker_web.dart'
    if (dart.library.io) 'folder_picker_io.dart';


class PickedFolderFile {
  
  final String name;

  
  final String relativePath;

  
  final int size;

  
  final String? mimeType;

  
  final Future<Uint8List> Function() readBytes;

  const PickedFolderFile({
    required this.name,
    required this.relativePath,
    required this.size,
    required this.readBytes,
    this.mimeType,
  });
}


class FolderPickResult {
  
  
  final String rootFolderName;

  
  final List<PickedFolderFile> files;

  
  final List<String> skipped;

  const FolderPickResult({
    required this.rootFolderName,
    required this.files,
    this.skipped = const [],
  });

  
  bool get isEmpty => files.isEmpty;
}


abstract class FolderPickerService {
  
  
  bool get isSupported;

  
  String get unsupportedReason;

  
  Future<FolderPickResult?> pickFolder();
}


FolderPickerService createFolderPickerService() =>
    createPlatformFolderPickerService();


String normalizePickedRelativePath(String raw) {
  final trimmed = raw.trim();
  if (trimmed.isEmpty) return '';
  final unified = trimmed.replaceAll('\\', '/');
  final collapsed = unified.replaceAll(RegExp(r'/+'), '/');
  var result = collapsed;
  if (result.startsWith('/')) result = result.substring(1);
  if (result.endsWith('/')) result = result.substring(0, result.length - 1);
  return result;
}


String pickRootSegment(String relativePath) {
  if (relativePath.isEmpty) return '';
  final slash = relativePath.indexOf('/');
  if (slash <= 0) return relativePath;
  return relativePath.substring(0, slash);
}
