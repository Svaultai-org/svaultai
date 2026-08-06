import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'video_recorder.dart';

enum WebVideoRecorderState {
  idle,
  requestingPermission,
  preview,
  recording,
  stopping,
  review,
  saving,
  error,
}

class WebVideoRecording {
  final Uint8List bytes;
  final String mimeType;

  const WebVideoRecording(this.bytes, {this.mimeType = 'video/webm'});
}

class WebVideoRecorderDialog extends StatefulWidget {
  final VideoRecorder recorder;

  const WebVideoRecorderDialog({super.key, required this.recorder});

  @override
  State<WebVideoRecorderDialog> createState() => _WebVideoRecorderDialogState();
}

class _WebVideoRecorderDialogState extends State<WebVideoRecorderDialog> {
  WebVideoRecorderState _state = WebVideoRecorderState.idle;
  List<VideoCaptureDevice> _devices = const [];
  String? _cameraId;
  String? _microphoneId;
  String? _previewViewType;
  String? _reviewViewType;
  Uint8List? _recordedBytes;
  String _error = '';
  bool _settingsOpen = false;
  bool _cameraEnabled = true;
  bool _microphoneEnabled = true;
  int _resolutionHeight = 720;
  int _frameRate = 30;
  Timer? _timer;
  StreamSubscription<String>? _mediaErrorSubscription;
  Duration _elapsed = Duration.zero;
  bool _closing = false;
  int _generation = 0;

  bool get _hasUnsavedRecording =>
      _state == WebVideoRecorderState.recording ||
      _state == WebVideoRecorderState.stopping ||
      (_state == WebVideoRecorderState.review && _recordedBytes != null);

  List<VideoCaptureDevice> get _cameras =>
      _devices.where((device) => device.kind == 'videoinput').toList();
  List<VideoCaptureDevice> get _microphones =>
      _devices.where((device) => device.kind == 'audioinput').toList();

  @override
  void initState() {
    super.initState();
    _mediaErrorSubscription = widget.recorder.mediaErrors.listen((message) {
      if (!mounted || _closing) return;
      _timer?.cancel();
      widget.recorder.cancel();
      setState(() {
        _state = WebVideoRecorderState.error;
        _error = message;
        _previewViewType = null;
      });
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _requestPermission());
  }

  Future<void> _requestPermission() async {
    final generation = ++_generation;
    setState(() {
      _state = WebVideoRecorderState.requestingPermission;
      _error = '';
      _reviewViewType = null;
      _recordedBytes = null;
    });
    final granted = await widget.recorder.requestPermission(
      videoDeviceId: _cameraId,
      audioDeviceId: _microphoneId,
      width: _resolutionHeight == 1080 ? 1920 : 1280,
      height: _resolutionHeight,
      frameRate: _frameRate,
    );
    if (!mounted || generation != _generation || _closing) return;
    if (!granted) {
      setState(() {
        _state = WebVideoRecorderState.error;
        _error = widget.recorder.lastErrorMessage;
      });
      return;
    }
    try {
      _devices = await widget.recorder.enumerateDevices();
    } catch (_) {
      _devices = const [];
    }
    if (!mounted || generation != _generation || _closing) return;
    final cameras = _cameras;
    if (cameras.isEmpty) {
      widget.recorder.cancel();
      setState(() {
        _state = WebVideoRecorderState.error;
        _error = 'No camera is available on this device.';
      });
      return;
    }
    _cameraId ??= cameras.first.deviceId;
    if (_microphones.isNotEmpty) {
      _microphoneId ??= _microphones.first.deviceId;
    }
    final viewType = 'svaultai-video-preview-$generation';
    widget.recorder.registerPreview(viewType);
    setState(() {
      _previewViewType = viewType;
      _state = WebVideoRecorderState.preview;
      _cameraEnabled = true;
      _microphoneEnabled = _microphones.isNotEmpty;
    });
  }

  void _startRecording() {
    if (_state != WebVideoRecorderState.preview) return;
    try {
      widget.recorder.start();
    } catch (_) {
      setState(() {
        _state = WebVideoRecorderState.error;
        _error = 'The camera could not start recording. It may be busy.';
      });
      return;
    }
    _elapsed = Duration.zero;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _state == WebVideoRecorderState.recording) {
        setState(() => _elapsed += const Duration(seconds: 1));
      }
    });
    setState(() => _state = WebVideoRecorderState.recording);
  }

  Future<void> _stopRecording() async {
    if (_state != WebVideoRecorderState.recording) return;
    _timer?.cancel();
    setState(() => _state = WebVideoRecorderState.stopping);
    final bytes = await widget.recorder.stop();
    if (!mounted || _closing) return;
    if (bytes == null || bytes.isEmpty) {
      setState(() {
        _state = WebVideoRecorderState.error;
        _error = 'The recording was empty. Please retake the video.';
      });
      return;
    }
    final viewType = 'svaultai-video-review-${++_generation}';
    widget.recorder.registerRecordingPreview(viewType, bytes);
    setState(() {
      _recordedBytes = bytes;
      _reviewViewType = viewType;
      _previewViewType = null;
      _state = WebVideoRecorderState.review;
    });
  }

  Future<void> _retake() async {
    if (_state != WebVideoRecorderState.review) return;
    widget.recorder.cancel();
    await _requestPermission();
  }

  void _save() {
    final bytes = _recordedBytes;
    if (_state != WebVideoRecorderState.review || bytes == null || _closing) {
      return;
    }
    setState(() => _state = WebVideoRecorderState.saving);
    _closing = true;
    _timer?.cancel();
    Navigator.of(context).pop(WebVideoRecording(bytes));
  }

  Future<void> _requestExit() async {
    if (_closing) return;
    if (_hasUnsavedRecording) {
      final reviewWasInteractive = _state == WebVideoRecorderState.review;
      if (reviewWasInteractive) {
        widget.recorder.setReviewInteractionEnabled(false);
      }
      final discard = await showDialog<bool>(
        context: context,
        useRootNavigator: false,
        barrierDismissible: false,
        builder: (dialogContext) => AlertDialog(
          key: const Key('web_video_discard_dialog'),
          title: const Text('Discard this recording?'),
          actions: [
            TextButton(
              key: const Key('web_video_keep_recording'),
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Keep recording'),
            ),
            FilledButton(
              key: const Key('web_video_discard_exit'),
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('Discard and exit'),
            ),
          ],
        ),
      );
      if (discard != true) {
        if (reviewWasInteractive) {
          widget.recorder.setReviewInteractionEnabled(true);
        }
        return;
      }
    }
    _closing = true;
    ++_generation;
    _timer?.cancel();
    widget.recorder.cancel();
    if (mounted) Navigator.of(context).pop();
  }

  void _toggleCamera() {
    if (_state != WebVideoRecorderState.preview &&
        _state != WebVideoRecorderState.recording) return;
    _cameraEnabled = !_cameraEnabled;
    widget.recorder.setCameraEnabled(_cameraEnabled);
    setState(() {});
  }

  void _toggleMicrophone() {
    if (_state != WebVideoRecorderState.preview &&
        _state != WebVideoRecorderState.recording) return;
    _microphoneEnabled = !_microphoneEnabled;
    widget.recorder.setMicrophoneEnabled(_microphoneEnabled);
    setState(() {});
  }

  Future<void> _switchCamera() async {
    final cameras = _cameras;
    if (cameras.length < 2 || _state != WebVideoRecorderState.preview) return;
    final current =
        cameras.indexWhere((device) => device.deviceId == _cameraId);
    _cameraId = cameras[(current + 1) % cameras.length].deviceId;
    await _requestPermission();
  }

  String _deviceLabel(VideoCaptureDevice device, int index, String noun) {
    return device.label.isNotEmpty ? device.label : '$noun ${index + 1}';
  }

  String get _elapsedLabel {
    final minutes = _elapsed.inMinutes.toString().padLeft(2, '0');
    final seconds = (_elapsed.inSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  void dispose() {
    _timer?.cancel();
    _mediaErrorSubscription?.cancel();
    widget.recorder.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final compact = size.width < 600 || size.height < 620;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) unawaited(_requestExit());
      },
      child: CallbackShortcuts(
        bindings: <ShortcutActivator, VoidCallback>{
          const SingleActivator(LogicalKeyboardKey.escape): () =>
              unawaited(_requestExit()),
        },
        child: Focus(
          autofocus: true,
          child: Dialog.fullscreen(
            backgroundColor: const Color(0xFF0F1115),
            child: SafeArea(
              child: Column(
                children: [
                  _buildTopBar(),
                  if (_settingsOpen) _buildSettings(compact),
                  Expanded(child: _buildPreview()),
                  _buildBottomControls(compact),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTopBar() => Material(
        color: const Color(0xFF171A20),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(
            children: [
              IconButton(
                key: const Key('web_video_close'),
                tooltip: 'Close recorder',
                onPressed: _requestExit,
                icon: const Icon(Icons.close),
              ),
              const Expanded(
                child: Text(
                  'Video Evidence',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
              ),
              if (_state == WebVideoRecorderState.recording) ...[
                const Icon(Icons.fiber_manual_record, color: Colors.redAccent),
                Semantics(
                  identifier: 'web_video_elapsed',
                  label: _elapsedLabel,
                  child: Text(
                    _elapsedLabel,
                    key: const Key('web_video_elapsed'),
                  ),
                ),
                const SizedBox(width: 8),
              ],
              TextButton.icon(
                key: const Key('web_video_settings'),
                onPressed: _state == WebVideoRecorderState.recording ||
                        _state == WebVideoRecorderState.stopping
                    ? null
                    : () => setState(() => _settingsOpen = !_settingsOpen),
                icon: const Icon(Icons.settings_outlined),
                label: const Text('Settings'),
              ),
            ],
          ),
        ),
      );

  Widget _buildPreview() {
    Widget child;
    if (_state == WebVideoRecorderState.requestingPermission) {
      child = const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('Requesting camera and microphone permission…'),
          ],
        ),
      );
    } else if (_state == WebVideoRecorderState.error) {
      child = Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.videocam_off_outlined, size: 54),
                const SizedBox(height: 16),
                Text(_error, key: const Key('web_video_error')),
                const SizedBox(height: 12),
                const Text(
                  'Check the browser site settings, close other camera apps, '
                  'then retry.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 18),
                Wrap(
                  spacing: 12,
                  children: [
                    OutlinedButton(
                      key: const Key('web_video_error_cancel'),
                      onPressed: _requestExit,
                      child: const Text('Cancel'),
                    ),
                    FilledButton.icon(
                      key: const Key('web_video_retry'),
                      onPressed: _requestPermission,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Retry'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
    } else if (_state == WebVideoRecorderState.review &&
        _reviewViewType != null) {
      child = HtmlElementView(viewType: _reviewViewType!);
    } else if (_previewViewType != null) {
      child = HtmlElementView(viewType: _previewViewType!);
    } else {
      child = const Center(child: Text('Preparing camera…'));
    }
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1100),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: ColoredBox(
              color: Colors.black,
              child: AspectRatio(aspectRatio: 16 / 9, child: child),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSettings(bool compact) {
    final cameraItems = <DropdownMenuItem<String>>[
      for (var i = 0; i < _cameras.length; i++)
        DropdownMenuItem(
          value: _cameras[i].deviceId,
          child: Text(_deviceLabel(_cameras[i], i, 'Camera')),
        ),
    ];
    final microphoneItems = <DropdownMenuItem<String>>[
      for (var i = 0; i < _microphones.length; i++)
        DropdownMenuItem(
          value: _microphones[i].deviceId,
          child: Text(_deviceLabel(_microphones[i], i, 'Microphone')),
        ),
    ];
    final fields = <Widget>[
      Semantics(
        container: true,
        identifier: 'web_video_camera_selector',
        label: 'Camera selector',
        child: DropdownButtonFormField<String>(
          key: const Key('web_video_camera_selector'),
          value: cameraItems.any((item) => item.value == _cameraId)
              ? _cameraId
              : null,
          items: cameraItems,
          decoration: const InputDecoration(labelText: 'Camera'),
          onChanged: (value) => setState(() => _cameraId = value),
        ),
      ),
      Semantics(
        container: true,
        identifier: 'web_video_microphone_selector',
        label: 'Microphone selector',
        child: DropdownButtonFormField<String>(
          key: const Key('web_video_microphone_selector'),
          value: microphoneItems.any((item) => item.value == _microphoneId)
              ? _microphoneId
              : null,
          items: microphoneItems,
          decoration: const InputDecoration(labelText: 'Microphone'),
          hint: Text(
              _microphones.isEmpty ? 'No microphone' : 'Select microphone'),
          onChanged: microphoneItems.isEmpty
              ? null
              : (value) => setState(() => _microphoneId = value),
        ),
      ),
      Semantics(
        container: true,
        identifier: 'web_video_resolution',
        label: 'Resolution selector',
        child: DropdownButtonFormField<int>(
          key: const Key('web_video_resolution'),
          value: _resolutionHeight,
          decoration: const InputDecoration(labelText: 'Resolution'),
          items: const [
            DropdownMenuItem(value: 720, child: Text('1280 × 720')),
            DropdownMenuItem(value: 1080, child: Text('1920 × 1080')),
          ],
          onChanged: (value) =>
              setState(() => _resolutionHeight = value ?? 720),
        ),
      ),
      Semantics(
        container: true,
        identifier: 'web_video_frame_rate',
        label: 'Frame rate selector',
        child: DropdownButtonFormField<int>(
          key: const Key('web_video_frame_rate'),
          value: _frameRate,
          decoration: const InputDecoration(labelText: 'Frame rate'),
          items: const [
            DropdownMenuItem(value: 24, child: Text('24 fps')),
            DropdownMenuItem(value: 30, child: Text('30 fps')),
          ],
          onChanged: (value) => setState(() => _frameRate = value ?? 30),
        ),
      ),
      FilledButton(
        key: const Key('web_video_apply_settings'),
        onPressed: _requestPermission,
        child: const Text('Apply'),
      ),
    ];
    return Material(
      color: const Color(0xFF20242C),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: compact
            ? Column(mainAxisSize: MainAxisSize.min, children: fields)
            : Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [for (final field in fields) Expanded(child: field)],
              ),
      ),
    );
  }

  Widget _buildBottomControls(bool compact) {
    final recording = _state == WebVideoRecorderState.recording;
    final preview = _state == WebVideoRecorderState.preview;
    final review = _state == WebVideoRecorderState.review;
    final controls = <Widget>[
      IconButton.filledTonal(
        key: const Key('web_video_camera_toggle'),
        tooltip: _cameraEnabled ? 'Turn camera off' : 'Turn camera on',
        onPressed: preview || recording ? _toggleCamera : null,
        icon: Icon(_cameraEnabled ? Icons.videocam : Icons.videocam_off),
      ),
      IconButton.filledTonal(
        key: const Key('web_video_microphone_toggle'),
        tooltip: _microphoneEnabled ? 'Mute microphone' : 'Unmute microphone',
        onPressed: (preview || recording) && _microphones.isNotEmpty
            ? _toggleMicrophone
            : null,
        icon: Icon(_microphoneEnabled ? Icons.mic : Icons.mic_off),
      ),
      if (_cameras.length > 1)
        IconButton.filledTonal(
          key: const Key('web_video_switch_camera'),
          tooltip: 'Switch camera',
          onPressed: preview ? _switchCamera : null,
          icon: const Icon(Icons.cameraswitch_outlined),
        ),
      if (preview)
        FilledButton.icon(
          key: const Key('web_video_start'),
          onPressed: _startRecording,
          icon: const Icon(Icons.fiber_manual_record),
          label: const Text('Start Recording'),
        ),
      if (recording)
        FilledButton.icon(
          key: const Key('web_video_stop'),
          style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
          onPressed: _stopRecording,
          icon: const Icon(Icons.stop),
          label: const Text('Stop Recording'),
        ),
      if (review) ...[
        OutlinedButton.icon(
          key: const Key('web_video_retake'),
          onPressed: _retake,
          icon: const Icon(Icons.replay),
          label: const Text('Retake'),
        ),
        FilledButton.icon(
          key: const Key('web_video_save'),
          onPressed: _save,
          icon: const Icon(Icons.check),
          label: const Text('Save'),
        ),
      ],
      OutlinedButton(
        key: const Key('web_video_cancel'),
        onPressed: _requestExit,
        child: Text(review ? 'Discard' : 'Cancel'),
      ),
    ];
    return Material(
      color: const Color(0xFF171A20),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Wrap(
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: compact ? 8 : 14,
            runSpacing: 8,
            children: controls,
          ),
        ),
      ),
    );
  }
}
