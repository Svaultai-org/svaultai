

import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

import 'folder_picker.dart';

class _WebFolderPicker implements FolderPickerService {
  const _WebFolderPicker();

  @override
  bool get isSupported => true;

  @override
  String get unsupportedReason => '';

  @override
  Future<FolderPickResult?> pickFolder() async {
    
    
    final input = html.FileUploadInputElement()
      ..multiple = true;
    input.setAttribute('webkitdirectory', '');
    input.setAttribute('directory', '');
    
    
    input.style.display = 'none';
    html.document.body?.children.add(input);

    final completer = Completer<FolderPickResult?>();
    StreamSubscription<html.Event>? changeSub;
    StreamSubscription<html.Event>? cancelSub;

    void cleanup() {
      changeSub?.cancel();
      cancelSub?.cancel();
      input.remove();
    }

    changeSub = input.onChange.listen((_) {
      final files = input.files;
      if (files == null || files.isEmpty) {
        cleanup();
        if (!completer.isCompleted) completer.complete(null);
        return;
      }

      final picked = <PickedFolderFile>[];
      final skipped = <String>[];
      String? rootName;

      for (var i = 0; i < files.length; i++) {
        final f = files[i];
        
        
        final rawRel = f.relativePath;
        final relPath = normalizePickedRelativePath(
          (rawRel == null || rawRel.isEmpty) ? f.name : rawRel,
        );
        if (relPath.isEmpty) {
          skipped.add('${f.name}: missing relative path');
          continue;
        }
        rootName ??= pickRootSegment(relPath);

        final size = f.size;
        
        
        final fileRef = f;
        picked.add(PickedFolderFile(
          name: f.name,
          relativePath: relPath,
          size: size,
          mimeType: f.type.isEmpty ? null : f.type,
          readBytes: () => _readBlobBytes(fileRef),
        ));
      }

      cleanup();
      if (completer.isCompleted) return;
      completer.complete(FolderPickResult(
        rootFolderName: rootName ?? '',
        files: picked,
        skipped: skipped,
      ));
    });

    
    cancelSub = input.on['cancel'].listen((_) {
      cleanup();
      if (!completer.isCompleted) completer.complete(null);
    });

    input.click();
    return completer.future;
  }

  Future<Uint8List> _readBlobBytes(html.File file) {
    final reader = html.FileReader();
    final completer = Completer<Uint8List>();

    StreamSubscription<html.ProgressEvent>? loadSub;
    StreamSubscription<html.ProgressEvent>? errorSub;

    void cleanup() {
      loadSub?.cancel();
      errorSub?.cancel();
    }

    loadSub = reader.onLoadEnd.listen((_) {
      if (completer.isCompleted) return;
      final result = reader.result;
      cleanup();
      if (result is Uint8List) {
        completer.complete(result);
      } else if (result is List<int>) {
        completer.complete(Uint8List.fromList(result));
      } else if (result is ByteBuffer) {
        completer.complete(result.asUint8List());
      } else {
        completer.completeError(StateError(
          'FileReader returned unexpected type ${result.runtimeType} '
          'for ${file.name}',
        ));
      }
    });
    errorSub = reader.onError.listen((event) {
      if (completer.isCompleted) return;
      cleanup();
      completer.completeError(StateError(
        'FileReader failed on ${file.name}: ${reader.error}',
      ));
    });
    reader.readAsArrayBuffer(file);
    return completer.future;
  }
}

FolderPickerService createPlatformFolderPickerService() =>
    const _WebFolderPicker();
