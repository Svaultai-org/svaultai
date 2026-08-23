import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/storage_page.dart';

const int _gib = 1024 * 1024 * 1024;

Map<String, dynamic> _entitlement({
  required int limitBytes,
  String source = 'none',
  String status = 'none',
  bool active = false,
  int blockCount = 0,
}) {
  return <String, dynamic>{
    'used_bytes': 0,
    'effective_limit_bytes': limitBytes,
    'percent_used': 0.0,
    'account_type': 'individual',
    'included_bytes': _gib,
    'storage_bytes_grant': 0,
    'block_count': blockCount,
    'source': source,
    'status': status,
    'has_active_subscription': active,
  };
}

Widget _wrap(Widget child) => MaterialApp(
      localizationsDelegates: const <LocalizationsDelegate<Object?>>[
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: child),
    );

Future<void> _pump(WidgetTester tester, StorageBody body) async {
  tester.view.physicalSize = const Size(1200, 2600);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(_wrap(body));
  await tester.pumpAndSettle();
}

void main() {
  group('Google Play subscription management URL', () {
    test('targets the configured product and Android package', () {
      final uri = buildGooglePlaySubscriptionManagementUri();
      expect(uri.scheme, 'https');
      expect(uri.host, 'play.google.com');
      expect(uri.path, '/store/account/subscriptions');
      expect(uri.queryParameters['sku'], 'svaultai_storage_50gb');
      expect(uri.queryParameters['package'], 'com.svaultai.app');
    });
  });

  group('store connection retry classification', () {
    test('healthy and purchase lifecycle states never look disconnected', () {
      for (final state in <String>[
        'ready',
        'verified',
        'reconciled',
        'pending',
        'canceled',
        'verification_failed',
        'error',
      ]) {
        expect(
          shouldShowStoreConnectionRetry(
            storeState: state,
            loading: false,
            connectionInFlight: false,
          ),
          isFalse,
          reason: '$state is not a BillingClient connection failure',
        );
      }
    });

    test('only explicit connection failures expose Retry', () {
      for (final state in <String>['unavailable', 'timed_out']) {
        expect(
          shouldShowStoreConnectionRetry(
            storeState: state,
            loading: false,
            connectionInFlight: false,
          ),
          isTrue,
        );
      }
      expect(
        shouldShowStoreConnectionRetry(
          storeState: 'ready',
          loading: false,
          connectionInFlight: false,
          connectionError: 'Google Play Billing is unavailable.',
        ),
        isTrue,
      );
      expect(
        shouldShowStoreConnectionRetry(
          storeState: 'unavailable',
          loading: true,
          connectionInFlight: false,
        ),
        isFalse,
      );
    });
  });

  group('one-product Android storage surface', () {
    testWidgets('active 50 GB plan is clear and recovery is secondary',
        (tester) async {
      var managed = false;
      var restored = false;
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(
            limitBytes: 50 * _gib,
            source: 'google_play',
            status: 'active',
            active: true,
            blockCount: 1,
          ),
          storePrice: r'$24.99',
          storeName: 'Google Play',
          onManageSubscription: () => managed = true,
          onRestorePurchases: () => restored = true,
          purchasablePlanLabel: '50 GB',
          showStorePlanSummary: true,
        ),
      );

      expect(find.text('Current plan'), findsOneWidget);
      expect(find.text('50 GB'), findsOneWidget);
      expect(find.text('Subscription active'), findsOneWidget);
      expect(find.text(r'$24.99/month'), findsOneWidget);
      expect(find.text('Managed by Google Play'), findsOneWidget);
      expect(find.text('Manage subscription'), findsOneWidget);
      expect(find.text('Having trouble?'), findsOneWidget);
      expect(find.text('Restore purchases / Refresh'), findsOneWidget);
      expect(find.text('Retry store connection'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
      expect(find.text('Self-service maximum'), findsNothing);
      expect(find.text('5 TB'), findsNothing);
      expect(find.text('100 GB'), findsNothing);

      await tester.tap(find.byKey(const Key('storage_manage_subscription')));
      await tester.tap(find.byKey(const Key('storage_restore_purchases')));
      expect(managed, isTrue);
      expect(restored, isTrue);
    });

    testWidgets('free user sees 1 GB and only the real 50 GB product',
        (tester) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(limitBytes: _gib),
          onBuyStorage: () {},
          storePrice: r'$24.99',
          storeName: 'Google Play',
          purchasablePlanLabel: '50 GB',
        ),
      );

      expect(find.text('1 GB included'), findsOneWidget);
      expect(find.text('Buy 50 GB'), findsOneWidget);
      expect(find.textContaining(r'$24.99'), findsOneWidget);
      expect(find.text('100 GB'), findsNothing);
      expect(find.text('250 GB'), findsNothing);
      expect(find.text('5 TB'), findsNothing);
    });

    testWidgets('pending purchase offers refresh but no connection retry',
        (tester) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(limitBytes: _gib),
          unavailableMessage: 'Purchase pending. Storage will update after '
              'Google confirms payment.',
          onRestorePurchases: () {},
          purchasablePlanLabel: '50 GB',
        ),
      );

      expect(find.textContaining('Purchase pending'), findsOneWidget);
      expect(find.text('Restore purchases / Refresh'), findsOneWidget);
      expect(find.text('Retry store connection'), findsNothing);
      expect(find.text('Buy 50 GB'), findsNothing);
    });

    testWidgets('canceled purchase can buy again without connection retry',
        (tester) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(limitBytes: _gib),
          unavailableMessage: 'Purchase canceled. No storage change was made.',
          onBuyStorage: () {},
          onRestorePurchases: () {},
          purchasablePlanLabel: '50 GB',
        ),
      );

      expect(find.textContaining('Purchase canceled'), findsOneWidget);
      expect(find.text('Buy 50 GB'), findsOneWidget);
      expect(find.text('Restore purchases / Refresh'), findsOneWidget);
      expect(find.text('Retry store connection'), findsNothing);
    });

    testWidgets('connection failure is the only surface with Retry',
        (tester) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(limitBytes: _gib),
          unavailableMessage: 'Google Play Billing is unavailable.',
          onRetryStore: () {},
          purchasablePlanLabel: '50 GB',
        ),
      );

      expect(find.textContaining('Google Play Billing is unavailable'),
          findsOneWidget);
      expect(find.text('Retry store connection'), findsOneWidget);
      expect(find.text('Restore purchases / Refresh'), findsNothing);
    });
  });
}
