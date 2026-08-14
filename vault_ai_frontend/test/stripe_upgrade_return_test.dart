

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

  
  group('Retired return-from-checkout branch', () {
    test('checkout=success is not detected by active storage UI', () {
      
      
      expect(
        storagePageSrc,
        isNot(contains("if (flag == 'success')")),
        reason: 'retired Stripe return flags must have no active handler',
      );
    });

    test('_runPostCheckoutPoll function exists', () {
      expect(
        storagePageSrc,
        contains('Future<void> _runPostCheckoutPoll() async'),
        reason: 'storage_page.dart must define _runPostCheckoutPoll '
            'as the post-return entry point.',
      );
    });

    test(
        '_pollEntitlementUntilPaidSubscriptionActive helper exists '
        'with the right shape', () {
      
      expect(
        storagePageSrc,
        contains(
          'Future<Map<String, dynamic>?> _pollEntitlementUntilPaidSubscriptionActive(',
        ),
        reason:
            '_pollEntitlementUntilPaidSubscriptionActive must return '
            'the entitlement payload on success / null on timeout.',
      );
      
      
      expect(
        storagePageSrc,
        contains('const maxAttempts = 20;'),
        reason: 'Post-checkout poll must use 20 attempts.',
      );
      expect(
        storagePageSrc,
        contains('const interval = Duration(seconds: 1);'),
        reason: 'Post-checkout poll must use 1 s interval.',
      );
    });
  });

  
  group('Poll success criterion', () {
    test('checks block_count > 0 AND has_active_subscription', () {
      final body = storagePageSrc;
      expect(
        body.contains('if (blocks > 0 && active) return data;'),
        isTrue,
        reason:
            'The post-checkout poll must succeed only when BOTH '
            'block_count > 0 AND has_active_subscription=true — so a '
            'race where one is set but the other is not does NOT '
            'land the user on a half-applied entitlement.',
      );
    });

    test('helper reads has_active_subscription from the payload', () {
      expect(
        storagePageSrc,
        contains(
          "(data['has_active_subscription'] as bool?) ?? false",
        ),
        reason:
            'Post-checkout poll must read has_active_subscription '
            'from /billing/me — the same field the backend pinned in '
            'StorageEntitlement.',
      );
    });
  });

  
  group('Copy refresh', () {
    test('new operator-pinned copy is present', () {
      const required = <String>[
        'Checking your upgrade…',
        "'Payment received'",
        "We're still applying your upgrade.",
        'Refresh in a moment.',
      ];
      for (final needle in required) {
        expect(
          storagePageSrc.contains(needle),
          isTrue,
          reason: 'storage_page.dart must contain the operator-pinned '
              'copy: $needle',
        );
      }


      expect(
        storagePageSrc.contains("'Refresh now'") ||
            storagePageSrc.contains('storageRefreshNow'),
        isTrue,
        reason:
            'storage_page.dart must expose the Refresh-now action, '
            'either as the literal string or via '
            'AppLocalizations.storageRefreshNow',
      );
    });

    test('legacy "Upgrade submitted" / "Upgrading storage" copy is gone',
        () {
      final executable = _stripDartComments(storagePageSrc);
      const forbidden = <String>[
        "'Upgrade submitted'",
        "'Upgrading storage'",
        'Your upgrade was accepted.',
        'Your new storage limit may take',
      ];
      for (final needle in forbidden) {
        expect(
          executable.contains(needle),
          isFalse,
          reason: 'storage_page.dart must NOT carry legacy copy: '
              '$needle',
        );
      }
    });
  });

  
  group('AppState propagation', () {
    test('post-checkout poll pushes payload via applyBillingPayload', () {
      
      
      final pollStart =
          storagePageSrc.indexOf(
              '_pollEntitlementUntilPaidSubscriptionActive');
      expect(pollStart, greaterThan(-1));
      
      final pollEnd = storagePageSrc.indexOf(
        'Future<void>',
        pollStart + 10,
      );
      final body = storagePageSrc.substring(pollStart, pollEnd);
      expect(
        body.contains('app.applyBillingPayload(data);'),
        isTrue,
        reason: 'The post-checkout poll body must push every payload '
            'into AppState.applyBillingPayload so the Crypto Vault '
            'locked card, Settings "Current plan" card, and Security '
            'Center storage indicator all flip in lockstep.',
      );
    });
  });

  
  group('Refresh now button wiring', () {
    test('timeout dialog onRefresh re-runs _runPostCheckoutPoll', () {
      
      
      final timeoutDialogIdx =
          storagePageSrc.indexOf('_UpgradeTimeoutDialog(');
      expect(timeoutDialogIdx, greaterThan(-1));
      
      
      final block = storagePageSrc.substring(
        timeoutDialogIdx,
        (timeoutDialogIdx + 600).clamp(0, storagePageSrc.length),
      );
      expect(
        block.contains('await _runPostCheckoutPoll();'),
        isTrue,
        reason:
            'The timeout dialog\'s Refresh now button must re-run '
            '_runPostCheckoutPoll(), NOT just _refresh() — the user '
            'may tap before Stripe delivers, so a single GET races '
            'the webhook a second time.',
      );
    });
  });

  
  group('Dev-mode diagnostic line', () {
    test('vlog is imported from main.dart', () {
      expect(
        storagePageSrc,
        contains(
          "import 'main.dart'\n"
          "    show AppState, backendBaseUrl, "
          "kVaultStorageLimitBytes, vlog;",
        ),
        reason: 'storage_page.dart must import vlog so the dev '
            'diagnostic line surfaces in the browser console.',
      );
    });

    test("poll body emits the 'billing-debug' vlog line", () {
      expect(
        storagePageSrc,
        contains("vlog('billing-debug',"),
        reason: 'Every successful poll tick must emit a vlog line '
            'tagged "billing-debug" so an operator running in dev '
            'can read it from the browser console.',
      );
    });

    test('_billingDebugFields helper exists and returns safe IDs only',
        () {
      expect(
        storagePageSrc,
        contains('Map<String, Object?> _billingDebugFields('),
        reason: '_billingDebugFields helper must exist so both the '
            'vlog line and the timeout dialog reuse the same '
            'closed-set field builder.',
      );
      
      expect(
        storagePageSrc,
        contains("acctId.substring(0, 8)"),
        reason:
            "_billingDebugFields must truncate account_id to its "
            "first 8 chars — never log the full UUID.",
      );
      expect(
        storagePageSrc,
        contains("'last_webhook':"),
        reason: 'Diagnostic fields must include last_webhook key.',
      );
      expect(
        storagePageSrc,
        contains("'account':"),
        reason: 'Diagnostic fields must include account key.',
      );
      expect(
        storagePageSrc,
        contains("'block_count':"),
        reason: 'Diagnostic fields must include block_count key.',
      );
      expect(
        storagePageSrc,
        contains("'active':"),
        reason: 'Diagnostic fields must include active key.',
      );
      expect(
        storagePageSrc,
        contains("'limit':"),
        reason: 'Diagnostic fields must include limit key.',
      );
    });
  });

  
  group('Dev-mode diagnostic card', () {
    test('_BillingDebugCard widget exists', () {
      expect(
        storagePageSrc,
        contains('class _BillingDebugCard extends StatelessWidget'),
        reason:
            '_BillingDebugCard must exist as a separate widget so it '
            "can be source-pinned and reused.",
      );
    });

    test('timeout dialog renders _BillingDebugCard only when not in '
        'release mode', () {
      expect(
        storagePageSrc,
        contains('if (!kReleaseMode && debugFields != null)'),
        reason:
            'The diagnostic card MUST be gated on !kReleaseMode so '
            'it never reaches a production build, and on a non-null '
            'debugFields so legacy call sites that have not been '
            'migrated still render cleanly.',
      );
      expect(
        storagePageSrc,
        contains('_BillingDebugCard(fields:'),
        reason:
            'The timeout dialog must instantiate _BillingDebugCard '
            'with the debugFields the poll captured.',
      );
    });

    test('_BillingDebugCard renders a copy-able SelectableText', () {
      
      
      expect(
        storagePageSrc,
        contains('SelectableText('),
        reason:
            'The diagnostic card must use SelectableText so the '
            'operator can copy the closed-set IDs into a bug report.',
      );
    });
  });

  
  group('Polling predicate sanity check', () {
    test('block_count > 0 + active flips the poll to success', () {
      
      
      bool pollSucceeds(Map<String, dynamic> data) {
        final blocks = (data['block_count'] as num?)?.toInt() ?? 0;
        final active =
            (data['has_active_subscription'] as bool?) ?? false;
        return blocks > 0 && active;
      }

      expect(
        pollSucceeds({'block_count': 1, 'has_active_subscription': true}),
        isTrue,
        reason: 'active sub + 1 block must flip the poll to success',
      );
      expect(
        pollSucceeds({'block_count': 0, 'has_active_subscription': true}),
        isFalse,
        reason: 'active sub with 0 blocks must NOT succeed (a stale '
            'status flip without the block count is half-applied)',
      );
      expect(
        pollSucceeds({'block_count': 1, 'has_active_subscription': false}),
        isFalse,
        reason: 'block count without an active sub must NOT succeed',
      );
      expect(
        pollSucceeds(<String, dynamic>{}),
        isFalse,
        reason: 'empty payload must NOT succeed',
      );
    });
  });
}
