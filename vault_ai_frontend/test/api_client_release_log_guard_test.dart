

library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  group('api_client.dart release-log guard', () {
    late String source;
    late List<String> lines;

    setUpAll(() {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue,
          reason: 'api_client.dart not found at the expected path');
      source = file.readAsStringSync();
      lines = source.split('\n');
    });

    test('only release-safe print() call lives inside _vlog', () {
      
      
      int? vlogPrintLine;
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].contains("print('[vault-debug] \$tag \$payload')")) {
          vlogPrintLine = i + 1; 
          break;
        }
      }
      expect(vlogPrintLine, isNotNull,
          reason: '_vlog\'s release-gated print() not found — the test '
              'invariant is broken or the helper was renamed');

      final offenders = <String>[];
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i];
        
        if (i + 1 == vlogPrintLine) continue;
        
        final stripped = line.trimLeft();
        if (stripped.startsWith('//') || stripped.startsWith('///')) continue;
        if (stripped.startsWith('*')) continue;
        
        
        final m = RegExp(r'\bprint\s*\(').firstMatch(line);
        if (m != null) {
          offenders.add('line ${i + 1}: ${line.trim()}');
        }
      }
      expect(
        offenders,
        isEmpty,
        reason: 'api_client.dart must NOT contain any release-visible '
            'print() call. Every diagnostic must go through _vlog so '
            'release builds emit nothing. Offenders:\n'
            '${offenders.join('\n')}',
      );
    });

    test('no release-visible debugPrint either', () {
      
      
      final offenders = <String>[];
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i];
        final stripped = line.trimLeft();
        if (stripped.startsWith('//') || stripped.startsWith('///')) continue;
        final m = RegExp(r'\bdebugPrint\s*\(').firstMatch(line);
        if (m != null) {
          offenders.add('line ${i + 1}: ${line.trim()}');
        }
      }
      expect(offenders, isEmpty,
          reason: 'api_client.dart must NOT call debugPrint — route '
              'through _vlog instead. Offenders:\n${offenders.join('\n')}');
    });

    test('no token / auth / body content emitted outside _vlog', () {
      
      
      const sensitiveKeys = [
        'authToken',
        'response.body',
        'errorBody',
        'tokenPreview',
        'Bearer ',
      ];
      final offenders = <String>[];
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i];
        final stripped = line.trimLeft();
        if (stripped.startsWith('//') || stripped.startsWith('///')) continue;
        if (stripped.startsWith('*')) continue;
        
        
        if (!line.contains('print(')) continue;
        for (final k in sensitiveKeys) {
          if (line.contains(k)) {
            offenders.add('line ${i + 1}: ${line.trim()}');
            break;
          }
        }
      }
      expect(
        offenders,
        isEmpty,
        reason: 'sensitive field name appears in a raw print() call: \n'
            '${offenders.join('\n')}',
      );
    });
  });
}
