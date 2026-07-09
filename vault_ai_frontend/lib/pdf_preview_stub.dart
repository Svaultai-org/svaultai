import 'dart:typed_data';


class VaultPdfPreviewer {
  bool get available => false;

  bool register({
    required String viewType,
    required Uint8List bytes,
  }) {
    return false;
  }

  void dispose() {}
}
