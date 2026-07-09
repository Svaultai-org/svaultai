

import 'folder_picker.dart';

class _StubFolderPicker implements FolderPickerService {
  const _StubFolderPicker();

  @override
  bool get isSupported => false;

  @override
  String get unsupportedReason =>
      'Folder upload is unavailable on this platform.';

  @override
  Future<FolderPickResult?> pickFolder() async {
    throw UnsupportedError(unsupportedReason);
  }
}

FolderPickerService createPlatformFolderPickerService() =>
    const _StubFolderPicker();
