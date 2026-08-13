
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


Iterable<File> _dartLibFiles() sync* {
  final root = Directory('lib');
  for (final entity in root.listSync(recursive: true)) {
    if (entity is File && entity.path.endsWith('.dart')) {
      yield entity;
    }
  }
}


bool _isRefusalOrFaqContext(String snippet) {
  final lower = snippet.toLowerCase();
  const contextMarkers = <String>[

    'refusal', 'refuse', 'refused',

    'faq', 'help center', 'kfaqentr',

    'not support', 'does not support', 'is not an exchange',

    'no send', 'no buy',

    'buysellswap', 'buy-sell-swap', "'buy-sell-swap'",
  ];
  return contextMarkers.any((m) => lower.contains(m));
}


void main() {


  group('Part E: no obsolete placeholder copy in frontend lib', () {

    const List<String> _placeholders = <String>[
      'Coming next',
      'Coming soon',
      'Planned',
      'Later phase',
      'Privacy wallet later',
      'No Send, no Receive, no QR',
    ];

    test('no obsolete placeholder copy', () {
      final offenders = <String>[];
      for (final f in _dartLibFiles()) {
        final content = f.readAsStringSync();
        final lines = content.split('\n');
        for (int i = 0; i < lines.length; i++) {
          for (final p in _placeholders) {

            final pattern = RegExp(
              r'(?:^|[\s"' r"'"
              r'.>({\[])'
              + RegExp.escape(p) +
              r'(?:$|[\s"' r"'"
              r'.<),}\]])',
            );
            if (pattern.hasMatch(lines[i])) {
              offenders.add('${f.path}:${i + 1}: '
                  '${lines[i].trim()}');
            }
          }
        }
      }
      expect(offenders, isEmpty,
          reason: 'obsolete placeholder copy found:\n'
                  '${offenders.join('\n')}');
    });
  });


  group('Part D: no generic "Aisha" in scanned frontend copy', () {
    test('no "Aisha" in lib except dynamic-vault-name context', () {
      final offenders = <String>[];
      for (final f in _dartLibFiles()) {
        final content = f.readAsStringSync();
        final lines = content.split('\n');
        for (int i = 0; i < lines.length; i++) {
          final line = lines[i];
          if (!RegExp(r'\bAisha\b', caseSensitive: false)
              .hasMatch(line)) continue;

          if (line.contains(r'$vaultLabel') ||
              line.contains('vaultLabel') ||
              line.contains('user.vaultName') ||
              line.contains('displayUsername')) {
            continue;
          }
          offenders.add('${f.path}:${i + 1}: ${line.trim()}');
        }
      }
      expect(offenders, isEmpty,
          reason: 'generic "Aisha" in lib copy:\n'
                  '${offenders.join('\n')}');
    });
  });


  group('Part E: no forbidden crypto verbs in wallet UI outside '
      'refusal/FAQ context', () {


    const List<String> _forbiddenVerbs = <String>[
      'Buy crypto', 'Sell crypto', 'Swap crypto',
      'Trade crypto', 'Stake crypto', 'Bridge crypto',
      'Convert crypto',
    ];

    test('no forbidden verbs in wallet UI', () {
      final offenders = <String>[];
      for (final f in _dartLibFiles()) {
        if (!f.path.contains('crypto_wallet_engine') &&
            !f.path.contains('crypto_vault') &&
            !f.path.contains('crypto_receive_panel')) continue;

        final content = f.readAsStringSync();
        final lines = content.split('\n');
        for (int i = 0; i < lines.length; i++) {
          final line = lines[i];
          for (final v in _forbiddenVerbs) {
            if (!line.toLowerCase().contains(v.toLowerCase())) {
              continue;
            }

            final start = (i - 2).clamp(0, lines.length - 1);
            final end = (i + 3).clamp(0, lines.length - 1);
            final windowText = lines.sublist(start, end).join('\n');
            if (_isRefusalOrFaqContext(windowText)) continue;
            offenders.add(
                '${f.path}:${i + 1}: forbidden verb "$v" '
                'outside refusal/FAQ context: ${line.trim()}');
          }
        }
      }
      expect(offenders, isEmpty,
          reason: 'forbidden crypto verbs in wallet UI:\n'
                  '${offenders.join('\n')}');
    });
  });


  group('Part E: no big commented-out code blocks', () {
    test('no ≥5 consecutive commented-out code lines', () {
      final offenders = <String>[];

      final commentedCodeRegex = RegExp(
        r'^\s*//\s+(?:'
        r'[a-zA-Z_$][\w$.]*\s*\(|'
        r'if\s*\(|'
        r'for\s*\(|'
        r'while\s*\(|'
        r'return\s|'
        r'final\s|'
        r'var\s|'
        r'const\s|'
        r'await\s'
        r')',
      );
      for (final f in _dartLibFiles()) {

        if (f.path.contains('l10n/')) continue;
        final lines = f.readAsStringSync().split('\n');
        int consecutive = 0;
        int start = -1;
        for (int i = 0; i < lines.length; i++) {
          if (commentedCodeRegex.hasMatch(lines[i])) {
            if (consecutive == 0) start = i + 1;
            consecutive++;
            if (consecutive >= 5) {
              offenders.add(
                  '${f.path}:$start-${i + 1}: '
                  'commented-out code block');
              consecutive = 0;
              start = -1;
            }
          } else {
            consecutive = 0;
            start = -1;
          }
        }
      }
      expect(offenders, isEmpty,
          reason: 'commented-out code blocks:\n'
                  '${offenders.join('\n')}');
    });
  });
}


bool _isCommentOnlyLine(String line, String needle) {

  final trimmed = line.trimLeft();
  if (trimmed.startsWith('//')) return true;
  return false;
}
