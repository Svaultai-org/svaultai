

import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;


class VideoRecorder {
  html.MediaStream? _stream;
  html.MediaRecorder? _recorder;
  final List<html.Blob> _chunks = [];
  Completer<Uint8List?>? _stopCompleter;

  
  Future<bool> requestPermission() async {
    try {
      _stream = await html.window.navigator.mediaDevices!.getUserMedia({
        'video': true,
        'audio': true,
      });
      return true;
    } catch (_) {
      _stream = null;
      return false;
    }
  }

  
  void registerPreview(String viewType) {
    final stream = _stream;
    if (stream == null) return;
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final video = html.VideoElement()
        ..autoplay = true
        ..muted = true 
        ..setAttribute('playsinline', 'true')
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.objectFit = 'cover'
        ..style.background = '#000'
        ..srcObject = stream;
      return video;
    });
  }

  
  void start() {
    final stream = _stream;
    if (stream == null) return;
    _chunks.clear();
    _recorder = html.MediaRecorder(stream);
    _recorder!.addEventListener('dataavailable', (html.Event event) {
      final blob = (event as html.BlobEvent).data;
      if (blob != null) _chunks.add(blob);
    });
    _recorder!.addEventListener('stop', (html.Event event) {
      final completer = _stopCompleter;
      if (completer == null || completer.isCompleted) return;
      if (_chunks.isEmpty) {
        completer.complete(null);
        return;
      }
      final mime = _chunks.first.type.isEmpty
          ? 'video/webm'
          : _chunks.first.type;
      final combined = html.Blob(_chunks, mime);
      final reader = html.FileReader();
      reader.onLoad.first.then((_) {
        final result = reader.result;
        if (result is List<int>) {
          completer.complete(Uint8List.fromList(result));
        } else if (result is ByteBuffer) {
          completer.complete(result.asUint8List());
        } else {
          completer.complete(null);
        }
      });
      reader.onError.first.then((_) => completer.complete(null));
      reader.readAsArrayBuffer(combined);
    });
    _recorder!.start();
  }

  
  Future<Uint8List?> stop() async {
    final recorder = _recorder;
    if (recorder == null) {
      _releaseStream();
      return null;
    }
    _stopCompleter = Completer<Uint8List?>();
    try {
      recorder.stop();
    } catch (_) {
      _stopCompleter!.complete(null);
    }
    final bytes = await _stopCompleter!.future;
    _releaseStream();
    return bytes;
  }

  
  void cancel() {
    final completer = _stopCompleter;
    if (completer != null && !completer.isCompleted) {
      completer.complete(null);
    }
    final recorder = _recorder;
    if (recorder != null) {
      try {
        recorder.stop();
      } catch (_) {}
    }
    _releaseStream();
  }

  void _releaseStream() {
    final stream = _stream;
    if (stream != null) {
      for (final track in stream.getTracks()) {
        try {
          track.stop();
        } catch (_) {}
      }
    }
    _stream = null;
    _recorder = null;
    _chunks.clear();
  }

  void dispose() => cancel();
}
