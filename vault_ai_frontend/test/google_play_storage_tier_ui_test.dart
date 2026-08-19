import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/storage_page.dart';

const int _gib = 1024 * 1024 * 1024;

const List<StoreStorageTierChoice> _allChoices = <StoreStorageTierChoice>[
  StoreStorageTierChoice(
    productId: 'svaultai_storage_50gb',
    capacityLabel: '50 GB',
    localizedPrice: r'US$24.99',
    rank: 1,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_100gb',
    capacityLabel: '100 GB',
    localizedPrice: r'US$49.99',
    rank: 2,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_150gb',
    capacityLabel: '150 GB',
    localizedPrice: '€69.99',
    rank: 3,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_200gb',
    capacityLabel: '200 GB',
    localizedPrice: '£99.99',
    rank: 4,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_250gb',
    capacityLabel: '250 GB',
    localizedPrice: r'US$124.99',
    rank: 5,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_300gb',
    capacityLabel: '300 GB',
    localizedPrice: r'US$149.99',
    rank: 6,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_500gb',
    capacityLabel: '500 GB',
    localizedPrice: r'US$249.99',
    rank: 7,
  ),
  StoreStorageTierChoice(
    productId: 'svaultai_storage_1tb',
    capacityLabel: '1 TB',
    localizedPrice: r'US$499.99',
    rank: 8,
  ),
];

Map<String, dynamic> _entitlement({
  int limitBytes = _gib,
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
  tester.view.physicalSize = const Size(1200, 4200);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(_wrap(body));
  await tester.pumpAndSettle();
}

void main() {
  group('tier visibility contract', () {
    test('free users receive every real tier in catalog order', () {
      final visible = selectableGooglePlayStorageTiers(_allChoices);
      expect(
        visible.map((choice) => choice.rank),
        orderedEquals(<int>[1, 2, 3, 4, 5, 6, 7, 8]),
      );
    });

    for (final scenario in <(int, List<int>)>[
      (1, <int>[2, 3, 4, 5, 6, 7, 8]),
      (2, <int>[3, 4, 5, 6, 7, 8]),
      (5, <int>[6, 7, 8]),
      (8, <int>[]),
    ]) {
      test('active tier rank ${scenario.$1} exposes only higher tiers', () {
        final visible = selectableGooglePlayStorageTiers(
          _allChoices,
          currentTierRank: scenario.$1,
          hasActiveSubscription: true,
        );
        expect(
          visible.map((choice) => choice.rank),
          orderedEquals(scenario.$2),
        );
      });
    }

    test('unknown active entitlement fails closed', () {
      expect(
        selectableGooglePlayStorageTiers(
          _allChoices,
          hasActiveSubscription: true,
        ),
        isEmpty,
      );
    });
  });

  group('multi-tier storage UI', () {
    testWidgets('free state shows 1 GB and all ProductDetails prices', (
      tester,
    ) async {
      String? selected;
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(),
          storeTierChoices: _allChoices,
          onSelectStoreTier: (productId) => selected = productId,
        ),
      );

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('1 GB included'), findsOneWidget);
      expect(find.text('Choose storage'), findsOneWidget);
      for (final choice in _allChoices) {
        expect(find.text(choice.capacityLabel), findsOneWidget);
        expect(find.text('${choice.localizedPrice}/month'), findsOneWidget);
      }
      expect(find.text('5 TB'), findsNothing);

      await tester.tap(
        find.byKey(const Key('storage_tier_svaultai_storage_150gb')),
      );
      expect(selected, 'svaultai_storage_150gb');
    });

    testWidgets('active 50 GB state shows current plan and higher tiers only', (
      tester,
    ) async {
      final choices = selectableGooglePlayStorageTiers(
        _allChoices,
        currentTierRank: 1,
        hasActiveSubscription: true,
      );
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
          storePrice: r'US$24.99',
          storeName: 'Google Play',
          showStorePlanSummary: true,
          onManageSubscription: () {},
          onRestorePurchases: () {},
          storeTierChoices: choices,
          onSelectStoreTier: (_) {},
        ),
      );

      expect(find.text('Current plan'), findsOneWidget);
      expect(find.text('50 GB'), findsOneWidget);
      expect(find.text(r'US$24.99/month'), findsOneWidget);
      expect(find.text('Subscription active'), findsOneWidget);
      expect(find.text('Managed by Google Play'), findsOneWidget);
      expect(find.text('Upgrade storage'), findsOneWidget);
      expect(
        find.byKey(const Key('storage_tier_svaultai_storage_50gb')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('storage_tier_svaultai_storage_100gb')),
        findsOneWidget,
      );
      expect(find.text('Retry store connection'), findsNothing);
    });

    for (final scenario in <(int, int, String, String)>[
      (2, 100, '100 GB', 'svaultai_storage_150gb'),
      (5, 250, '250 GB', 'svaultai_storage_300gb'),
    ]) {
      testWidgets(
        'active ${scenario.$3} state exposes only higher Play tiers',
        (tester) async {
          final choices = selectableGooglePlayStorageTiers(
            _allChoices,
            currentTierRank: scenario.$1,
            hasActiveSubscription: true,
          );
          await _pump(
            tester,
            StorageBody(
              data: _entitlement(
                limitBytes: scenario.$2 * _gib,
                source: 'google_play',
                status: 'active',
                active: true,
                blockCount: scenario.$1,
              ),
              activeStorePlanLabel: scenario.$3,
              storePrice: r'US$49.99',
              storeName: 'Google Play',
              showStorePlanSummary: true,
              onManageSubscription: () {},
              onRestorePurchases: () {},
              storeTierChoices: choices,
              onSelectStoreTier: (_) {},
            ),
          );

          expect(find.text(scenario.$3), findsOneWidget);
          expect(find.text('Upgrade storage'), findsOneWidget);
          for (final choice in _allChoices) {
            final finder = find.byKey(Key('storage_tier_${choice.productId}'));
            expect(
              finder,
              choice.rank > scenario.$1 ? findsOneWidget : findsNothing,
            );
          }
        },
      );
    }

    testWidgets('active 1 TB state exposes no downgrade or stacking action', (
      tester,
    ) async {
      final choices = selectableGooglePlayStorageTiers(
        _allChoices,
        currentTierRank: 8,
        hasActiveSubscription: true,
      );
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(
            limitBytes: 1000 * _gib,
            source: 'google_play',
            status: 'active',
            active: true,
            blockCount: 20,
          ),
          storePrice: r'US$499.99',
          activeStorePlanLabel: '1 TB',
          storeName: 'Google Play',
          showStorePlanSummary: true,
          onManageSubscription: () {},
          onRestorePurchases: () {},
          storeTierChoices: choices,
        ),
      );

      expect(find.text('Current plan'), findsOneWidget);
      expect(find.text('1 TB'), findsOneWidget);
      expect(find.text('Choose storage'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
      expect(find.textContaining('Buy '), findsNothing);
    });

    testWidgets('pending disables every tier and keeps recovery secondary', (
      tester,
    ) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(),
          busy: true,
          unavailableMessage: 'Purchase pending. Storage will update after '
              'Google confirms payment.',
          onRestorePurchases: () {},
          storeTierChoices: _allChoices,
          onSelectStoreTier: (_) {},
        ),
      );

      expect(find.textContaining('Purchase pending'), findsOneWidget);
      expect(find.text('Restore purchases / Refresh'), findsOneWidget);
      expect(find.text('Retry store connection'), findsNothing);
      final button = tester.widget<OutlinedButton>(
        find.byKey(const Key('storage_tier_svaultai_storage_50gb')),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('connection error alone exposes Retry store connection', (
      tester,
    ) async {
      await _pump(
        tester,
        StorageBody(
          data: _entitlement(),
          unavailableMessage: 'Google Play Billing is unavailable.',
          onRetryStore: () {},
        ),
      );

      expect(
        find.textContaining('Google Play Billing is unavailable'),
        findsOneWidget,
      );
      expect(find.text('Retry store connection'), findsOneWidget);
      expect(find.text('Choose storage'), findsNothing);
    });
  });
}
