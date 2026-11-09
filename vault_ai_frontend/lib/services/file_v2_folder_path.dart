import 'dart:convert';

/// A folder picker's path, including the final file name. It is placed only
/// inside the client-encrypted V2 manifest, never in a request field or URL.
String requirePrivateV2RelativePath(String path, {String? fileName}) {
  if (path.isEmpty ||
      utf8.encode(path).length > 4096 ||
      path.contains('\\') ||
      path.startsWith('/') ||
      path.endsWith('/') ||
      RegExp(r'[\x00-\x1f\x7f]').hasMatch(path)) {
    throw const FormatException('Invalid private folder path');
  }
  final parts = path.split('/');
  if (parts.length < 2 ||
      parts.any((part) => part.isEmpty || part == '.' || part == '..') ||
      (fileName != null && parts.last != fileName)) {
    throw const FormatException('Invalid private folder path');
  }
  return path;
}
