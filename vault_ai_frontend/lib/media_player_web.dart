

import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;


class MediaPlayer {
  String? _blobUrl;

  
  static bool canPlay({required String? mimeType, required bool isVideo}) {
    final mt = (mimeType ?? '').trim();
    if (mt.isEmpty) return false;
    try {
      final probe = isVideo ? html.VideoElement() : html.AudioElement();
      final result = probe.canPlayType(mt);
      return result.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  
  bool register({
    required String viewType,
    required Uint8List bytes,
    required String? mimeType,
    required bool isVideo,
  }) {
    try {
      final mime = (mimeType == null || mimeType.isEmpty)
          ? (isVideo ? 'video/webm' : 'audio/webm')
          : mimeType;
      final blob = html.Blob([bytes], mime);
      _blobUrl = html.Url.createObjectUrlFromBlob(blob);
    } catch (_) {
      _blobUrl = null;
      return false;
    }
    final url = _blobUrl;
    if (url == null) return false;

    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      if (isVideo) {
        return html.VideoElement()
          ..controls = true
          ..autoplay = false
          ..preload = 'metadata'
          ..setAttribute('playsinline', 'true')
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.background = '#000'
          ..src = url;
      }
      return html.AudioElement()
        ..controls = true
        ..autoplay = false
        ..preload = 'metadata'
        ..style.width = '100%'
        ..src = url;
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
