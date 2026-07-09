

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readMain() {
  return File(
    Directory.current.path + '/lib/main.dart',
  ).readAsStringSync();
}

String _read(String relativePath) {
  return File(
    Directory.current.path + '/' + relativePath,
  ).readAsStringSync();
}


String _stripDartComments(String src) {
  
  src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
  
  src = src.replaceAll(RegExp(r'//[^\n]*'), '');
  return src;
}

void main() {
  group('AppState — single source of truth', () {
    test('effectiveStorageLimitBytes getter exists', () {
      final src = _readMain();
      expect(
        src,
        contains('int get effectiveStorageLimitBytes {'),
        reason:
            'AppState must expose a single getter every surface '
            'reads; without it surfaces would re-derive the limit.',
      );
    });

    test('effectiveStorageLimitBytes prefers billingEffectiveLimitBytes',
        () {
      final src = _readMain();
      final start =
          src.indexOf('int get effectiveStorageLimitBytes {');
      
      final body = src.substring(start, start + 600);
      expect(
        body,
        contains('billingEffectiveLimitBytes'),
        reason:
            'Getter must prefer the /billing/me-driven '
            'effective_limit_bytes so paid users never see a '
            'stale 1 GB number.',
      );
    });

    test('planLabel uses block_count + purchased_bytes (not + included)',
        () {
      final src = _readMain();
      final start = src.indexOf('String get planLabel {');
      final body = src.substring(start, start + 600);
      
      
      expect(
        body,
        contains('billingBlockCount > 0 && billingPurchasedBytes > 0'),
        reason:
            'planLabel must mirror the backend "paid replaces '
            'free" rule.',
      );
      
      final executable = _stripDartComments(body);
      expect(
        executable,
        isNot(contains('billingIncludedBytes + billingPurchasedBytes')),
        reason:
            'planLabel must NEVER show "1 GB + purchased" — '
            'operator brief.',
      );
    });
  });

  group('No surface re-derives the limit from raw billing fields', () {
    test('main.dart contains no executable "included + purchased" addition',
        () {
      final src = _readMain();
      final exec = _stripDartComments(src);
      for (final pattern in const [
        'billingIncludedBytes + billingPurchasedBytes',
        'includedBytes + purchasedBytes',
      ]) {
        expect(
          exec,
          isNot(contains(pattern)),
          reason:
              'main.dart contains an executable "$pattern" — '
              'operator brief forbids stacking the free tier on '
              'top of the paid plan.',
        );
      }
    });

    test('storage_page.dart does not re-derive limit by addition', () {
      final src = _read('lib/storage_page.dart');
      final exec = _stripDartComments(src);
      for (final pattern in const [
        'includedBytes + purchasedBytes',
        'included_bytes + purchased_bytes',
        'billingIncludedBytes + billingPurchasedBytes',
      ]) {
        expect(
          exec,
          isNot(contains(pattern)),
          reason:
              'storage_page.dart contains "$pattern" — operator '
              'brief: paid replaces free, never adds.',
        );
      }
    });

    test('storage_page.dart reads effective_limit_bytes from /billing/me',
        () {
      final src = _read('lib/storage_page.dart');
      expect(
        src,
        contains("effective_limit_bytes"),
        reason:
            'The Storage page reads the SAME number AppState reads '
            'from /billing/me.',
      );
    });
  });

  group('Quota / save-warning callsites read AppState', () {
    test('upload flow reads app.effectiveStorageLimitBytes', () {
      final src = _readMain();
      expect(
        src,
        contains('app.effectiveStorageLimitBytes'),
        reason:
            'Upload flow must read AppState.effectiveStorageLimitBytes '
            '— never an independent calculation.',
      );
    });

    test('upload flow reads app.storageUsedBytes', () {
      final src = _readMain();
      expect(
        src,
        contains('app.storageUsedBytes'),
      );
    });
  });

  group('Upgraded path does not show the 1 GB free constant', () {
    test('kVaultStorageLimitBytes is only a fallback, not the source '
        'for paid users', () {
      
      
      final src = _readMain();
      
      final exec = _stripDartComments(src);
      final occurrences =
          'kVaultStorageLimitBytes'.allMatches(exec).length;
      
      
      expect(
        occurrences,
        lessThanOrEqualTo(8),
        reason:
            'kVaultStorageLimitBytes is referenced $occurrences '
            'times in executable code. The 1 GB constant should '
            'only appear as a cold-start fallback; if more '
            'surfaces depend on it, refactor to read the AppState '
            'getter instead.',
      );
    });
  });
}
