import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/storage_page.dart';

Widget _wrap(Widget child) => MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: child),
    );

Future<void> _enlarge(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}

Map<String, dynamic> _billing({
  String source = 'none',
  String status = 'none',
  int blocks = 0,
}) =>
    {
      'used_bytes': 0,
      'effective_limit_bytes': 1073741824,
      'percent_used': 0.0,
      'account_type': 'individual',
      'self_service_max_blocks': 100,
      'included_bytes': 1073741824,
      'block_count': blocks,
      'storage_bytes_grant': 0,
      'source': source,
      'status': status,
      'has_active_subscription': status == 'active',
    };

void main() {
  testWidgets('mobile Buy storage control is responsive', (tester) async {
    await _enlarge(tester);
    var taps = 0;
    await tester.pumpWidget(_wrap(
      StorageBody(
        data: _billing(),
        onBuyStorage: () => taps++,
        onRestorePurchases: () {},
      ),
    ));
    await tester.tap(find.text('Buy storage'));
    expect(taps, 1);
    expect(find.text('Restore Purchases'), findsOneWidget);
  });

  testWidgets('active Apple plan exposes upgrade and management controls',
      (tester) async {
    await _enlarge(tester);
    var upgrades = 0;
    var manages = 0;
    await tester.pumpWidget(_wrap(
      StorageBody(
        data: _billing(source: 'apple', status: 'active', blocks: 1),
        onBuyStorage: () => upgrades++,
        onManageSubscription: () => manages++,
        onRestorePurchases: () {},
      ),
    ));
    await tester.tap(find.text('Upgrade storage'));
    await tester.tap(find.byKey(const Key('manage_subscription_button')));
    expect(upgrades, 1);
    expect(manages, 1);
  });

  testWidgets('Apple picker uses StoreKit prices and only returned products',
      (tester) async {
    await _enlarge(tester);
    await tester.pumpWidget(_wrap(const StoragePlanPicker(
      currentBlockCount: 0,
      usedBytes: 0,
      blockBytes: 53687091200,
      blockPriceCentsUsd: 0,
      selfServiceMaxBlocks: 100,
      storePrices: {1: r'$24.99', 2: r'$49.99'},
      applePurchase: true,
    )));
    expect(find.textContaining(r'$24.99/month'), findsOneWidget);
    expect(find.textContaining(r'$49.99/month'), findsOneWidget);
    expect(find.text('150 GB'), findsNothing);
    expect(find.textContaining('App Store'), findsOneWidget);
  });
}
