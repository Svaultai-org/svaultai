import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/storage_page.dart';

const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

Map<String, dynamic> _entitlement({
  String provider = 'free',
  String? productId,
  String displayTier = '1 GB',
  int storageBytes = 1073741824,
  bool active = false,
  bool webCardAllowed = true,
  String? conflictReason,
}) {
  return <String, dynamic>{
    'provider': provider,
    'source': provider,
    'product_id': productId,
    'base_plan_id': provider == 'google_play' ? 'monthly-auto' : 'monthly',
    'billing_period': 'P1M',
    'storage_bytes': storageBytes,
    'display_tier': displayTier,
    'subscription_status': active ? 'active' : 'free',
    'status': active ? 'active' : 'none',
    'entitlement_family': 'storage',
    'has_active_subscription': active,
    'web_card_purchase_allowed': webCardAllowed,
    'conflict_reason_code': conflictReason,
    'ownership_status': conflictReason == null ? 'owned' : 'conflict',
    'migration_status': 'none',
    'included_bytes': 1073741824,
    'effective_limit_bytes': storageBytes,
    'purchased_bytes': active ? storageBytes : 0,
    'used_bytes': 0,
    'percent_used': 0.0,
    'block_count': active ? 1 : 0,
    'storage_bytes_grant': 0,
    'self_service_max_blocks': 20,
  };
}

Widget _wrap(Widget child) {
  return MaterialApp(
    theme: ThemeData.dark(),
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(body: child),
  );
}

Future<void> _largeSurface(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1000, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  group('authoritative provider contract helpers', () {
    test('Google manage action uses verified product and package', () {
      final uri = providerManageSubscriptionUri(_entitlement(
        provider: 'google_play',
        productId: 'svaultai_storage_250gb',
        displayTier: '250 GB',
        storageBytes: 268435456000,
        active: true,
        webCardAllowed: false,
      ));
      expect(uri, isNotNull);
      expect(uri!.host, 'play.google.com');
      expect(uri.queryParameters['sku'], 'svaultai_storage_250gb');
      expect(uri.queryParameters['package'], 'com.svaultai.app');
    });

    test('Google manage action fails closed without verified product', () {
      expect(
        providerManageSubscriptionUri(_entitlement(
          provider: 'google_play',
          active: true,
          webCardAllowed: false,
        )),
        isNull,
      );
    });

    test('Apple manage action is Apple-specific', () {
      final uri = providerManageSubscriptionUri(_entitlement(
        provider: 'apple',
        productId: 'svaultai.storage.100gb.monthly',
        displayTier: '100 GB',
        storageBytes: 107374182400,
        active: true,
        webCardAllowed: false,
      ));
      expect(uri.toString(), 'https://apps.apple.com/account/subscriptions');
    });

    test('canonical 1 TB metadata never renders as 1000 GB', () {
      final data = _entitlement(
        provider: 'google_play',
        productId: 'svaultai_storage_1tb',
        displayTier: '',
        storageBytes: 1073741824000,
        active: true,
        webCardAllowed: false,
      );
      expect(billingDisplayTier(data), '1 TB');
      expect(formatBytes(1073741824000), '1 TB');
    });

    test('store ownership and conflicts block web-card purchase', () {
      expect(
        webCardPurchaseAllowed(_entitlement(
          provider: 'google_play',
          active: true,
          webCardAllowed: false,
        )),
        isFalse,
      );
      expect(
        webCardPurchaseAllowed(_entitlement(
          provider: 'apple',
          active: true,
          webCardAllowed: false,
        )),
        isFalse,
      );
      expect(
        webCardPurchaseAllowed(_entitlement(
          provider: 'web_card',
          active: true,
          webCardAllowed: false,
          conflictReason: 'multiple_active_storage_entitlements',
        )),
        isFalse,
      );
    });

    test('store provider wins over an inconsistent web checkout flag', () {
      expect(
        webCardPurchaseAllowed(_entitlement(
          provider: 'google_play',
          active: true,
          webCardAllowed: true,
        )),
        isFalse,
      );
      expect(
        webCardPurchaseAllowed(_entitlement(
          provider: 'apple',
          active: true,
          webCardAllowed: true,
        )),
        isFalse,
      );
    });
  });

  group('web current-plan ownership UX', () {
    testWidgets('Google 250 GB shows owner, status, manage, and no buy',
        (tester) async {
      await _largeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(
          provider: 'google_play',
          productId: 'svaultai_storage_250gb',
          displayTier: '250 GB',
          storageBytes: 268435456000,
          active: true,
          webCardAllowed: false,
        ),
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));

      expect(find.text('Current plan'), findsOneWidget);
      expect(find.text('250 GB'), findsWidgets);
      expect(find.text('Subscription active'), findsOneWidget);
      expect(find.text('Billed through Google Play'), findsOneWidget);
      expect(find.text('Manage subscription'), findsOneWidget);
      expect(find.text('Buy storage'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
    });

    testWidgets('Apple shows Apple owner and no web purchase', (tester) async {
      await _largeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(
          provider: 'apple',
          productId: 'svaultai.storage.100gb.monthly',
          displayTier: '100 GB',
          storageBytes: 107374182400,
          active: true,
          webCardAllowed: false,
        ),
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));

      expect(find.text('100 GB'), findsWidgets);
      expect(find.text('Billed through Apple'), findsOneWidget);
      expect(find.text('Manage subscription'), findsOneWidget);
      expect(find.text('Buy storage'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
    });

    testWidgets('free state is explicit', (tester) async {
      await _largeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(),
        unavailableMessage: 'Web billing is not configured.',
      )));

      expect(find.text('Current plan'), findsOneWidget);
      expect(find.text('Free — 1 GB'), findsOneWidget);
      expect(find.text('Subscription active'), findsNothing);
    });

    testWidgets('web-card representative tier has web billing label',
        (tester) async {
      await _largeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(
          provider: 'web_card',
          productId: 'svaultai_web_50gb',
          displayTier: '50 GB',
          storageBytes: 53687091200,
          active: true,
        ),
        onManageSubscription: () {},
      )));

      expect(find.text('Billed on SVaultAI web'), findsOneWidget);
      expect(find.text('Manage billing'), findsOneWidget);
    });

    testWidgets('conflict surfaces safe state and hides purchase',
        (tester) async {
      await _largeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(
          provider: 'google_play',
          productId: 'svaultai_storage_50gb',
          displayTier: '50 GB',
          storageBytes: 53687091200,
          active: true,
          webCardAllowed: false,
          conflictReason: 'multiple_active_storage_entitlements',
        ),
        onBuyStorage: () {},
      )));

      expect(find.byKey(const Key('storage_billing_owner_conflict')),
          findsOneWidget);
      expect(find.text('Buy storage'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
    });
  });
}
