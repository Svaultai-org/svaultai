

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/main.dart' show
    generateVoiceRecordingFilename, kAcceptedAudioExtensions;


String _readLib(String relative) {
  final file = File('lib/$relative');
  expect(file.existsSync(), isTrue,
      reason: 'expected file does not exist: ${file.path}');
  return file.readAsStringSync();
}


void main() {
  group('kAcceptedAudioExtensions', () {
    test('includes the five promised formats', () {
      
      
      for (final ext in ['mp3', 'm4a', 'wav', 'aac', 'ogg']) {
        expect(
          kAcceptedAudioExtensions, contains(ext),
          reason: 'must accept .$ext',
        );
      }
    });

    test('contains no dot prefix', () {
      
      
      for (final ext in kAcceptedAudioExtensions) {
        expect(
          ext.startsWith('.'),
          isFalse,
          reason: 'extension "$ext" must not start with a dot — '
                  'FilePicker filters on bare extensions',
        );
      }
    });

    test('all lowercase', () {
      
      for (final ext in kAcceptedAudioExtensions) {
        expect(
          ext, equals(ext.toLowerCase()),
          reason: 'extension "$ext" must be lowercase',
        );
      }
    });
  });

  group('generateVoiceRecordingFilename', () {
    test('produces the canonical "Voice recording - <date> <time>" '
        'shape', () {
      
      final ts = DateTime(2026, 6, 6, 14, 32, 8);
      expect(
        generateVoiceRecordingFilename(now: ts),
        'Voice recording - 2026-06-06 14-32-08.m4a',
      );
    });

    test('pads single-digit month/day/hour/minute/second', () {
      
      
      final ts = DateTime(2026, 1, 3, 1, 2, 3);
      expect(
        generateVoiceRecordingFilename(now: ts),
        'Voice recording - 2026-01-03 01-02-03.m4a',
      );
    });

    test('uses dashes instead of colons in the time component', () {
      
      
      final ts = DateTime(2026, 6, 6, 14, 32, 8);
      final name = generateVoiceRecordingFilename(now: ts);
      expect(name.contains(':'), isFalse,
          reason: 'colons break on Windows');
      expect(name, contains('14-32-08'));
    });

    test('honors the extension parameter', () {
      
      
      final ts = DateTime(2026, 6, 6, 14, 32, 8);
      expect(
        generateVoiceRecordingFilename(now: ts, extension: 'ogg'),
        'Voice recording - 2026-06-06 14-32-08.ogg',
      );
    });

    test('default extension is m4a', () {
      
      
      final ts = DateTime(2026, 6, 6, 14, 32, 8);
      expect(
        generateVoiceRecordingFilename(now: ts).endsWith('.m4a'),
        isTrue,
      );
    });
  });

  group('Audio upload option mounted inside the + attachment menu', () {
    test('+ menu has an Upload audio entry that routes to _pickAudio',
        () {
      
      
      final src = _readLib('main.dart');
      expect(
        src,
        contains("Icon(Icons.audiotrack)"),
        reason: 'an audiotrack-icon entry must exist in the + menu',
      );
      expect(
        src.contains("Text('Upload audio')") ||
            src.contains('filesUploadAudio'),
        isTrue,
        reason:
            'menu entry must carry "Upload audio" label (literal '
            'or via AppLocalizations.filesUploadAudio)',
      );
      expect(
        src,
        contains("case 'audio':"),
        reason: 'menu must route the audio option',
      );
      expect(
        src,
        contains('await _pickAudio();'),
        reason: 'audio option must invoke _pickAudio',
      );
    });
  });

  group('_pickAudio implementation', () {
    test('uses FileType.custom with the extension whitelist', () {
      
      
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> _pickAudio()');
      expect(idx, greaterThan(-1),
          reason: 'main.dart must declare _pickAudio()');
      final window = src.substring(
        idx,
        (idx + 2000).clamp(0, src.length),
      );
      expect(window, contains('FileType.custom'));
      expect(
        window,
        contains('allowedExtensions: kAcceptedAudioExtensions'),
        reason: 'picker must reference the canonical constant so a '
                'new format added to the list automatically reaches '
                'the dialog filter',
      );
      expect(
        window,
        contains('allowMultiple: true'),
        reason: 'audio picker must support multi-select like the '
                'other picker entry points',
      );
    });

    test('routes picked files through _ingestPickedFiles with kind '
        '"audio"', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> _pickAudio()');
      final window = src.substring(
        idx,
        (idx + 2000).clamp(0, src.length),
      );
      expect(
        window,
        contains("_ingestPickedFiles(result.files, kind: 'audio')"),
        reason: '_pickAudio must hand off to the shared ingest path '
                'with the audio kind tag',
      );
    });
  });

  group('Recorder filename uses generateVoiceRecordingFilename', () {
    test('the in-app recorder no longer uses the legacy '
        '"recording_<epoch>.m4a" shape', () {
      
      
      final src = _readLib('main.dart');
      expect(
        src.contains("'recording_\${DateTime.now().millisecondsSinceEpoch}.m4a'"),
        isFalse,
        reason: 'recorder must use generateVoiceRecordingFilename(), '
                'not the epoch-ms shape',
      );
      
      expect(
        src,
        contains('generateVoiceRecordingFilename(now: DateTime.now())'),
        reason: 'the recorder must produce its filename through the '
                'shared helper',
      );
    });
  });

  group('Native recording and capture guards', () {
    test('voice recorder uses platform storage instead of URL-fetching '
        'native file paths', () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains('createRecordingStorage()'),
        reason: 'chat screen must initialize the conditional recording '
            'storage helper',
      );
      expect(
        src,
        contains('await _recordingStorage.audioPath(recordingName)'),
        reason: 'native audio capture needs an app-private temp path',
      );
      expect(
        src,
        contains('await _recordingStorage.readAndMaybeDelete(path)'),
        reason: 'native recordings must be read locally and cleaned up',
      );
      expect(
        src,
        isNot(contains('http.get(Uri.parse(path))')),
        reason: 'Android recorder paths are local files, not URLs',
      );
    });

    test('record voice action is awaited and permission-gated', () {
      final src = _readLib('main.dart');
      expect(src, contains("case 'voice':"));
      expect(
        src,
        contains('await _toggleRecording();'),
        reason: 'plugin exceptions must stay in the local menu handler',
      );
      expect(
        src,
        contains('Permission.microphone.request()'),
        reason: 'microphone permission must be requested only for voice '
            'recording/capture actions',
      );
      expect(src, contains('openAppSettings'));
    });

    test('Android camera capture uses native media capture service', () {
      final src = _readLib('main.dart');
      expect(src, contains('createNativeMediaCaptureService()'));
      expect(src, contains("case 'take_photo':"));
      expect(src, contains('await _captureNativePhoto();'));
      expect(src, contains("case 'record_video':"));
      expect(src, contains('await _toggleVideoRecording();'));
      expect(src, contains('!kIsWeb && _nativeMediaCapture.isSupported'));
    });

    test('native capture implementation uses camera source only in IO file',
        () {
      final src = _readLib('services/native_media_capture_io.dart');
      expect(src, contains('ImageSource.camera'));
      expect(src, contains('capturePhoto()'));
      expect(src, contains('captureVideo()'));
      expect(src, contains("kind: 'image'"));
      expect(src, contains("kind: 'video'"));
    });
  });
}
