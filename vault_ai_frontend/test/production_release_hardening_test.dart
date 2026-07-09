

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


class _Lib {
  final String relPath;
  final String content;
  _Lib(this.relPath, this.content);
}


List<_Lib> _readAllLibFiles() {
  final root = Directory('${Directory.current.path}/lib');
  if (!root.existsSync()) return const [];
  final out = <_Lib>[];
  for (final entity in root.listSync(recursive: true)) {
    if (entity is! File) continue;
    if (!entity.path.endsWith('.dart')) continue;
    
    
    final rel = entity.path
        .replaceAll('\\', '/')
        .substring(root.path.replaceAll('\\', '/').length + 1);
    out.add(_Lib(
      rel,
      entity.readAsStringSync().replaceAll('\r\n', '\n'),
    ));
  }
  return out;
}


String _stripCommentsAndDocs(String src) {
  
  src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
  final lines = <String>[];
  for (final raw in src.split('\n')) {
    final line = raw;
    
    
    var keep = line;
    final commentIdx = _safeCommentIndex(line);
    if (commentIdx != -1) {
      keep = line.substring(0, commentIdx);
    }
    if (keep.trim().isEmpty) continue;
    lines.add(keep);
  }
  return lines.join('\n');
}


int _safeCommentIndex(String line) {
  bool inSingle = false;
  bool inDouble = false;
  bool inRaw = false;
  for (int i = 0; i < line.length - 1; i++) {
    final c = line[i];
    if (!inSingle && !inDouble && c == 'r'
        && (line[i + 1] == "'" || line[i + 1] == '"')) {
      inRaw = true;
      continue;
    }
    if (c == "'" && !inDouble) {
      
      if (i > 0 && line[i - 1] == r'\' && !inRaw) continue;
      inSingle = !inSingle;
      if (!inSingle) inRaw = false;
      continue;
    }
    if (c == '"' && !inSingle) {
      if (i > 0 && line[i - 1] == r'\' && !inRaw) continue;
      inDouble = !inDouble;
      if (!inDouble) inRaw = false;
      continue;
    }
    if (!inSingle && !inDouble
        && c == '/' && line[i + 1] == '/') {
      return i;
    }
  }
  return -1;
}


void _f1NoHardcodedDevUrls(List<_Lib> libs) {
  group('F1 — No hardcoded dev URLs in production source', () {
    test('no localhost / 127.0.0.1 / ngrok / localtunnel string '
        'literals appear in non-debug code', () {
      const forbidden = [
        'http://localhost',
        'https://localhost',
        'http://127.0.0.1',
        'https://127.0.0.1',
        '://0.0.0.0',
        '.ngrok.io',
        '.loca.lt',
        '.localtunnel.me',
        'http://dev.',
        'https://dev.',
        'https://staging.',
      ];
      for (final lib in libs) {
        final stripped = _stripCommentsAndDocs(lib.content);
        for (final f in forbidden) {
          
          
          int idx = 0;
          while (true) {
            final at = stripped.indexOf(f, idx);
            if (at == -1) break;
            
            final lineStart = stripped.lastIndexOf('\n', at) + 1;
            final lineEnd = stripped.indexOf('\n', at);
            final lineEndIdx = lineEnd == -1
                ? stripped.length : lineEnd;
            
            
            final priorWindow =
                stripped.substring(
                  (lineStart - 800).clamp(0, lineStart),
                  lineStart,
                );
            final gated =
                priorWindow.contains('kDebugMode')
                || priorWindow.contains('!kReleaseMode')
                || priorWindow.contains(
                    'String.fromEnvironment(')
                || priorWindow.contains(
                    'bool.fromEnvironment(')
                || priorWindow.contains(
                    'int.fromEnvironment(');
            if (!gated) {
              fail(
                'lib/${lib.relPath}: forbidden dev URL literal '
                '"$f" appears outside a kDebugMode / '
                '!kReleaseMode / String.fromEnvironment gate. '
                'Line: '
                '${stripped.substring(lineStart, lineEndIdx)}',
              );
            }
            idx = at + f.length;
          }
        }
      }
    });
  });
}


void _f2NoDebugPrintOfSensitive(List<_Lib> libs) {
  group('F2 — No debugPrint / print of sensitive identifiers', () {
    test('lib/ source emits no debugPrint(...sensitive...) calls',
        () {
      
      
      const sensitive = [
        '.pin',
        '.password',
        '.secretValue',
        '.recoveryPhrase',
        '.privateKey',
        '.seedPhrase',
        '.walletAddress',
        '.publicAddress',
        'recovery_phrase',
        'private_key',
        'seed_phrase',
        'wallet_address',
        'public_address',
        'secret_value',
      ];
      final callRx = RegExp(
        r'(?:debugPrint|print)\([\s\S]*?\)',
        multiLine: true,
      );
      for (final lib in libs) {
        final stripped = _stripCommentsAndDocs(lib.content);
        for (final m in callRx.allMatches(stripped)) {
          final block = m.group(0)!;
          for (final s in sensitive) {
            expect(block.contains(s), isFalse,
                reason: 'lib/${lib.relPath}: debugPrint / print '
                    'emits sensitive identifier "$s": $block');
          }
        }
      }
    });
  });
}


void _f3AppWideAntiClaim(List<_Lib> libs) {
  group('F3 — App-wide anti-claim scan', () {
    test('no prohibited Crypto Vault literals anywhere in lib/', () {
      const literals = [
        "'Send crypto'",
        "'Send BTC'",
        "'Send ETH'",
        "'Sign transaction'",
        "'Broadcast transaction'",
        "'Buy crypto'",
        "'Sell crypto'",
        "'Swap crypto'",
        "'Trade crypto'",
        "'Create wallet'",
        "'Generate wallet'",
        "'Connect MetaMask'",
        "'Verify transaction'",
        "'Import transaction history'",
        
        '"Send crypto"',
        '"Sign transaction"',
        '"Broadcast transaction"',
        '"Buy crypto"',
        '"Sell crypto"',
        '"Swap crypto"',
        '"Trade crypto"',
        '"Create wallet"',
        '"Generate wallet"',
        '"Connect MetaMask"',
      ];
      for (final lib in libs) {
        for (final literal in literals) {
          expect(lib.content.contains(literal), isFalse,
              reason: 'lib/${lib.relPath}: contains prohibited '
                  'string literal $literal');
        }
      }
    });
  });
}


void _f4NoTestFixtureLeakage(List<_Lib> libs) {
  group('F4 — No test fixture leakage in production source', () {
    test('no test_/mock_/fake_ string literals in lib/', () {
      
      
      const prefixes = [
        "'test_",
        "'mock_",
        "'fake_",
        '"test_',
        '"mock_',
        '"fake_',
      ];
      for (final lib in libs) {
        for (final p in prefixes) {
          expect(lib.content.contains(p), isFalse,
              reason: 'lib/${lib.relPath}: contains test-fixture '
                  'literal prefix $p');
        }
      }
    });
  });
}


void _f5NoHardcodedPinDefaults(List<_Lib> libs) {
  group('F5 — No hardcoded PIN defaults', () {
    test(
      'no TextEditingController(text: "1234"/"0000") with PIN '
      'semantic context in lib/',
      () {
        
        
        final ctlRx = RegExp(
          r'''TextEditingController\(\s*text:\s*['"](?:1234|0000)['"]''',
        );
        for (final lib in libs) {
          final stripped = _stripCommentsAndDocs(lib.content);
          for (final m in ctlRx.allMatches(stripped)) {
            final window = stripped.substring(
              (m.start - 200).clamp(0, m.start),
              (m.end + 200).clamp(0, stripped.length),
            );
            expect(window.toLowerCase().contains('pin'), isFalse,
                reason: 'lib/${lib.relPath}: hardcoded PIN '
                    'default near match: ${m.group(0)}');
          }
        }
      },
    );
  });
}


void _f8NoTodoLiterals(List<_Lib> libs) {
  group('F8 — No TODO/FIXME/XXX string literals', () {
    test('no string literal carries "TODO" / "FIXME" / "XXX" '
        'prefix in lib/', () {
      
      
      const forbidden = [
        "'TODO:",
        "'FIXME:",
        "'XXX:",
        '"TODO:',
        '"FIXME:',
        '"XXX:',
      ];
      for (final lib in libs) {
        for (final p in forbidden) {
          expect(lib.content.contains(p), isFalse,
              reason: 'lib/${lib.relPath}: contains dev-marker '
                  'string literal $p');
        }
      }
    });
  });
}


void _f9LogoutClearsState(List<_Lib> libs) {
  group('F9 — Logout clears state', () {
    test('AppState.signOut() clears vault crypto cache + session',
        () {
      final main = libs.firstWhere(
        (l) => l.relPath == 'main.dart',
        orElse: () => _Lib('', ''),
      );
      expect(main.content.isNotEmpty, isTrue,
          reason: 'main.dart not found in lib/');
      
      
      final src = main.content;
      
      
      final start = src.indexOf('signOut(');
      expect(start, greaterThanOrEqualTo(0),
          reason: 'AppState.signOut method not found');
      
      final window = src.substring(
        start,
        (start + 1500).clamp(0, src.length),
      );
      expect(window.contains('_VaultCrypto.clearCache(') ||
             window.contains('clearCache('),
          isTrue,
          reason: 'signOut must clear the vault crypto cache');
      expect(window.contains('clearSession('), isTrue,
          reason: 'signOut must call clearSession to wipe the '
              'auth token + vault id');
    });
  });
}


void main() {
  final libs = _readAllLibFiles();
  _f1NoHardcodedDevUrls(libs);
  _f2NoDebugPrintOfSensitive(libs);
  _f3AppWideAntiClaim(libs);
  _f4NoTestFixtureLeakage(libs);
  _f5NoHardcodedPinDefaults(libs);
  _f8NoTodoLiterals(libs);
  _f9LogoutClearsState(libs);
}
