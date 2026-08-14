

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
  late String storagePageSrc;

  setUpAll(() {
    storagePageSrc = _readLib('storage_page.dart');
  });

  
  group('Stripe Checkout — same-tab navigation', () {
    test('checkout launchUrl uses webOnlyWindowName: "_self" on web',
        () {
      
      
      expect(
        storagePageSrc,
        contains("webOnlyWindowName: kIsWeb ? '_self' : null,"),
        reason:
            "The Stripe checkout launchUrl must use "
            "webOnlyWindowName: '_self' on web so the same browser "
            "tab navigates to Stripe Checkout. Native platforms keep "
            "the existing externalApplication mode.",
      );
    });

    test('checkout launchUrl mode branches on kIsWeb', () {
      
      
      expect(
        storagePageSrc,
        contains(
          'mode: kIsWeb\n'
          '            ? LaunchMode.platformDefault\n'
          '            : LaunchMode.externalApplication,',
        ),
        reason: 'launchUrl mode must branch on kIsWeb: '
            'platformDefault on web (lets webOnlyWindowName apply); '
            'externalApplication on native (lets the system browser '
            'handle Stripe Checkout).',
      );
    });
  });

  
  group('Forbidden new-tab markers', () {
    test('storage_page.dart executable code carries no "_blank"', () {
      final executable = _stripDartComments(storagePageSrc);
      expect(
        executable.contains("'_blank'"),
        isFalse,
        reason:
            "storage_page.dart MUST NOT carry a '_blank' window name. "
            "Stripe Checkout must navigate in the same tab; '_blank' "
            "is the legacy new-tab marker that produced the live bug.",
      );
      expect(
        executable.contains('"_blank"'),
        isFalse,
        reason:
            'storage_page.dart MUST NOT carry a "_blank" window name '
            '(double-quoted variant).',
      );
    });

    test('storage_page.dart carries no window.open call', () {
      
      
      final executable = _stripDartComments(storagePageSrc);
      expect(
        executable.contains('window.open('),
        isFalse,
        reason:
            'storage_page.dart MUST NOT call window.open() — that is '
            'the legacy new-tab path; the same-tab fix uses '
            'launchUrl(..., webOnlyWindowName: "_self") instead.',
      );
    });
  });

  
  group('Checkout success URL', () {
    test('buildCheckoutRedirectUrl anchors at the current origin', () {
      
      
      expect(
        storagePageSrc,
        contains('final base = Uri.base;'),
        reason: 'buildCheckoutRedirectUrl must derive scheme + host + '
            'port from Uri.base so Stripe redirects back to the '
            'same tab.',
      );
      expect(
        storagePageSrc,
        contains("path: '/storage',"),
        reason: 'buildCheckoutRedirectUrl must always anchor at '
            '/storage so the post-checkout poll triggers there.',
      );
      expect(
        storagePageSrc,
        contains("queryParameters: {'checkout': queryFlag},"),
        reason: 'buildCheckoutRedirectUrl must carry the '
            '?checkout=<flag> query string so storage_page.dart can '
            'distinguish success from cancel on return.',
      );
    });

    test('successUrl is passed to createStripeCheckoutSession', () {
      
      
      expect(
        storagePageSrc,
        contains("successUrl: buildCheckoutRedirectUrl('success'),"),
        reason: '_startCheckout must forward the origin-anchored '
            'success URL so Stripe redirects back to the same tab.',
      );
      expect(
        storagePageSrc,
        contains("cancelUrl:  buildCheckoutRedirectUrl('cancel'),"),
        reason: '_startCheckout must forward the origin-anchored '
            'cancel URL too.',
      );
    });
  });

  
  group('No new-vault / signup creation on return', () {
    test('post-checkout poll body never invokes signup / new-vault APIs',
        () {
      final pollIdx = storagePageSrc
          .indexOf('Future<void> _runPostCheckoutPoll() async');
      expect(pollIdx, greaterThan(-1));
      
      final pollEnd = storagePageSrc.indexOf(
        'Future<Map<String, dynamic>?>',
        pollIdx,
      );
      final pollBody = storagePageSrc.substring(pollIdx, pollEnd);
      for (final banned in const <String>[
        'createVault',
        'create_vault',
        'authSignup',
        'auth_signup',
        '/signup',
        'pushReplacementNamed(\'/signup\')',
        'pushReplacementNamed(\'/auth\')',
      ]) {
        expect(
          pollBody.contains(banned),
          isFalse,
          reason: '_runPostCheckoutPoll MUST NEVER call "$banned" — '
              'a successful checkout never creates a new vault.',
        );
      }
    });

    test('checkout=success branch is retired', () {
      
      
      final detectIdx = storagePageSrc.indexOf("if (flag == 'success')");
      expect(detectIdx, lessThan(0));
    });
  });
}
