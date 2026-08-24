

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _readLib(String relativePath) {
  return File(
    '${Directory.current.path}/lib/$relativePath',
  ).readAsStringSync();
}


String _stripDartComments(String src) {
  src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
  src = src.replaceAll(RegExp(r'//[^\n]*'), '');
  return src;
}


void main() {
  late String mainSrc;
  late String storagePageSrc;

  setUpAll(() {
    mainSrc = _readLib('main.dart');
    storagePageSrc = _readLib('storage_page.dart');
  });

  
  group('Canonical free-tier constant', () {
    test('kVaultStorageLimitBytes resolves to 1 GiB = 1,073,741,824', () {
      
      
      expect(
        mainSrc,
        contains(
          'const int kVaultStorageLimitBytes = 1024 * 1024 * 1024;',
        ),
        reason:
            'kVaultStorageLimitBytes must remain the canonical '
            '1 GiB free-tier constant — exactly 1024 * 1024 * 1024 '
            'bytes — so the UI floor cannot accidentally drift.',
      );
    });

    test('numeric value sanity-check: 1024^3 = 1_073_741_824', () {
      
      
      const int oneGib = 1024 * 1024 * 1024;
      expect(oneGib, 1073741824,
          reason: 'Free-tier floor must equal exactly 1,073,741,824 '
              'bytes — matches backend DEFAULT_FREE_STORAGE_BYTES.');
    });
  });

  
  group('No duplicate hardcoded 1 GB literal in storage page', () {
    test('storage_page.dart imports kVaultStorageLimitBytes', () {
      expect(
        storagePageSrc,
        contains("import 'main.dart'"),
        reason: 'storage_page.dart must import from main.dart.',
      );
      expect(
        storagePageSrc,
        contains('kVaultStorageLimitBytes'),
        reason: 'storage_page.dart must reference '
            'kVaultStorageLimitBytes for the free-tier fallback so '
            'it can never drift from main.dart.',
      );
    });

    test('storage_page.dart has no inline 1073741824 literal in '
        'executable code', () {
      
      
      final executable = _stripDartComments(storagePageSrc);
      expect(
        RegExp(r'\b1073741824\b').hasMatch(executable),
        isFalse,
        reason:
            'storage_page.dart must NOT carry a hardcoded 1073741824 '
            'literal in executable code — reference '
            'kVaultStorageLimitBytes instead.',
      );
    });
  });

  
  group('AppState.effectiveStorageLimitBytes floor', () {
    test('returns kVaultStorageLimitBytes when no billing loaded', () {
      
      
      expect(
        mainSrc,
        contains('return kVaultStorageLimitBytes;'),
        reason: 'effectiveStorageLimitBytes must fall back to '
            'kVaultStorageLimitBytes when neither '
            'billingEffectiveLimitBytes nor storageLimitBytes is set.',
      );
    });
  });

  
  group('Storage page reads backend entitlement', () {
    test('storage page calls getBillingMe', () {
      expect(
        storagePageSrc,
        contains('getBillingMe'),
        reason: 'StoragePage must hydrate from GET /billing/me.',
      );
    });

    test('storage page reads effective_limit_bytes from response', () {
      expect(
        storagePageSrc,
        contains("data['effective_limit_bytes']"),
        reason: '_UsageCard must read effective_limit_bytes from the '
            'backend entitlement response — never compute it locally.',
      );
    });

    test('storage page reads used_bytes from response', () {
      expect(
        storagePageSrc,
        contains("data['used_bytes']"),
        reason:
            'Storage page must read used_bytes from the backend, '
            'never re-sum it client-side.',
      );
    });

    test('storage page reads included_bytes from response', () {
      expect(
        storagePageSrc,
        contains("data['included_bytes']"),
        reason: 'Storage page must read included_bytes from the '
            'backend for the free-tier explanation card.',
      );
    });
  });

  
  group('Free-tier predicate + paid label closed-set', () {
    test('storage_page.dart exposes isOnFreeTierOnly predicate', () {
      expect(
        storagePageSrc,
        contains('isOnFreeTierOnly'),
        reason:
            'The free-tier UI branch must be gated on the closed-set '
            'predicate isOnFreeTierOnly — never re-derived inline.',
      );
    });

    test('main.dart planLabel rule is paid-or-free, not stacked', () {
      
      
      expect(
        mainSrc,
        contains(
          'if (billingBlockCount > 0 && billingPurchasedBytes > 0)',
        ),
        reason:
            'planLabel must mirror the backend rule — paid REPLACES '
            'free; it must not stack the free 1 GB on top of paid.',
      );
      expect(
        mainSrc,
        contains("return 'Free Vault Plan';"),
        reason:
            'planLabel must return "Free Vault Plan" on the else '
            'branch.',
      );
    });
  });

  
  group('Over-quota surfaces use backend error', () {
    test('VaultStorageLimitExceededException carries backend fields', () {
      final apiClient = _readLib('api_client.dart');
      expect(
        apiClient,
        contains("(detail['used_bytes'] as num?)?.toInt()"),
        reason:
            'VaultStorageLimitExceededException must read used_bytes '
            'from the backend error detail.',
      );
      expect(
        apiClient,
        contains('_parseStorageLimitException'),
        reason:
            'api_client must wire the closed-set backend over-quota '
            'parser so over-quota messages surface uniformly.',
      );
    });
  });

  
  group('No null / 0 / unlimited surface for free user', () {
    test('storage page never carries the word "unlimited"', () {
      final executable = _stripDartComments(storagePageSrc);
      expect(
        executable.toLowerCase().contains('unlimited'),
        isFalse,
        reason:
            'Storage page must NEVER render the word "unlimited" — '
            'the free tier is bounded.',
      );
    });

    test('storage page does not render the word "null" as text', () {
      final executable = _stripDartComments(storagePageSrc);
      
      
      expect(
        executable.contains("Text('null')"),
        isFalse,
        reason:
            'Storage page must NEVER render a "null" Text widget.',
      );
    });
  });
}
