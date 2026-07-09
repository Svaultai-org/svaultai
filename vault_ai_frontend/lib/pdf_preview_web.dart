

import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;


class VaultPdfPreviewer {
  String? _blobUrl;

  
  bool get available => true;

  
  bool register({
    required String viewType,
    required Uint8List bytes,
  }) {
    try {
      final blob = html.Blob([bytes], 'application/pdf');
      _blobUrl = html.Url.createObjectUrlFromBlob(blob);
    } catch (_) {
      _blobUrl = null;
      return false;
    }
    final url = _blobUrl;
    if (url == null) return false;

    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = url
        ..style.border = '0'
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.background = '#1A1A1A';
      
      
      iframe.setAttribute(
        'sandbox',
        
        
        'allow-same-origin allow-scripts',
      );
      iframe.setAttribute('referrerpolicy', 'no-referrer');
      return iframe;
    });
    return true;
  }

  
  void dispose() {
    final url = _blobUrl;
    if (url != null) {
      try {
        html.Url.revokeObjectUrl(url);
      } catch (_) {}
    }
    _blobUrl = null;
  }
}
