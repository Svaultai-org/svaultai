import 'package:file_picker/file_picker.dart';

typedef QaFilePicker = Future<FilePickerResult?> Function({required bool allowMultiple});

QaFilePicker? qaFilePickerOverride;

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
