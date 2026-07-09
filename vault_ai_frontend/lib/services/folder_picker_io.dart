

import 'dart:io' as io;
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

import 'folder_picker.dart';

class _IoFolderPicker implements FolderPickerService {
  const _IoFolderPicker();

  @override
  bool get isSupported {
    
    
    if (io.Platform.isWindows) return true;
    if (io.Platform.isMacOS) return true;
    if (io.Platform.isLinux) return true;
    return false;
  }

  @override
  String get unsupportedReason {
    if (io.Platform.isAndroid || io.Platform.isIOS) {
      return 'Folder upload is available on the web and desktop. '
          'On mobile, pick multiple files instead.';
    }
    return 'Folder upload is unavailable on this platform.';
  }

  @override
  Future<FolderPickResult?> pickFolder() async {
    if (!isSupported) {
      throw UnsupportedError(unsupportedReason);
    }

    final selectedDir = await FilePicker.platform.getDirectoryPath();
    if (selectedDir == null) return null;

    final dir = io.Directory(selectedDir);
    if (!await dir.exists()) return null;

    final rootName = _basename(selectedDir);
    final picked = <PickedFolderFile>[];
    final skipped = <String>[];

    await for (final entity in dir.list(recursive: true, followLinks: false)) {
      if (entity is! io.File) continue;
      try {
        final stat = await entity.stat();
        final rel = _relPath(entity.path, selectedDir);
        if (rel.isEmpty) {
          skipped.add('${entity.path}: empty relative path');
          continue;
        }
        final fullRel = normalizePickedRelativePath(
          rootName.isEmpty ? rel : '$rootName/$rel',
        );
        picked.add(PickedFolderFile(
          name: _basename(entity.path),
          relativePath: fullRel,
          size: stat.size,
          mimeType: null, 
          readBytes: () => _readFileBytes(entity),
        ));
      } catch (e) {
        skipped.add('${entity.path}: $e');
      }
    }

    return FolderPickResult(
      rootFolderName: rootName,
      files: picked,
      skipped: skipped,
    );
  }

  Future<Uint8List> _readFileBytes(io.File file) async {
    return file.readAsBytes();
  }

  
  static String _basename(String fullPath) {
    final unified = fullPath.replaceAll('\\', '/');
    final slash = unified.lastIndexOf('/');
    if (slash < 0) return unified;
    return unified.substring(slash + 1);
  }

  
  static String _relPath(String fullPath, String basePath) {
    final full = fullPath.replaceAll('\\', '/');
    final base = basePath.replaceAll('\\', '/');
    if (!full.startsWith(base)) {
      return full;
    }
    var rest = full.substring(base.length);
    if (rest.startsWith('/')) rest = rest.substring(1);
    return rest;
  }
}

FolderPickerService createPlatformFolderPickerService() =>
    const _IoFolderPicker();
