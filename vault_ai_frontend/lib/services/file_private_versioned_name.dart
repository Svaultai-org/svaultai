/// Choose a local name after the server reports only a blinded name conflict.
/// The plaintext candidate is encrypted into the next V2 manifest; it is never
/// sent in the conflict request.
String privateVersionedFileName(String original, int version) {
  if (version < 2 || version > 100 || original.trim().isEmpty) {
    throw const FormatException('Invalid private file name version');
  }
  final name = original.trim();
  final match = RegExp(r'^(.*?)(\.[^./\s]{1,12})?$').firstMatch(name);
  var base = (match?.group(1) ?? name).trimRight();
  final extension = match?.group(2) ?? '';
  final suffix = ' ($version)$extension';
  while (base.isNotEmpty && base.length + suffix.length > 255) {
    final codepoints = base.runes.toList()..removeLast();
    base = String.fromCharCodes(codepoints);
  }
  if (base.isEmpty) throw const FormatException('Private file name too long');
  return '$base$suffix';
}
