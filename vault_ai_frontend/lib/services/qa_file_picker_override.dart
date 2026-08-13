import 'package:file_picker/file_picker.dart';

typedef QaFilePicker = Future<FilePickerResult?> Function(
    {required bool allowMultiple});
typedef QaTypedFilePicker = Future<FilePickerResult?> Function({
  required bool allowMultiple,
  required FileType type,
  List<String>? allowedExtensions,
});

QaFilePicker? qaFilePickerOverride;
QaTypedFilePicker? qaTypedFilePickerOverride;

Future<FilePickerResult?> pickFilesForUpload({required bool allowMultiple}) {
  final override = qaFilePickerOverride;
  if (override != null) return override(allowMultiple: allowMultiple);
  return FilePicker.platform.pickFiles(
    withData: false,
    withReadStream: true,
    allowMultiple: allowMultiple,
    type: FileType.any,
  );
}

Future<FilePickerResult?> pickTypedFilesForUpload({
  required bool allowMultiple,
  required FileType type,
  List<String>? allowedExtensions,
}) {
  final override = qaTypedFilePickerOverride;
  if (override != null) {
    return override(
      allowMultiple: allowMultiple,
      type: type,
      allowedExtensions: allowedExtensions,
    );
  }
  return FilePicker.platform.pickFiles(
    withData: false,
    withReadStream: true,
    allowMultiple: allowMultiple,
    type: type,
    allowedExtensions: allowedExtensions,
  );
}
