

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/storage_page.dart';


Map<String, dynamic> _billing({
  required String status,
  bool cancelAtPeriodEnd = false,
  String source = 'stripe',
  int blockCount = 1,
  int usedBytes = 128 * 1024 * 1024,
  int limitBytes = 100 * 1024 * 1024 * 1024,
}) {
  return {
    'account_type':          'individual',
    'source':                source,
    'status':                status,
    'block_count':           blockCount,
    'used_bytes':            usedBytes,
    'effective_limit_bytes': limitBytes,
    'included_bytes':        1024 * 1024 * 1024,
    'percent_used':          (usedBytes / limitBytes) * 100.0,
    'self_service_max_blocks': 100,
    'cancel_at_period_end':  cancelAtPeriodEnd,
    'has_active_subscription':
        const {'active', 'in_grace', 'canceled_pending'}
            .contains(status)
        && source == 'stripe',
  };
}


Future<void> _pumpStorage(
  WidgetTester tester,
  Map<String, dynamic> data,
) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: StorageBody(
          data: data,
          onBuyStorage: () {},
          onManageSubscription: () {},
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('subscription-status banner classifiers', () {
    test('isSubscriptionInGrace true for status=in_grace', () {
      expect(
        isSubscriptionInGrace(_billing(status: 'in_grace')),
        isTrue,
      );
    });

    test('isSubscriptionInGrace false for active', () {
      expect(
        isSubscriptionInGrace(_billing(status: 'active')),
        isFalse,
      );
    });

    test('isSubscriptionCanceledPending true for status=canceled_pending',
        () {
      expect(
        isSubscriptionCanceledPending(
          _billing(status: 'canceled_pending'),
        ),
        isTrue,
      );
    });

    test(
        'isSubscriptionCanceledPending true when cancel_at_period_end=true '
        'on an active sub',
        () {
      expect(
        isSubscriptionCanceledPending(
          _billing(status: 'active', cancelAtPeriodEnd: true),
        ),
        isTrue,
      );
    });

    test('isSubscriptionCanceledPending false for a normal active sub', () {
      expect(
        isSubscriptionCanceledPending(_billing(status: 'active')),
        isFalse,
      );
    });

    test('isSubscriptionOverQuotaGrace true for over_quota_grace', () {
      expect(
        isSubscriptionOverQuotaGrace(
          _billing(status: 'over_quota_grace', source: 'none'),
        ),
        isTrue,
      );
    });
  });

  group('storage page renders status-driven banners', () {
    testWidgets('in_grace shows critical payment-issue banner',
        (tester) async {
      await _pumpStorage(tester, _billing(status: 'in_grace'));
      expect(
        find.byKey(const Key('storage_in_grace_banner')),
        findsOneWidget,
      );
      expect(
        find.text(kStorageInGraceBannerMessage),
        findsOneWidget,
      );
    });

    testWidgets(
        'canceled_pending shows warning cancel banner (not payment banner)',
        (tester) async {
      await _pumpStorage(tester, _billing(status: 'canceled_pending'));
      expect(
        find.byKey(const Key('storage_canceled_pending_banner')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('storage_in_grace_banner')),
        findsNothing,
      );
      expect(
        find.text(kStorageCanceledPendingBannerMessage),
        findsOneWidget,
      );
    });

    testWidgets('active with cancel_at_period_end=true shows cancel banner',
        (tester) async {
      await _pumpStorage(
        tester,
        _billing(status: 'active', cancelAtPeriodEnd: true),
      );
      expect(
        find.byKey(const Key('storage_canceled_pending_banner')),
        findsOneWidget,
      );
    });

    testWidgets('over_quota_grace shows critical banner', (tester) async {
      await _pumpStorage(
        tester,
        _billing(status: 'over_quota_grace', source: 'none'),
      );
      expect(
        find.byKey(const Key('storage_over_quota_grace_banner')),
        findsOneWidget,
      );
    });

    testWidgets('normal active subscription shows no status banner',
        (tester) async {
      await _pumpStorage(tester, _billing(status: 'active'));
      expect(
        find.byKey(const Key('storage_in_grace_banner')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('storage_canceled_pending_banner')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('storage_over_quota_grace_banner')),
        findsNothing,
      );
    });

    testWidgets('in_grace banner does not mention buy/sell/swap language',
        (tester) async {
      await _pumpStorage(tester, _billing(status: 'in_grace'));
      final lower = kStorageInGraceBannerMessage.toLowerCase();
      for (final banned in ['swap', 'stake', 'bridge',
                            'trade', ' buy ', ' sell ']) {
        expect(lower, isNot(contains(banned)),
            reason: 'banner leaks banned language: $banned');
      }
    });
  });

  group('debug billing card release-mode gating (source guard)', () {
    test('storage_page.dart guards _BillingDebugCard with !kReleaseMode',
        () {
      final src = File('lib/storage_page.dart').readAsStringSync();
      final debugCardIdx = src.indexOf('_BillingDebugCard');
      expect(debugCardIdx, greaterThan(-1),
          reason: '_BillingDebugCard must exist in storage_page.dart');
      final slice = src.substring(
        (debugCardIdx - 800).clamp(0, src.length),
        debugCardIdx,
      );
      expect(
        slice.contains('!kReleaseMode'),
        isTrue,
        reason: 'The _BillingDebugCard render must be gated on '
            '!kReleaseMode so production builds never expose it',
      );
    });
  });

  group('banner copy — non-exchange surface', () {
    test('storage banner constants contain no exchange verbs', () {
      for (final b in [
        kStorageInGraceBannerMessage,
        kStorageCanceledPendingBannerMessage,
        kStorageOverQuotaGraceBannerMessage,
      ]) {
        final lower = b.toLowerCase();
        for (final banned in ['swap ', 'stake ', 'bridge ',
                              'trade ', ' buy ', ' sell ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'banner leaked banned language: $b');
        }
      }
    });

    test('storage banner constants never reference lite/saved-record UI',
        () {
      for (final b in [
        kStorageInGraceBannerMessage,
        kStorageCanceledPendingBannerMessage,
        kStorageOverQuotaGraceBannerMessage,
      ]) {
        expect(b.toLowerCase(),
            isNot(contains('crypto vault lite')));
      }
    });
  });
}
