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

  final defaultLimit =
      (blocks > 0 && purchased > 0) ? purchased : (includedBytes + grant);
  final limit = effectiveLimitBytes ?? defaultLimit;
  final used = usedBytes ?? 0;
  final pct = percentUsed ?? (limit > 0 ? (used / limit) * 100.0 : 0.0);

  const liveStatuses = {'active', 'in_grace', 'canceled_pending'};
  final defaultHasSub = const {'apple', 'google_play'}.contains(source) &&
      liveStatuses.contains(status);
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

    test('isOnFreeTierOnly is true only with zero blocks AND zero grant', () {
      expect(isOnFreeTierOnly(_entitlement()), isTrue);
      expect(isOnFreeTierOnly(_entitlement(blockCount: 1)), isFalse);
      expect(isOnFreeTierOnly(_entitlement(storageBytesGrant: 1)), isFalse);
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
          find.text('Your vault is nearing its storage limit.'), findsNothing);
      expect(
          find.text('Storage limit reached. Upgrade storage to continue '
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
          find.text('Your vault is nearing its storage limit.'), findsNothing);
      expect(
          find.text('Storage limit reached. Upgrade storage to continue '
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

      expect(find.text('Your vault is nearing its storage limit.'),
          findsOneWidget);

      expect(
          find.text('Storage limit reached. Upgrade storage to continue '
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
      expect(find.text('Your vault is nearing its storage limit.'),
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
          find.text('Storage limit reached. Upgrade storage to continue '
              'uploading files.'),
          findsOneWidget);

      expect(
          find.text('Your vault is nearing its storage limit.'), findsNothing);
    });
  });

  group('scenario 5: over-quota grandfather user', () {
    testWidgets('renders the grandfathered note instead of the free-tier nudge',
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

      expect(find.text('Additional storage pricing'), findsOneWidget);
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

      expect(find.text('Your vault is nearing its storage limit.'),
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

    test('storage_page.dart has no "coming soon" / "next release" copy', () {
      final src = readLib('storage_page.dart');
      expect(src, isNot(contains('coming soon')));
      expect(src, isNot(contains('next release')));
      expect(src, isNot(contains('lands in the next')));
    });

    test('main.dart has no "Payment upgrade will be connected next"', () {
      final src = readLib('main.dart');
      expect(src, isNot(contains('Payment upgrade will be connected next')));

      expect(
        src.toLowerCase(),
        isNot(contains('payment upgrade will be connected')),
      );
    });

    test('main.dart dashboard upgrade card uses the production copy', () {
      final src = readLib('main.dart');
      expect(src, contains("'Buy More Storage'"),
          reason: 'dashboard card title must read Buy More Storage');

      expect(src, contains('Add storage in 50 GB blocks.'),
          reason: 'dashboard card body opener regressed');
      expect(src, contains('limit updates automatically'),
          reason: 'dashboard card body middle clause regressed');
      expect(src, contains('after '),
          reason: 'dashboard card body trailing clause regressed');
      expect(
        src.contains("'Choose Storage'") || src.contains('filesChooseStorage'),
        isTrue,
        reason: 'dashboard card must expose a Choose Storage button '
            '(literal or via AppLocalizations.filesChooseStorage)',
      );

      expect(src, isNot(contains("'Upgrade Vault Storage'")),
          reason: 'legacy Upgrade Vault Storage card not removed');
      expect(src, isNot(contains('Upgrade for \$25')),
          reason: 'legacy Upgrade for 25 dollar button not removed');
      expect(src, isNot(contains(r'$25 upgrade')),
          reason: 'legacy 25 dollar upgrade string not removed');
    });

    test(
        'main.dart dashboard upgrade card routes to /storage with '
        'autoOpenPicker:true', () {
      final src = readLib('main.dart');
      final idx = src.indexOf("'Buy More Storage'");
      expect(idx, greaterThan(-1),
          reason: 'Buy More Storage label missing from main.dart');
      final start = (idx - 200).clamp(0, src.length);
      final end = (idx + 2500).clamp(0, src.length);
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
        contains("'autoOpenPicker': true"),
        reason: 'dashboard card must pass autoOpenPicker:true so the '
            'Storage page opens the SKU picker on entry — no '
            'placeholder snackbar.',
      );
    });
  });

  group('storage_page auto-open picker plumbing', () {
    String readLib(String relative) {
      final file = File('lib/$relative');
      expect(file.existsSync(), isTrue,
          reason: 'expected file does not exist: ${file.path}');
      return file.readAsStringSync();
    }

    test('storage_page.dart reads autoOpenPicker route argument', () {
      final src = readLib('storage_page.dart');
      expect(
        src,
        contains("ModalRoute.of(context)?.settings.arguments"),
        reason: 'storage page must read its route arguments',
      );
      expect(
        src,
        contains("'autoOpenPicker'"),
        reason: 'storage page must look for the autoOpenPicker arg',
      );
    });

    test('storage_page.dart auto-open path calls _onBuyStorage', () {
      final src = readLib('storage_page.dart');
      final idx = src.indexOf('void _maybeAutoOpenPicker()');
      expect(idx, greaterThan(-1),
          reason: 'auto-open helper definition missing from '
              'storage_page.dart');
      final start = idx;
      final end = (idx + 1200).clamp(0, src.length);
      final window = src.substring(start, end);
      expect(
        window,
        contains('_onBuyStorage'),
        reason: 'auto-open helper must invoke _onBuyStorage so the picker '
            'opens via the same path as the button click.',
      );
    });
  });

  group('P1 buttons: Buy / Manage', () {
    testWidgets('mobile/no-checkout configuration renders no purchase button',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StorageBody(data: _entitlement())));

      expect(find.text('Buy storage'), findsNothing);
      expect(find.text('Upgrade storage'), findsNothing);
      expect(find.text('Manage Subscription'), findsNothing);
    });

    testWidgets('free tier renders Buy but NOT Manage', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));

      expect(find.text('Buy storage'), findsOneWidget);
      expect(find.text('Manage Subscription'), findsNothing);
    });

    testWidgets('active Apple subscriber renders both buttons', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        blockCount: 2,
        status: 'active',
      );
      data['source'] = 'apple';
      data['has_active_subscription'] = true;
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));

      expect(find.text('Upgrade storage'), findsOneWidget);
      expect(find.text('Manage Subscription'), findsOneWidget);
    });

    testWidgets('Apple in_grace still shows Manage (user can fix payment)',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        blockCount: 1,
        status: 'in_grace',
      );
      data['source'] = 'apple';
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Manage Subscription'), findsOneWidget);
    });

    testWidgets('Manage button hidden when callbacks are null', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(blockCount: 1, status: 'active');
      data['source'] = 'apple';
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
      )));

      expect(find.text('Manage Subscription'), findsNothing);
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

      expect(find.text('Monthly cost  ·  \$14.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$19.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$24.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$29.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$34.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$49.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$79.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$129.99/month'), findsOneWidget);
      expect(find.text('Monthly cost  ·  \$199.99/month'), findsOneWidget);
    });

    testWidgets('current block count is marked as "Current"', (tester) async {
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

      expect(find.text('Monthly cost  ·  \$49.99/month'), findsNothing);
      expect(find.text('Monthly cost  ·  \$79.99/month'), findsNothing);
      expect(find.text('Monthly cost  ·  \$129.99/month'), findsNothing);
      expect(find.text('Monthly cost  ·  \$199.99/month'), findsNothing);

      expect(find.text('Monthly cost  ·  \$34.99/month'), findsOneWidget);
    });

    testWidgets(
        'new storage limit equals blocks * block_bytes (paid replaces free)',
        (tester) async {
      await _enlargeSurface(tester);
      await tester.pumpWidget(_wrap(StoragePlanPicker(
        currentBlockCount: 0,
        usedBytes: 0,
        blockBytes: 53687091200,
        blockPriceCentsUsd: 2500,
        selfServiceMaxBlocks: 100,
      )));

      expect(find.text('New storage limit  ·  50 GB'), findsOneWidget);
      expect(find.text('New storage limit  ·  100 GB'), findsOneWidget);
      expect(find.text('New storage limit  ·  150 GB'), findsOneWidget);

      expect(find.textContaining('51 GB'), findsNothing);
      expect(find.textContaining('101 GB'), findsNothing);
      expect(find.textContaining('151 GB'), findsNothing);
    });

    testWidgets(
        'upgrade mode shows "Upgrade Storage" header, not "Buy More Storage"',
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
      expect(find.text('Upgrade Storage'), findsOneWidget);
      expect(find.text('Buy More Storage'), findsNothing);
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
      expect(find.text('Current: 150 GB / \$24.99/month'), findsOneWidget);
    });

    testWidgets(
        'upgrade tile shows "New plan", "Added today", and proration note',
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
        find.text('New plan  ·  200 GB / \$29.99/month'),
        findsOneWidget,
      );
      expect(
        find.text('Added today  ·  +50 GB / +\$5.00/month'),
        findsOneWidget,
      );

      expect(
        find.text('Your app store will confirm today\'s charge'),
        findsWidgets,
      );

      expect(
        find.text('Added today  ·  +100 GB / +\$10.00/month'),
        findsOneWidget,
      );
    });

    testWidgets(
        'upgrade mode does NOT show "Added today" on the current tier or '
        'tiers below current (only above)', (tester) async {
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
      expect(find.textContaining('Added today  ·  +-'), findsNothing);
    });

    testWidgets(
        'upgrade mode preserves "Monthly cost" lines (not used in upgrade tiles)',
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
        find.text('Monthly cost  ·  \$29.99/month'),
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
    testWidgets('renders "Organization" as the account type', (tester) async {
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

      expect(find.text('Self-service maximum'), findsOneWidget);

      expect(find.text('Grandfathered storage'), findsOneWidget);
    });
  });

  group('cross-cutting structure', () {
    testWidgets('all scenarios render the Storage Usage title', (tester) async {
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

    testWidgets('self-service maximum row renders as 5 TB', (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(data: data)));

      expect(find.text('5 TB'), findsOneWidget);
    });

    testWidgets('pricing examples list shows the four locked tiers',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement();
      await tester.pumpWidget(_wrap(StorageBody(data: data)));
      expect(find.text('50 GB'), findsOneWidget);
      expect(find.text('100 GB'), findsOneWidget);
      expect(find.text('150 GB'), findsOneWidget);
      expect(find.text('500 GB'), findsOneWidget);
      expect(find.text(r'$14.99/month'), findsOneWidget);
      expect(find.text(r'$19.99/month'), findsOneWidget);
      expect(find.text(r'$24.99/month'), findsOneWidget);
      expect(find.text(r'$49.99/month'), findsOneWidget);
    });
  });

  group('verified store subscription predicates', () {
    test('Apple and Google Play honor the verified active flag', () {
      for (final source in ['apple', 'google_play']) {
        expect(
            hasActiveSubscription(_entitlement(
              source: source,
              status: 'active',
              hasActiveSubscription: true,
            )),
            isTrue);
        expect(
            hasActiveSubscription(_entitlement(
              source: source,
              status: 'expired',
              hasActiveSubscription: false,
            )),
            isFalse);
      }
    });

    test('free and retired card providers cannot enable paid controls', () {
      for (final source in ['none', 'stripe', 'web_card']) {
        final data = _entitlement(
          source: source,
          status: 'active',
          hasActiveSubscription: true,
        );
        expect(hasActiveSubscription(data), isFalse);
        expect(hasManageableSubscription(data), isFalse);
      }
    });

    test('store status fallback supports active, grace and cancellation', () {
      for (final source in ['apple', 'google_play']) {
        for (final status in ['active', 'in_grace', 'canceled_pending']) {
          expect(hasActiveSubscription({'source': source, 'status': status}),
              isTrue);
        }
        expect(hasActiveSubscription({'source': source, 'status': 'expired'}),
            isFalse);
        expect(
            hasManageableSubscription({'source': source, 'status': 'expired'}),
            isTrue);
      }
    });
  });

  group('StorageBody purchase action button', () {
    testWidgets('shows "Buy storage" when user has NO active subscription',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        source: 'none',
        status: 'none',
        blockCount: 0,
      );
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Buy storage'), findsOneWidget);
      expect(find.text('Upgrade storage'), findsNothing);
    });

    testWidgets(
      'shows "Upgrade storage" when user has an active Apple subscription',
      (tester) async {
        await _enlargeSurface(tester);
        final data = _entitlement(
          source: 'apple',
          status: 'active',
          blockCount: 2,
        );
        await tester.pumpWidget(_wrap(StorageBody(
          data: data,
          onBuyStorage: () {},
          onManageSubscription: () {},
        )));
        expect(find.text('Upgrade storage'), findsOneWidget);
        expect(find.text('Buy storage'), findsNothing);
      },
    );

    testWidgets('expired Apple sub flips label back to "Buy storage"',
        (tester) async {
      await _enlargeSurface(tester);
      final data = _entitlement(
        source: 'apple',
        status: 'expired',
        blockCount: 1,
      );
      await tester.pumpWidget(_wrap(StorageBody(
        data: data,
        onBuyStorage: () {},
        onManageSubscription: () {},
      )));
      expect(find.text('Buy storage'), findsOneWidget);
      expect(find.text('Upgrade storage'), findsNothing);
    });
  });
}
