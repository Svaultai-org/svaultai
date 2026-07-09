

import 'dart:html' as html;
import 'dart:typed_data';


class FileDownloader {
  bool downloadBytes({
    required Uint8List bytes,
    required String fileName,
    required String? mimeType,
  }) {
    String? blobUrl;
    try {
      final mime = (mimeType == null || mimeType.isEmpty)
          ? 'application/octet-stream'
          : mimeType;
      final blob = html.Blob([bytes], mime);
      blobUrl = html.Url.createObjectUrlFromBlob(blob);
      final anchor = html.AnchorElement(href: blobUrl)
        ..download = fileName
        
        
        ..rel = 'noopener'
        ..style.display = 'none';
      html.document.body?.append(anchor);
      anchor.click();
      anchor.remove();
      return true;
    } catch (_) {
      return false;
    } finally {
      if (blobUrl != null) {
        try {
          html.Url.revokeObjectUrl(blobUrl);
        } catch (_) {}
      }
    }
  }

  bool openBytesInBrowser({
    required Uint8List bytes,
    required String fileName,
    required String? mimeType,
  }) {
    String? blobUrl;
    try {
      final mime = (mimeType == null || mimeType.isEmpty)
          ? 'application/octet-stream'
          : mimeType;
      final blob = html.Blob([bytes], mime);
      blobUrl = html.Url.createObjectUrlFromBlob(blob);
      
      
      html.window.open(blobUrl, '_blank');
      
      
      final urlToRevoke = blobUrl;
      Future<void>.delayed(const Duration(seconds: 60), () {
        try {
          html.Url.revokeObjectUrl(urlToRevoke);
        } catch (_) {}
      });
      blobUrl = null;
      return true;
    } catch (_) {
      return false;
    } finally {
      if (blobUrl != null) {
        try {
          html.Url.revokeObjectUrl(blobUrl);
        } catch (_) {}
      }
    }
  }
}
