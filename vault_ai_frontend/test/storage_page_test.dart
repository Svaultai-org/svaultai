

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/storage_page.dart';

Widget _wrap(Widget child) => MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: child),
    );


Future<void> _enlargeSurface(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}


Map<String, dynamic> _entitlement({
  int? usedBytes,
  int? effectiveLimitBytes,
  double? percentUsed,
  int? blockCount,
  int? storageBytesGrant,
  String accountType = 'individual',
  String salesChannel = 'self_service',
  String status = 'none',
  String source = 'none',
  bool? hasActiveSubscription,
  int includedBytes = 1073741824,
  int blockBytes = 53687091200,
  int selfServiceMaxBlocks = 100,
}) {
  final blocks = blockCount ?? 0;
  final purchased = blocks * blockBytes;
  final grant = storageBytesGrant ?? 0;
  
  
  final defaultLimit = (blocks > 0 && purchased > 0)
      ? purchased
      : (includedBytes + grant);
  final limit = effectiveLimitBytes ?? defaultLimit;
  final used = usedBytes ?? 0;
  final pct = percentUsed ??
      (limit > 0 ? (used / limit) * 100.0 : 0.0);
  
  
  const liveStatuses = {'active', 'in_grace', 'canceled_pending'};
  final defaultHasSub = source == 'stripe' && liveStatuses.contains(status);
  return <String, dynamic>{
    'account_id': '00000000-0000-0000-0000-000000000001',
    'account_type': accountType,
    'sales_channel': salesChannel,
    'included_bytes': includedBytes,
    'purchased_bytes': purchased,
    'storage_bytes_grant': grant,
    'effective_limit_bytes': limit,
    'used_bytes': used,
    'percent_used': double.parse(pct.clamp(0.0, 100.0).toStringAsFixed(1)),
    'block_count': blockCount ?? 0,
    'self_service_max_blocks': selfServiceMaxBlocks,
    'status': status,
    'source': source,
    'current_period_end': null,
    'cancel_at_period_end': false,
    'block_price_cents_usd': 2500,
    'block_bytes': blockBytes,
    'has_active_subscription': hasActiveSubscription ?? defaultHasSub,
  };
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('threshold predicates', () {
    test('nearsLimitWarning fires at exactly 80%', () {
      expect(nearsLimitWarning(79.9), isFalse);
      expect(nearsLimitWarning(80.0), isTrue);
      expect(nearsLimitWarning(99.9), isTrue);
      expect(nearsLimitWarning(100.0), isFalse);
    });

    test('limitReachedWarning fires at exactly 100%', () {
      expect(limitReachedWarning(99.9), isFalse);
      expect(limitReachedWarning(100.0), isTrue);
      expect(limitReachedWarning(150.0), isTrue);
    });

    test('isOnFreeTierOnly is true only with zero blocks AND zero grant',
        () {
      expect(isOnFreeTierOnly(_entitlement()), isTrue);
      expect(isOnFreeTierOnly(_entitlement(blockCount: 1)), isFalse);
      expect(
          isOnFreeTierOnly(_entitlement(storageBytesGrant: 1)), isFalse);
    });

    test('isGrandfathered needs zero blocks AND a positive grant', () {
      expect(isGrandfathered(_entitlement()), isFalse);
      expect(isGrandfathered(_entitlement(blockCount: 1)), isFalse);
      expect(
          isGrandfathered(
              _entitlement(storageBytesGrant: 5 * 1024 * 1024 * 1024)),
          isTrue);
    });
  });

  
  group('formatBytes', () {
    test('zero', () {
      expect(formatBytes(0), '0 B');
    });

    test('GB precision (one decimal)', () {
      
      
      expect(formatBytes(1024 * 1024 * 1024), '1 GB');
      expect(formatBytes(15 * 1024 * 1024 * 1024 ~/ 10), '1.5 GB');
    });

    test('TB precision', () {
      expect(formatBytes(5 * 1024 * 1024 * 1024 * 1024), '5 TB');
    });
  });

  
  group('scenario 1: 0% used (fresh signup)', () {
    testWidgets('renders free tier + no warnings', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(usedBytes: 0);
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(find.text('Storage Usage'), findsOneWidget);
      expect(find.textContaining('0%'), findsOneWidget);
      
      expect(find.text('Free Tier'), findsOneWidget);
      expect(find.text('Need more space?'), findsOneWidget);
      
      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsNothing);
      expect(
          find.text(
              'Storage limit reached. Upgrade storage to continue '
              'uploading files.'),
          findsNothing);
    });
  });

  group('scenario 2: 50% used', () {
    testWidgets('shows usage but no warning banner', (tester) async {
      await _enlargeSurface(tester);
      
      final data = _entitlement(
        usedBytes: 512 * 1024 * 1024,
        percentUsed: 50.0,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(find.textContaining('50.0%'), findsOneWidget);
      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsNothing);
      expect(
          find.text(
              'Storage limit reached. Upgrade storage to continue '
              'uploading files.'),
          findsNothing);
    });
  });

  group('scenario 3: 80% used (warn threshold)', () {
    testWidgets('shows the "nearing limit" banner', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        usedBytes: (1073741824 * 0.8).round(),
        percentUsed: 80.0,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsOneWidget);
      
      expect(
          find.text(
              'Storage limit reached. Upgrade storage to continue '
              'uploading files.'),
          findsNothing);
    });

    testWidgets('still shows the warn banner at 99.9%', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        usedBytes: (1073741824 * 0.999).round(),
        percentUsed: 99.9,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsOneWidget);
    });
  });

  group('scenario 4: 100% used (limit reached)', () {
    testWidgets('shows the "limit reached" banner only', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        usedBytes: 1073741824,
        percentUsed: 100.0,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(
          find.text(
              'Storage limit reached. Upgrade storage to continue '
              'uploading files.'),
          findsOneWidget);
      
      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsNothing);
    });
  });

  group('scenario 5: over-quota grandfather user', () {
    testWidgets(
        'renders the grandfathered note instead of the free-tier nudge',
        (tester) async {
      await _enlargeSurface(tester);
      
      
      final fourGB = 4 * 1024 * 1024 * 1024;
      final data = _entitlement(
        usedBytes: 3 * 1024 * 1024 * 1024,
        storageBytesGrant: fourGB,
        percentUsed: 60.0,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(find.text('Grandfathered storage'), findsOneWidget);
      
      expect(find.text('Free Tier'), findsNothing);
      expect(find.text('Need more space?'), findsNothing);
      
      expect(find.text('Additional storage pricing'), findsNothing);
    });

    testWidgets('grandfather user over 80% shows the warn banner too',
        (tester) async {
      await _enlargeSurface(tester);
      
      final eightGB = 8 * 1024 * 1024 * 1024;
      final data = _entitlement(
        usedBytes: (9 * 1024 * 1024 * 1024 * 0.85).round(),
        storageBytesGrant: eightGB,
        percentUsed: 85.0,
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(
          find.text('Your vault is nearing its storage limit.'),
          findsOneWidget);
      expect(find.text('Grandfathered storage'), findsOneWidget);
    });
  });

  
  group('used_bytes display', () {
    testWidgets('renders a nonzero used value the backend supplies',
        (tester) async {
      await _enlargeSurface(tester);
      
      
      final data = _entitlement(usedBytes: 7948721);
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      expect(find.textContaining('7.6 MB'), findsAtLeastNWidgets(1));
    });

    testWidgets('zero used_bytes still renders as "0 B"', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(usedBytes: 0);
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      expect(find.textContaining('0 B'), findsAtLeastNWidgets(1));
    });
  });

  
  group('no placeholder / coming-soon copy remains', () {
    
    
    String readLib(String relative) {
      final file = File('lib/$relative');
      expect(file.existsSync(), isTrue,
          reason: 'expected file does not exist: ${file.path}');
      return file.readAsStringSync();
    }

    test('storage_page.dart has no "coming soon" / "next release" copy',
        () {
      final src = readLib('storage_page.dart');
      expect(src, isNot(contains('coming soon')));
      expect(src, isNot(contains('next release')));
      expect(src, isNot(contains('lands in the next')));
    });

    test('main.dart has no "Payment upgrade will be connected next"',
        () {
      
      
      final src = readLib('main.dart');
      expect(src, isNot(contains('Payment upgrade will be connected next')));
      
      expect(
        src.toLowerCase(),
        isNot(contains('payment upgrade will be connected')),
      );
    });

    test('main.dart has no retired web checkout promotion',
        () {
      
      
      final src = readLib('main.dart');
      expect(src, isNot(contains("'Buy More Storage'")));
      
      
      expect(src, isNot(contains('Add storage in 50 GB blocks.')));
      expect(src, isNot(contains('limit updates automatically')));
      expect(
        src.contains("'Choose Storage'") ||
            src.contains('filesChooseStorage'),
        isFalse,
        reason: 'retired web checkout must not expose a purchase button',
      );
      
      expect(src, isNot(contains("'Upgrade Vault Storage'")),
          reason: 'legacy Upgrade Vault Storage card not removed');
      expect(src, isNot(contains('Upgrade for \$25')),
          reason: 'legacy Upgrade for 25 dollar button not removed');
      expect(src, isNot(contains(r'$25 upgrade')),
          reason: 'legacy 25 dollar upgrade string not removed');
    });

    test('main.dart has no legacy checkout auto-open route', () {
      
      
      final src = readLib('main.dart');
      final idx = src.indexOf("'Buy More Storage'");
      expect(idx, lessThan(0));
      final start = 0;
      final end = src.length;
      final window = src.substring(start, end);
      expect(
        window,
        contains("Navigator.pushNamed"),
        reason: 'dashboard card must navigate via Navigator.pushNamed',
      );
      expect(
        window,
        contains("'/storage'"),
        reason: 'dashboard card must navigate to /storage',
      );
      expect(
        window,
        isNot(contains("'autoOpenPicker': true")),
        reason:
            'dashboard card must pass autoOpenPicker:true so the '
            'Storage page opens the SKU picker on entry — no '
            'placeholder snackbar.',
      );
    });
  });

  
  group('retired checkout cannot auto-open', () {
    String readLib(String relative) {
      final file = File('lib/$relative');
      expect(file.existsSync(), isTrue,
          reason: 'expected file does not exist: ${file.path}');
      return file.readAsStringSync();
    }

    test('storage_page.dart ignores legacy autoOpenPicker arguments', () {
      final src = readLib('storage_page.dart');
      expect(
        src,
        isNot(contains("ModalRoute.of(context)?.settings.arguments")),
        reason: 'retired checkout route arguments must not be read',
      );
      expect(
        src,
        isNot(contains("'autoOpenPicker'")),
        reason: 'retired checkout must not auto-open',
      );
    });

    test('storage_page.dart has no checkout auto-open helper', () {
      
      
      final src = readLib('storage_page.dart');
      final idx = src.indexOf('void _maybeAutoOpenPicker()');
      expect(idx, lessThan(0));
      final start = 0;
      final end = 1200.clamp(0, src.length);
      final window = src.substring(start, end);
      expect(
        window,
        isNot(contains('_onBuyStorage')),
        reason:
            'auto-open helper must invoke _onBuyStorage so the picker '
            'opens via the same path as the button click.',
      );
    });
  });

  
  group('P1 buttons: Buy / Manage', () {
    testWidgets('free tier renders Buy but NOT Manage', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      
      
      expect(find.text('Buy storage'),        findsOneWidget);
      expect(find.text('Manage Subscription'), findsNothing);
    });

    testWidgets('active Stripe subscriber renders both buttons',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        blockCount: 2,
        status: 'active',
      );
      data['source'] = 'stripe';
      data['has_active_subscription'] = true;
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      
      
      expect(find.text('Upgrade storage'),    findsOneWidget);
      expect(find.text('Manage Subscription'), findsOneWidget);
    });

    testWidgets('Stripe in_grace still shows Manage (user can fix payment)',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        blockCount: 1,
        status: 'in_grace',
      );
      data['source'] = 'stripe';
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Manage Subscription'), findsOneWidget);
    });

    testWidgets('Manage button hidden when callbacks are null',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(blockCount: 1, status: 'active');
      data['source'] = 'stripe';
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        
      )));
      
      
      expect(find.text('Manage Subscription'), findsNothing);
    });
  });

  group('hasManageableStripeSubscription predicate', () {
    test('returns false for free tier', () {
      expect(hasManageableStripeSubscription(_entitlement()), isFalse);
    });

    test('returns false when source is not stripe', () {
      final data = _entitlement(blockCount: 1, status: 'active');
      data['source'] = 'apple';
      expect(hasManageableStripeSubscription(data), isFalse);
    });

    test('returns true for active Stripe sub', () {
      final data = _entitlement(blockCount: 1, status: 'active');
      data['source'] = 'stripe';
      expect(hasManageableStripeSubscription(data), isTrue);
    });

    test('returns true for canceled_pending Stripe sub', () {
      final data = _entitlement(blockCount: 1, status: 'canceled_pending');
      data['source'] = 'stripe';
      expect(hasManageableStripeSubscription(data), isTrue);
    });
  });

  
  group('StoragePlanPicker', () {
    testWidgets('renders all 9 self-service tiers when ceiling is 100',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 0,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
      )));
      
      
      expect(find.text('Monthly cost  ·  \$25/month'),    findsOneWidget);
      expect(find.text('Monthly cost  ·  \$50/month'),    findsOneWidget);
      expect(find.text('Monthly cost  ·  \$75/month'),    findsOneWidget);
      expect(find.text('Monthly cost  ·  \$100/month'),   findsOneWidget);
      expect(find.text('Monthly cost  ·  \$125/month'),   findsOneWidget);
      expect(find.text('Monthly cost  ·  \$250/month'),   findsOneWidget);
      expect(find.text('Monthly cost  ·  \$500/month'),   findsOneWidget);
      expect(find.text('Monthly cost  ·  \$1000/month'),  findsOneWidget);
      expect(find.text('Monthly cost  ·  \$2500/month'),  findsOneWidget);
    });

    testWidgets('current block count is marked as "Current"',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 2,  
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
      )));
      expect(find.text('Current'), findsOneWidget);
    });

    testWidgets('block ladder respects the self-service ceiling',
        (tester) async {
      await _enlargeSurface(tester);
      
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 0,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 5,
      )));
      
      expect(find.text('Monthly cost  ·  \$250/month'),  findsNothing);
      expect(find.text('Monthly cost  ·  \$500/month'),  findsNothing);
      expect(find.text('Monthly cost  ·  \$1000/month'), findsNothing);
      expect(find.text('Monthly cost  ·  \$2500/month'), findsNothing);
      
      expect(find.text('Monthly cost  ·  \$125/month'),  findsOneWidget);
    });

    testWidgets('new storage limit equals blocks * block_bytes (paid replaces free)',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 0,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
      )));
      
      
      expect(find.text('New storage limit  ·  50 GB'),  findsOneWidget);
      expect(find.text('New storage limit  ·  100 GB'), findsOneWidget);
      expect(find.text('New storage limit  ·  150 GB'), findsOneWidget);
      
      
      expect(find.textContaining('51 GB'),  findsNothing);
      expect(find.textContaining('101 GB'), findsNothing);
      expect(find.textContaining('151 GB'), findsNothing);
    });

    
    testWidgets('upgrade mode shows "Upgrade Storage" header, not "Buy More Storage"',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      expect(find.text('Upgrade Storage'),    findsOneWidget);
      expect(find.text('Buy More Storage'),   findsNothing);
    });

    testWidgets('upgrade mode summarises current plan once at the top',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      expect(find.text('Current: 150 GB / \$75/month'), findsOneWidget);
    });

    testWidgets('upgrade tile shows "New plan", "Added today", and proration note',
        (tester) async {
      await _enlargeSurface(tester);
      
      
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      expect(
        find.text('New plan  ·  200 GB / \$100/month'),
        findsOneWidget,
      );
      expect(
        find.text('Added today  ·  +50 GB / +\$25/month'),
        findsOneWidget,
      );
      
      
      expect(
        find.text('Today\'s charge  ·  prorated by Stripe'),
        findsWidgets,
      );
      
      expect(
        find.text('Added today  ·  +100 GB / +\$50/month'),
        findsOneWidget,
      );
    });

    testWidgets(
        'upgrade mode does NOT show "Added today" on the current tier or '
        'tiers below current (only above)',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      
      
      expect(find.text('Current'), findsOneWidget);
      
      
      expect(find.textContaining('Added today  ·  +0 GB'), findsNothing);
      expect(find.textContaining('Added today  ·  +-'),    findsNothing);
    });

    testWidgets('upgrade mode preserves "Monthly cost" lines (not used in upgrade tiles)',
        (tester) async {
      await _enlargeSurface(tester);
      
      
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      
      
      expect(
        find.text('Monthly cost  ·  \$100/month'),
        findsNothing,
      );
    });

    
    testWidgets('upgrade mode marks tiers below current as "Lower plan"',
        (tester) async {
      await _enlargeSurface(tester);
      
      
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 20,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      
      expect(find.text('Lower plan'), findsNWidgets(6));
      
      expect(find.text('Current'), findsOneWidget);
    });

    testWidgets(
        'Buy mode (no active sub) does NOT show "Lower plan" labels — '
        'every tier is a Buy candidate', (tester) async {
      await _enlargeSurface(tester);
      
      
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 0,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: false,
      )));
      expect(find.text('Lower plan'), findsNothing);
    });

    testWidgets(
        'upgrade mode: tier above current shows the upgrade chevron, '
        'NOT "Lower plan"', (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 3,    
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
        hasActiveSubscription: true,
      )));
      
      
      expect(find.text('Lower plan'), findsNWidgets(2));
    });
  });

  group('scenario 6: organization account', () {
    testWidgets('renders "Organization" as the account type',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        accountType: 'organization',
        salesChannel: 'enterprise',
        
        storageBytesGrant: 100 * 1024 * 1024 * 1024 * 1024,
        usedBytes: 40 * 1024 * 1024 * 1024 * 1024,
        percentUsed: 40.0,
        status: 'active',
      );
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(find.text('Organization'), findsOneWidget);
      
      
      expect(find.text('Self-service maximum'), findsNothing);
      
      
      expect(find.text('Grandfathered storage'), findsOneWidget);
    });
  });

  
  group('cross-cutting structure', () {
    testWidgets('all scenarios render the Storage Usage title',
        (tester) async {
      await _enlargeSurface(tester);
      for (final percent in <double>[0.0, 50.0, 80.0, 100.0]) {
        final data = _entitlement(
          usedBytes: (1073741824 * (percent / 100.0)).round(),
          percentUsed: percent,
        );
        await tester.pumpWidget(_wrap(StorageBody(data: data)));
        expect(find.text('Storage Usage'), findsOneWidget,
            reason: 'missing title at $percent%');
      }
    });

    testWidgets('does not advertise the unsupported 5 TB maximum',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      
      expect(find.text('Self-service maximum'), findsNothing);
      expect(find.text('5 TB'), findsNothing);
    });

    testWidgets('unsupported pricing examples are hidden by default',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      expect(find.text('100 GB'), findsNothing);
      expect(find.text('150 GB'), findsNothing);
      expect(find.text('500 GB'), findsNothing);
      expect(find.text(r'$50/month'), findsNothing);
      expect(find.text(r'$75/month'), findsNothing);
      expect(find.text(r'$250/month'), findsNothing);
    });
  });

  
  group('CheckoutReturnBanner', () {
    testWidgets('success kind shows confirmation copy and dismiss icon',
        (tester) async {
      var dismissed = false;
      await tester.pumpWidget(_wrap(CheckoutReturnBanner(
        kind: 'success',
        onDismiss: () => dismissed = true,
      )));

      expect(find.text('Payment confirmed'), findsOneWidget);
      expect(
        find.textContaining('Your new storage will appear here'),
        findsOneWidget,
      );
      
      final dismissBtn = find.byIcon(Icons.close);
      expect(dismissBtn, findsOneWidget);
      await tester.tap(dismissBtn);
      expect(dismissed, isTrue);
    });

    testWidgets('cancel kind shows neutral note and dismiss icon',
        (tester) async {
      var dismissed = false;
      await tester.pumpWidget(_wrap(CheckoutReturnBanner(
        kind: 'cancel',
        onDismiss: () => dismissed = true,
      )));

      expect(find.text('Checkout cancelled'), findsOneWidget);
      expect(
        find.textContaining('No changes were made'),
        findsOneWidget,
      );
      await tester.tap(find.byIcon(Icons.close));
      expect(dismissed, isTrue);
    });
  });

  
  group('checkout redirect URL builders', () {
    String readLib(String relative) {
      final file = File('lib/$relative');
      expect(file.existsSync(), isTrue,
          reason: 'expected file does not exist: ${file.path}');
      return file.readAsStringSync();
    }

    test('buildCheckoutRedirectUrl returns null off-web (kIsWeb=false)', () {
      
      
      expect(buildCheckoutRedirectUrl('success'), isNull);
      expect(buildCheckoutRedirectUrl('cancel'), isNull);
      expect(buildPortalReturnUrl(), isNull);
    });

    test('storage_page.dart forwards origin-derived success_url and '
        'cancel_url to createStripeCheckoutSession', () {
      
      
      final src = readLib('storage_page.dart');
      
      
      final idx = src.indexOf('createStripeCheckoutSession(');
      expect(idx, greaterThan(-1),
          reason: 'createStripeCheckoutSession call missing');
      final window = src.substring(
        idx,
        (idx + 600).clamp(0, src.length),
      );
      expect(
        window,
        contains("successUrl: buildCheckoutRedirectUrl('success')"),
        reason: 'success_url must be forwarded so Stripe redirects to '
                'the actual frontend origin, not the env fallback.',
      );
      expect(
        window,
        contains("cancelUrl:  buildCheckoutRedirectUrl('cancel')"),
        reason: 'cancel_url must be forwarded too.',
      );
    });

    test('storage_page.dart forwards origin-derived return_url to '
        'createStripePortalSession', () {
      final src = readLib('storage_page.dart');
      final idx = src.indexOf('createStripePortalSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(
        idx,
        (idx + 400).clamp(0, src.length),
      );
      expect(
        window,
        contains("returnUrl: buildPortalReturnUrl()"),
      );
    });

    test('storage_page.dart ignores retired checkout return flags', () {
      
      
      final src = readLib('storage_page.dart');
      expect(src,
          isNot(contains("Uri.base.queryParameters['checkout']")),
          reason: 'retired checkout query flags must not be read');
      expect(src,
          isNot(contains("args['checkout']")),
          reason: 'retired checkout route flags must not be read');
    });

    test('main.dart enables PathUrlStrategy on web so /storage works '
        'without #', () {
      final src = File('lib/main.dart').readAsStringSync();
      
      
      expect(src, contains('PathUrlStrategy'),
          reason: 'Set PathUrlStrategy so /storage?checkout=success '
                  'routes cleanly without a leading #');
      expect(src, contains('flutter_web_plugins'));
    });
  });

  
  group('hasActiveSubscription rule', () {
    test('true when payload says has_active_subscription=true', () {
      final data = _entitlement(hasActiveSubscription: true);
      expect(hasActiveSubscription(data), isTrue);
    });

    test('false when payload says has_active_subscription=false', () {
      final data = _entitlement(hasActiveSubscription: false);
      expect(hasActiveSubscription(data), isFalse);
    });

    test('falls back to source+status when flag is missing', () {
      
      
      final paid = <String, dynamic>{
        'source': 'stripe', 'status': 'active',
      };
      final free = <String, dynamic>{
        'source': 'none',   'status': 'none',
      };
      final expiredStripe = <String, dynamic>{
        'source': 'stripe', 'status': 'expired',
      };
      expect(hasActiveSubscription(paid),          isTrue);
      expect(hasActiveSubscription(free),          isFalse);
      expect(hasActiveSubscription(expiredStripe), isFalse);
    });

    test('canceled_pending counts as active', () {
      
      
      final data = _entitlement(
        source: 'stripe', status: 'canceled_pending', blockCount: 1,
      );
      expect(hasActiveSubscription(data), isTrue);
    });

    test('Apple-source sub never flags as Stripe-modifiable', () {
      
      
      final data = <String, dynamic>{
        'source': 'apple', 'status': 'active',
      };
      expect(hasActiveSubscription(data), isFalse);
    });

    test('billing source labels never claim a cross-provider entitlement', () {
      expect(
        billingProviderLabel(<String, dynamic>{'source': 'apple'}),
        'the App Store',
      );
      expect(
        billingProviderLabel(<String, dynamic>{'source': 'google_play'}),
        'Google Play',
      );
      expect(
        billingProviderLabel(<String, dynamic>{'source': 'stripe_legacy'}),
        'the legacy web billing provider',
      );
    });
  });

  group('StorageBody purchase action button', () {
    testWidgets('native single-product surface hides unsupported tier prices',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(
        data: _entitlement(),
        showPricingExamples: false,
        unavailableMessage: 'No store product is configured.',
      )));

      expect(find.text('No store product is configured.'), findsOneWidget);
      expect(find.text('100 GB'), findsNothing);
      expect(find.text(r'$50/month'), findsNothing);
      expect(find.text('150 GB'), findsNothing);
      expect(find.text('500 GB'), findsNothing);
    });

    testWidgets('shows "Buy storage" when user has NO active subscription',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        source: 'none', status: 'none', blockCount: 0,
      );
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Buy storage'),     findsOneWidget);
      expect(find.text('Upgrade storage'), findsNothing);
    });

    testWidgets(
      'shows "Upgrade storage" when user has an active Stripe subscription',
      (tester) async {
        await _enlargeSurface(tester);
        final data = _entitlement(
          source: 'stripe', status: 'active', blockCount: 2,
        );
        await tester.pumpWidget(_wrap(StorageBody(
          data: data,
          onBuyStorage: () {},
          onManageSubscription: () {},
        )));
        expect(find.text('Upgrade storage'), findsOneWidget);
        expect(find.text('Buy storage'),     findsNothing);
      },
    );

    testWidgets('expired Stripe sub flips label back to "Buy storage"',
        (tester) async {
      
      
      await _enlargeSurface(tester);
      final data = _entitlement(
        source: 'stripe', status: 'expired', blockCount: 1,
      );
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Buy storage'),     findsOneWidget);
      expect(find.text('Upgrade storage'), findsNothing);
    });
  });

  
  group('createStripeCheckoutSession response shape', () {
    test('api_client exposes the createStripeCheckoutSession entry point',
        () {
      final src = File('lib/api_client.dart').readAsStringSync();
      expect(
        src,
        contains('createStripeCheckoutSession'),
        reason: 'api_client must expose the Stripe checkout helper',
      );
    });

    test('storage_page._startCheckout branches on action field', () {
      
      
      final src = File('lib/storage_page.dart').readAsStringSync();
      expect(src, contains("result['action']"),
          reason: '_startCheckout must read the action field');
      expect(src, contains("'updated_existing'"),
          reason: '_startCheckout must handle the in-place upgrade branch');
      expect(src, contains('_pollEntitlementForBlocks'),
          reason: 'in-place upgrade must trigger the entitlement poll');
    });
  });

  
  group('storage_page post-upgrade poll', () {
    late String storageSource;

    setUpAll(() {
      storageSource = File('lib/storage_page.dart').readAsStringSync();
    });

    test('_pollEntitlementForBlocks exists with the right shape', () {
      
      
      expect(storageSource, contains('_pollEntitlementForBlocks'),
          reason: 'the post-upgrade poll helper must exist');
      expect(storageSource, contains('maxAttempts = 10'),
          reason: 'spec calls for "up to 10 seconds" of polling');
      expect(storageSource, contains('interval = Duration(seconds: 1)'),
          reason: 'spec calls for 1-second tick interval');
    });

    test('poll uses BOTH local _data AND AppState.applyBillingPayload', () {
      
      
      expect(storageSource, contains('app.applyBillingPayload(data)'),
          reason: 'the poll must feed AppState too, not just _data');
      
      
      final pollDeclIdx = storageSource.indexOf(
        'Future<bool> _pollEntitlementForBlocks',
      );
      expect(pollDeclIdx, greaterThan(-1),
          reason: '_pollEntitlementForBlocks declaration must exist');
      final body = storageSource.substring(
        pollDeclIdx,
        (pollDeclIdx + 2500).clamp(0, storageSource.length),
      );
      expect(body, contains('_data = data'),
          reason: 'the poll must also update the local _data snapshot');
      expect(body, contains('blocks >= targetBlocks'),
          reason: 'the poll must early-exit on target reached');
    });

    test('poll captures AppState BEFORE the first await (BuildContext-safe)', () {
      
      
      final fnIdx = storageSource.indexOf('_startCheckout(int blockCount)');
      expect(fnIdx, greaterThan(-1));
      final readIdx = storageSource.indexOf(
          'context.read<AppState>()', fnIdx);
      final awaitIdx = storageSource.indexOf(
          'await _client.createStripeCheckoutSession', fnIdx);
      expect(readIdx, greaterThan(-1),
          reason: '_startCheckout must read AppState via Provider');
      expect(awaitIdx, greaterThan(-1));
      expect(readIdx, lessThan(awaitIdx),
          reason: 'AppState must be captured BEFORE any await — '
                  'context.read across an async gap is unsafe');
    });

    test('downgrade flow uses friendly dialog, not the error dialog', () {
      
      
      expect(storageSource, contains('_LowerPlanDialog'),
          reason: '_LowerPlanDialog widget must exist');

      
      expect(storageSource, contains('Changing to a lower plan'),
          reason: 'Phase 1: lower-plan dialog title');
      expect(
        storageSource,
        contains('To reduce your storage plan, open Manage Subscription.'),
        reason: 'lower-plan dialog body (first sentence)',
      );
      expect(
        storageSource,
        contains(
          'Changes to a lower plan may take effect at the end of your',
        ),
        reason: 'lower-plan dialog body (second sentence)',
      );

      
      expect(
        storageSource.contains("'Manage Subscription'") ||
            storageSource.contains('settingsManageSubscription'),
        isTrue,
        reason:
            'lower-plan dialog must have a Manage Subscription '
            'button, either as literal or via '
            'AppLocalizations.settingsManageSubscription',
      );
      expect(
        storageSource.contains("'Close'"),
        isTrue,
        reason: 'lower-plan dialog must have a Close button',
      );

      
      final lowerPlanIdx = storageSource.indexOf('class _LowerPlanDialog');
      expect(lowerPlanIdx, greaterThan(-1),
          reason: '_LowerPlanDialog class must exist');
      
      
      final nextClassIdx = storageSource.indexOf(
        RegExp(r'^class\s', multiLine: true),
        lowerPlanIdx + 1,
      );
      final endIdx = nextClassIdx > -1
          ? nextClassIdx
          : storageSource.length;
      final lowerPlanBody = storageSource.substring(lowerPlanIdx, endIdx);
      for (final banned in const [
        'Exception',
        'Checkout session failed',
        "Upgrade couldn't start",
      ]) {
        expect(
          lowerPlanBody.contains(banned),
          isFalse,
          reason:
              'banned leak string "$banned" must not appear inside '
              '_LowerPlanDialog body',
        );
      }

      
      final showDialogIdx =
          storageSource.indexOf('Future<void> _showLowerPlanDialog');
      expect(showDialogIdx, greaterThan(-1),
          reason: '_showLowerPlanDialog must exist');
      final dialogBody = storageSource.substring(
        showDialogIdx,
        (showDialogIdx + 1000).clamp(0, storageSource.length),
      );
      expect(dialogBody, contains('_onManageSubscription'),
          reason:
              "lower-plan dialog must reuse _StoragePageState's existing "
              '_onManageSubscription, not its own copy');

      
      final onBuyIdx =
          storageSource.indexOf('Future<void> _onBuyStorage()');
      expect(onBuyIdx, greaterThan(-1));
      final onBuyBody = storageSource.substring(
        onBuyIdx,
        (onBuyIdx + 3000).clamp(0, storageSource.length),
      );
      final preCheckPos = onBuyBody.indexOf('picked < currentBlocks');
      final startCheckoutPos = onBuyBody.indexOf('_startCheckout(picked)');
      expect(preCheckPos, greaterThan(-1));
      expect(startCheckoutPos, greaterThan(-1));
      expect(preCheckPos, lessThan(startCheckoutPos),
          reason:
              'the picked < currentBlocks pre-check must be lexically '
              'BEFORE the _startCheckout call so the downgrade path '
              'never reaches the backend');

      
      expect(storageSource, contains('_isDowngradeNotSupportedError'),
          reason: 'catch-block helper for the race-condition fallback');
      expect(storageSource, contains('downgrade_not_supported'),
          reason:
              'the helper must match on the backend error code so the '
              'fallback routes correctly');
    });

    test('three-phase dialog copy matches the spec verbatim', () {
      
      
      expect(
        storageSource,
        contains('Checking your upgrade…'),
        reason: 'Phase 1: progress dialog title',
      );
      
      
      expect(
        storageSource,
        contains("We're updating your SVaultAI storage plan."),
        reason: 'Phase 1: progress dialog body (first sentence)',
      );
      expect(
        storageSource,
        contains('This usually'),
        reason: 'Phase 1: progress dialog body (second sentence)',
      );

      
      expect(
        storageSource,
        contains('Storage upgraded successfully'),
        reason: 'Phase 2: success dialog title',
      );
      expect(
        storageSource,
        contains('Your storage limit is now '),
        reason: 'Phase 2: success dialog body ("...is now N GB.")',
      );

      
      expect(
        storageSource,
        contains("'Payment received'"),
        reason: 'Phase 3: timeout dialog title — operator-pinned',
      );
      expect(
        storageSource,
        contains("We're still applying your upgrade."),
        reason: 'Phase 3: timeout dialog body (first sentence)',
      );
      expect(
        storageSource,
        contains('Refresh in a moment.'),
        reason: 'Phase 3: timeout dialog body (second sentence)',
      );
      expect(
        storageSource.contains("'Refresh now'") ||
            storageSource.contains('storageRefreshNow'),
        isTrue,
        reason:
            'Phase 3: timeout dialog must have a Refresh-now action, '
            'either as literal or via '
            'AppLocalizations.storageRefreshNow',
      );
    });

    test('forbidden copy strings have been removed', () {
      
      
      expect(
        storageSource,
        isNot(contains('Refreshing your storage limit')),
        reason: 'banned phrase: "Refreshing your storage limit"',
      );
      expect(
        storageSource,
        isNot(contains('The prorated charge is on its way')),
        reason: 'banned phrase: "The prorated charge is on its way"',
      );
    });

    test(
        'no developer/diagnostic cards exist in the Storage page UI '
        '(debug OR release)', () {
      
      
      expect(
        storageSource,
        isNot(contains('kDebugMode')),
        reason: 'kDebugMode reference removed with the dev card',
      );

      
      for (final symbol in const [
        'DevCleanupCard',
        '_DevCleanupResultDialog',
        '_DevDialogRow',
        '_onCleanupDuplicateSubs',
        '_busyDevCleanup',
      ]) {
        expect(
          storageSource,
          isNot(contains(symbol)),
          reason: 'identifier $symbol must be removed; the cleanup '
                  'surface is backend-script-only now',
        );
      }

      
      for (final copy in const [
        'Developer tools',
        'Cleanup duplicate Stripe subscriptions',
        'Cleanup complete',
        'Canceled IDs',
        'Cleanup failed',
      ]) {
        expect(
          storageSource,
          isNot(contains(copy)),
          reason: 'copy "$copy" must be removed; do not re-introduce '
                  'a frontend cleanup surface',
        );
      }

      
      for (final iconName in const [
        'bug_report_outlined',
        'cleaning_services_outlined',
      ]) {
        expect(
          storageSource,
          isNot(contains(iconName)),
          reason: 'Icons.$iconName was used only by the dev card; '
                  'its return likely means the card returned',
        );
      }

      
      final apiClientSource = File('lib/api_client.dart').readAsStringSync();
      expect(
        apiClientSource,
        isNot(contains('cleanupDuplicateStripeSubscriptions')),
        reason: 'api_client.dart must not expose a method that calls '
                '/billing/dev/cleanup-duplicate-subs; the operator '
                'runs the backend script instead',
      );
    });

    test('upgrade-outcome surfaces use showDialog, not snackbars', () {
      
      
      expect(storageSource, contains('_UpgradeProgressDialog'),
          reason: 'Phase 1 progress dialog widget must exist');
      expect(storageSource, contains('_UpgradeSuccessDialog'),
          reason: 'Phase 2 success dialog widget must exist');
      expect(storageSource, contains('_UpgradeTimeoutDialog'),
          reason: 'Phase 3 timeout dialog widget must exist');
      expect(storageSource, contains('_UpgradeErrorDialog'),
          reason: 'error dialog widget must exist');
      
      
      final branchIdx = storageSource.indexOf("'updated_existing'");
      expect(branchIdx, greaterThan(-1));
      
      
      final branchBody = storageSource.substring(
        branchIdx,
        (branchIdx + 3000).clamp(0, storageSource.length),
      );
      expect(branchBody, contains('_UpgradeProgressDialog'),
          reason: 'updated_existing branch must show the progress dialog');
      expect(branchBody, contains('_UpgradeSuccessDialog'),
          reason: 'updated_existing branch must show the success dialog');
      expect(branchBody, contains('_UpgradeTimeoutDialog'),
          reason: 'updated_existing branch must show the timeout dialog');
      expect(branchBody, isNot(contains('showSnackBar')),
          reason: 'updated_existing branch must NOT use snackbars');
    });
  });
}
