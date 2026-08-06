import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

class VideoCaptureDevice {
  final String deviceId;
  final String label;
  final String kind;

  const VideoCaptureDevice({
    required this.deviceId,
    required this.label,
    required this.kind,
  });
}

class VideoRecorder {
  html.MediaStream? _stream;
  html.MediaRecorder? _recorder;
  final List<html.Blob> _chunks = [];
  Completer<Uint8List?>? _stopCompleter;
  html.VideoElement? _previewElement;
  html.VideoElement? _reviewElement;
  String? _reviewUrl;
  final List<String> _lastTrackStates = [];
  final StreamController<String> _mediaErrors =
      StreamController<String>.broadcast();
  final List<StreamSubscription<html.Event>> _trackSubscriptions = [];
  String _lastErrorMessage = '';

  String get lastErrorMessage => _lastErrorMessage.isEmpty
      ? 'Camera permission is required to record video.'
      : _lastErrorMessage;
  Stream<String> get mediaErrors => _mediaErrors.stream;

  Future<bool> requestPermission({
    String? videoDeviceId,
    String? audioDeviceId,
    int? width,
    int? height,
    String? facingMode,
    int? frameRate,
  }) async {
    _releaseStream();
    _lastTrackStates.clear();
    _lastErrorMessage = '';
    final video = <String, dynamic>{
      if (videoDeviceId != null && videoDeviceId.isNotEmpty)
        'deviceId': {'exact': videoDeviceId},
      if (width != null) 'width': {'ideal': width},
      if (height != null) 'height': {'ideal': height},
      if (facingMode != null && facingMode.isNotEmpty)
        'facingMode': {'ideal': facingMode},
      if (frameRate != null) 'frameRate': {'ideal': frameRate},
    };
    try {
      final audio = audioDeviceId == null || audioDeviceId.isEmpty
          ? true
          : <String, dynamic>{
              'deviceId': {'exact': audioDeviceId},
            };
      _stream = await html.window.navigator.mediaDevices!.getUserMedia({
        'video': video,
        'audio': audio,
      });
      _listenForEndedTracks();
      return true;
    } on html.DomException catch (error) {
      final name = error.name.toLowerCase();
      if (name.contains('notfound') || name.contains('devicesnotfound')) {
        try {
          _stream = await html.window.navigator.mediaDevices!.getUserMedia({
            'video': video,
            'audio': false,
          });
          _listenForEndedTracks();
          return true;
        } catch (_) {
          // The video-only retry also failed: report the original safe
          // no-device category below.
        }
      }
      if (name.contains('notallowed') || name.contains('permission')) {
        _lastErrorMessage =
            'Camera permission is required. Allow access in your browser settings, then retry.';
      } else if (name.contains('notfound') ||
          name.contains('devicesnotfound')) {
        _lastErrorMessage = 'No camera is available on this device.';
      } else if (name.contains('notreadable') || name.contains('trackstart')) {
        _lastErrorMessage =
            'The camera is busy or unavailable. Close other camera applications, then retry.';
      } else if (name.contains('overconstrained')) {
        _lastErrorMessage =
            'The selected camera does not support these settings. Choose another option and retry.';
      } else {
        _lastErrorMessage =
            'The browser could not start the camera. Check site settings and retry.';
      }
      _stream = null;
      return false;
    } catch (_) {
      _lastErrorMessage =
          'Camera recording is unavailable in this browser. Check browser support and site settings.';
      _stream = null;
      return false;
    }
  }

  void _listenForEndedTracks() {
    for (final subscription in _trackSubscriptions) {
      subscription.cancel();
    }
    _trackSubscriptions.clear();
    for (final track
        in _stream?.getTracks() ?? const <html.MediaStreamTrack>[]) {
      _trackSubscriptions.add(track.onEnded.listen((_) {
        if (!_mediaErrors.isClosed) {
          _mediaErrors.add(
            'A camera or microphone was disconnected. Reconnect it and retry.',
          );
        }
      }));
    }
  }

  Future<List<VideoCaptureDevice>> enumerateDevices() async {
    final mediaDevices = html.window.navigator.mediaDevices;
    if (mediaDevices == null) return const [];
    final devices = await mediaDevices.enumerateDevices();
    return devices
        .where((device) =>
            device.kind == 'videoinput' || device.kind == 'audioinput')
        .map((device) => VideoCaptureDevice(
              deviceId: device.deviceId ?? '',
              label: (device.label ?? '').trim(),
              kind: device.kind ?? '',
            ))
        .toList(growable: false);
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
        ..style.objectFit = 'contain'
        ..style.background = '#000'
        ..style.pointerEvents = 'none'
        ..srcObject = stream;
      _previewElement = video;
      return video;
    });
  }

  void registerRecordingPreview(
    String viewType,
    Uint8List bytes, {
    String mimeType = 'video/webm',
  }) {
    _revokeReviewUrl();
    final blob = html.Blob([bytes], mimeType);
    final url = html.Url.createObjectUrlFromBlob(blob);
    _reviewUrl = url;
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final video = html.VideoElement()
        ..controls = true
        ..setAttribute('playsinline', 'true')
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.objectFit = 'contain'
        ..style.background = '#000'
        ..src = url;
      _reviewElement = video;
      return video;
    });
  }

  void setReviewInteractionEnabled(bool enabled) {
    _reviewElement?.style.pointerEvents = enabled ? 'auto' : 'none';
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
      final mime =
          _chunks.first.type.isEmpty ? 'video/webm' : _chunks.first.type;
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
    _revokeReviewUrl();
  }

  void setCameraEnabled(bool enabled) {
    for (final track
        in _stream?.getVideoTracks() ?? const <html.MediaStreamTrack>[]) {
      track.enabled = enabled;
    }
  }

  void setMicrophoneEnabled(bool enabled) {
    for (final track
        in _stream?.getAudioTracks() ?? const <html.MediaStreamTrack>[]) {
      track.enabled = enabled;
    }
  }

  List<String> get trackStates => List.unmodifiable(
        _stream?.getTracks().map((track) => track.readyState).toList() ??
            _lastTrackStates,
      );

  void _releaseStream() {
    for (final subscription in _trackSubscriptions) {
      subscription.cancel();
    }
    _trackSubscriptions.clear();
    final stream = _stream;
    if (stream != null) {
      for (final track in stream.getTracks()) {
        try {
          track.stop();
        } catch (_) {}
        _lastTrackStates.add(track.readyState ?? 'ended');
      }
    }
    if (_previewElement != null) {
      _previewElement!.srcObject = null;
      _previewElement!.remove();
      _previewElement = null;
    }
    _stream = null;
    _recorder = null;
    _chunks.clear();
  }

  void _revokeReviewUrl() {
    if (_reviewElement != null) {
      _reviewElement!
        ..pause()
        ..removeAttribute('src')
        ..load()
        ..remove();
      _reviewElement = null;
    }
    final url = _reviewUrl;
    if (url != null) html.Url.revokeObjectUrl(url);
    _reviewUrl = null;
  }

  void dispose() {
    cancel();
    _mediaErrors.close();
  }
}
