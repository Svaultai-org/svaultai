

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


List<File> _libFiles() {
  final libDir = Directory('lib');
  expect(libDir.existsSync(), isTrue, reason: 'lib/ must exist');
  return libDir
      .listSync(recursive: true)
      .whereType<File>()
      .where((f) => f.path.endsWith('.dart'))
      .toList();
}


void main() {
  group('pubspec.yaml', () {
    test('no descope package dependency', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();
      
      
      final regex = RegExp(
        r'^\s*descope(_[a-z]+)?\s*:',
        multiLine: true,
      );
      expect(
        regex.hasMatch(pubspec),
        isFalse,
        reason: 'pubspec.yaml must not list the descope package',
      );
    });

    test('description does not advertise email OTP', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();
      final lines = pubspec.split('\n');
      final descLine = lines.firstWhere(
        (l) => l.startsWith('description:'),
        orElse: () => '',
      );
      expect(
        descLine.toLowerCase().contains('email otp'),
        isFalse,
        reason: 'pubspec description must not say "Email OTP" anymore',
      );
    });
  });

  group('lib/', () {
    test('no file imports package:descope', () {
      final offenders = <String>[];
      for (final f in _libFiles()) {
        final src = f.readAsStringSync();
        if (src.contains("import 'package:descope")) {
          offenders.add(f.path);
        }
      }
      expect(
        offenders, isEmpty,
        reason: 'descope import found in: ${offenders.join(", ")}',
      );
    });

    test('no Descope.* SDK call sites remain', () {
      final regex = RegExp(r'\bDescope\.[A-Za-z]+');
      final offenders = <String>[];
      for (final f in _libFiles()) {
        final src = f.readAsStringSync();
        
        
        for (final line in src.split('\n')) {
          if (regex.hasMatch(line)) {
            final trimmed = line.trim();
            final isComment = trimmed.startsWith('//') ||
                trimmed.startsWith('*') ||
                trimmed.startsWith('///');
            if (!isComment) {
              offenders.add('${f.path}: $trimmed');
            }
          }
        }
      }
      expect(
        offenders, isEmpty,
        reason: 'Descope SDK call site found in:\n  '
                '${offenders.join("\n  ")}',
      );
    });

    test('no DescopeSession / DescopeSessionManager / sessionJwt '
        'references in code', () {
      final symbols = ['DescopeSession', 'sessionJwt', 'sessionManager'];
      final offenders = <String>[];
      for (final f in _libFiles()) {
        final src = f.readAsStringSync();
        for (final line in src.split('\n')) {
          final trimmed = line.trim();
          final isComment = trimmed.startsWith('//') ||
              trimmed.startsWith('*') ||
              trimmed.startsWith('///');
          if (isComment) continue;
          for (final sym in symbols) {
            if (line.contains(sym)) {
              offenders.add('${f.path}: $trimmed');
              break;
            }
          }
        }
      }
      expect(
        offenders, isEmpty,
        reason: 'Descope session symbol found in code:\n  '
                '${offenders.join("\n  ")}',
      );
    });

    test('no email-OTP UI strings remain', () {
      
      final libCombined = _libFiles()
          .map((f) => f.readAsStringSync())
          .join('\n');
      final forbidden = <String>[
        'Enter the 6-digit code',
        "We'll send a code",
        "We'll send you a verification",
        
        'class AuthEmailOtpPage',
      ];
      for (final phrase in forbidden) {
        expect(
          libCombined.contains(phrase),
          isFalse,
          reason: 'forbidden email-OTP phrase remains in lib/: '
                  '"$phrase"',
        );
      }
    });

    test('Descope-era SharedPreferences key "vault_name_\$email" is gone',
        () {
      final offenders = <String>[];
      for (final f in _libFiles()) {
        final src = f.readAsStringSync();
        if (src.contains('vault_name_\$email') ||
            src.contains("'vault_name_'")) {
          offenders.add(f.path);
        }
      }
      expect(
        offenders, isEmpty,
        reason: 'legacy per-email vault_name SharedPreferences key '
                'remains in: ${offenders.join(", ")}',
      );
    });
  });

  group('api_client.dart', () {
    test('exposes authSignup / authLogin / authMe / authLogout', () {
      final src = File('lib/api_client.dart').readAsStringSync();
      for (final method in [
        'authSignup',
        'authLogin',
        'authMe',
        'authLogout',
      ]) {
        expect(
          src,
          contains(method),
          reason: 'api_client.dart must expose $method',
        );
      }
    });

    test('VaultNameTakenException + InvalidCredentialsException are '
        'defined', () {
      final src = File('lib/api_client.dart').readAsStringSync();
      expect(src, contains('class VaultNameTakenException'));
      expect(src, contains('class InvalidCredentialsException'));
    });
  });
}
