

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

const String _mainDartRel = 'lib/main.dart';

String _readMain() => File(_mainDartRel).readAsStringSync();

void main() {
  group('production_deployment_readiness', () {
    test('R1: release-mode HTTPS hard guard exists in main()', () {
      final src = _readMain();
      
      expect(
        src.contains('kReleaseMode'),
        isTrue,
        reason: 'main.dart must reference kReleaseMode for the boot guard',
      );
      expect(
        src.contains("!backendBaseUrl.startsWith('https://')"),
        isTrue,
        reason: 'main() must hard-fail when a release build is pointed at a '
            'non-HTTPS backend; otherwise auth tokens would ship in plaintext.',
      );
      
      
      expect(
        src.contains('BACKEND_BASE_URL=') ||
            src.contains('--dart-define=BACKEND_BASE_URL'),
        isTrue,
        reason: 'release-mode HTTPS guard must include the --dart-define '
            'remediation hint in its error message.',
      );
    });

    test('R2: backendBaseUrl is read via String.fromEnvironment', () {
      final src = _readMain();
      
      
      expect(
        src.contains("String.fromEnvironment("),
        isTrue,
        reason: 'main.dart must use String.fromEnvironment for the API URL',
      );
      expect(
        src.contains("'BACKEND_BASE_URL'"),
        isTrue,
        reason: 'main.dart must use the BACKEND_BASE_URL env key so the '
            'deployment runbook can document a single --dart-define flag.',
      );
    });

    test('R3: no hidden fallback that survives release without HTTPS', () {
      
      
      final src = _readMain();
      
      
      final lines = src.split('\n');
      var seenDefaultValue = false;
      for (var i = 0; i < lines.length; i++) {
        final raw = lines[i];
        final trimmed = raw.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('///')) {
          continue;
        }
        if (!raw.contains('localhost') && !raw.contains('127.0.0.1')) {
          continue;
        }
        
        
        if (raw.contains("defaultValue: 'http://localhost:8000'") ||
            raw.contains('defaultValue: "http://localhost:8000"')) {
          seenDefaultValue = true;
          continue;
        }
        
        final lo = (i - 6).clamp(0, lines.length);
        final priorWindow = lines.sublist(lo, i + 1).join('\n');
        final isDevGated = priorWindow.contains('kDebugMode') ||
            priorWindow.contains('!kReleaseMode') ||
            priorWindow.contains('kIsWeb');
        if (isDevGated) continue;
        fail(
          'main.dart line ${i + 1} references localhost / 127.0.0.1 outside '
          'a kDebugMode / !kReleaseMode / kIsWeb gate and is NOT the '
          'documented String.fromEnvironment default:\n  $trimmed',
        );
      }
      expect(
        seenDefaultValue,
        isTrue,
        reason: 'main.dart must keep the documented '
            "String.fromEnvironment defaultValue: 'http://localhost:8000' "
            'so dev builds still work without --dart-define',
      );
    });

    test('R4: debugShowCheckedModeBanner is disabled in MaterialApp', () {
      final src = _readMain();
      expect(
        src.contains('debugShowCheckedModeBanner: false'),
        isTrue,
        reason: 'Release users must never see a "DEBUG" ribbon overlay.',
      );
    });

    test('R5: signOut() clears vault crypto cache + session', () {
      final src = _readMain();
      
      
      final signOutIdx = src.indexOf('Future<void> signOut(');
      expect(
        signOutIdx,
        greaterThan(-1),
        reason: 'main.dart must declare signOut() on AppState',
      );
      
      final body = src.substring(
        signOutIdx,
        (signOutIdx + 2000).clamp(0, src.length),
      );
      expect(
        body.contains('_VaultCrypto.clearCache(') ||
            body.contains('VaultCrypto.clearCache('),
        isTrue,
        reason: 'signOut() must wipe the per-vault crypto cache so a '
            'subsequent sign-in does not reuse a cached AES key.',
      );
      expect(
        body.contains('clearSession('),
        isTrue,
        reason: 'signOut() must call clearSession() so the persisted '
            'auth token + vault id are gone from local storage.',
      );
    });

    test('R6: api_client baseUrl is constructor-driven, not hardcoded', () {
      
      
      final clientPath = 'lib/api_client.dart';
      final src = File(clientPath).readAsStringSync();
      
      expect(
        src.contains('baseUrl'),
        isTrue,
        reason: 'api_client.dart must expose a baseUrl constructor arg',
      );
      
      final lines = src.split('\n');
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i].trim();
        if (line.startsWith('//') || line.startsWith('///')) continue;
        if (line.contains("'http://localhost") ||
            line.contains('"http://localhost') ||
            line.contains("'http://127.0.0.1") ||
            line.contains('"http://127.0.0.1')) {
          fail(
            'api_client.dart line ${i + 1} hardcodes a localhost URL '
            'that would survive into release builds:\n  $line',
          );
        }
      }
    });
  });
}
