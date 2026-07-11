

import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/foundation.dart';


class MediaPlayer {
  String? _blobUrl;

  // Live listeners on the underlying <video>/<audio> element. Retained
  // so dispose() can cancel them — leaving them attached would keep
  // the DOM element referenced past the dialog's lifetime and, more
  // importantly, keep pushing MediaErrors into an errorNotifier whose
  // dialog no longer exists.
  final List<StreamSubscription<html.Event>> _errorSubs =
      <StreamSubscription<html.Event>>[];

  // Caller-observable error state. When the underlying element fires
  // an `error` event (bad codec, mid-playback decode failure, or the
  // race between dispose()'s blob-URL revocation and the platform
  // view still being attached), we surface a human-readable string
  // on this notifier. The dialog builder subscribes to it and paints
  // a controlled error banner. The listener also swallows the browser
  // event so it can't bubble to window.onerror — that unhandled path
  // was the observed trigger for the Flutter web shell reload.
  final ValueNotifier<String?> errorNotifier =
      ValueNotifier<String?>(null);

  bool _disposed = false;

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
        final v = html.VideoElement()
          ..controls = true
          ..autoplay = false
          ..preload = 'metadata'
          ..setAttribute('playsinline', 'true')
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.background = '#000'
          ..src = url;
        _errorSubs.add(v.onError.listen((_) {
          if (_disposed) return;
          errorNotifier.value = _readMediaError(v.error);
        }));
        return v;
      }
      final a = html.AudioElement()
        ..controls = true
        ..autoplay = false
        ..preload = 'metadata'
        ..style.width = '100%'
        ..src = url;
      _errorSubs.add(a.onError.listen((_) {
        if (_disposed) return;
        errorNotifier.value = _readMediaError(a.error);
      }));
      return a;
    });
    return true;
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    // Cancel every onError subscription BEFORE the blob URL is
    // revoked so a late-fired error can't reach a disposed notifier
    // or a torn-down dialog.
    for (final sub in _errorSubs) {
      try {
        sub.cancel();
      } catch (_) {}
    }
    _errorSubs.clear();
    final url = _blobUrl;
    if (url != null) {
      try {
        html.Url.revokeObjectUrl(url);
      } catch (_) {}
    }
    _blobUrl = null;
    try {
      errorNotifier.dispose();
    } catch (_) {}
  }

  static String _readMediaError(html.MediaError? e) {
    if (e == null) return 'Playback failed.';
    switch (e.code) {
      case 1:
        return 'Playback was aborted.';
      case 2:
        return 'A network error interrupted playback.';
      case 3:
        return 'This file could not be decoded by the browser.';
      case 4:
        return 'This format is not supported by your browser.';
      default:
        return 'Playback failed (code ${e.code}).';
    }
  }
}
