import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_scanner_card.dart';


Widget _wrap(Widget child, {Size size = const Size(1200, 2400)}) {
  return MaterialApp(
    home: Scaffold(
      body: SizedBox(
        width: size.width,
        height: size.height,
        child: SingleChildScrollView(child: child),
      ),
    ),
  );
}


CryptoWalletFeatures _features({
  bool xmrOn = true,
  bool clientScannerSupported = false,
}) {
  return CryptoWalletFeatures.fromBackend(<String, dynamic>{
    'walletEngineEnabled':      true,
    'mainnetReceiveEnabled':    true,
    'mainnetErc20ReceiveEnabled': true,
    'xmrEnabled':               xmrOn,
    'xmrReceiveEnabled':        xmrOn,
    'xmrBalanceEnabled':        false,
    'xmrSendEnabled':           false,
    'xmrClientScannerSupported': clientScannerSupported,
  });
}


void main() {


  group('Monero scanner card — no duplicated unavailable copy', () {

    testWidgets(
        'default disabled state shows exactly ONE "Scanner not '
        'enabled" — the state line — and no duplicated long copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();


      expect(find.text('Scanner not enabled'), findsOneWidget);


      expect(
        find.text('Monero scanning is not available in this build yet.'),
        findsNothing,
      );
    });

    testWidgets('default disabled state has "Monero scanner" as header',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Monero scanner'), findsOneWidget);
    });
  });


  group('Sync instructions are only shown during scanner_syncing', () {

    testWidgets(
        'disabled state does NOT show "Scanning happens on this '
        'device."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Scanning happens on this device.'),
        findsNothing,
      );
    });

    testWidgets(
        'disabled state does NOT show "Do not close the app while '
        'scanning."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Do not close the app while scanning.'),
        findsNothing,
      );
    });

    testWidgets(
        'disabled state does NOT show "Sync can take time depending '
        'on restore height."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Sync can take time depending on restore height.'),
        findsNothing,
      );
    });

    testWidgets(
        'not-started state does NOT show "Do not close the app '
        'while scanning."',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        initialStatus:
            MoneroSyncStatus.notStarted(restoreHeight: 3220000),
      );
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Do not close the app while scanning.'),
        findsNothing,
        reason: 'sync instructions must NOT be shown when the '
            'scanner is not actively syncing',
      );
      expect(
        find.text('Sync can take time depending on restore height.'),
        findsNothing,
      );
    });

    testWidgets(
        'syncing state DOES show "Do not close the app while '
        'scanning." and "Sync can take time depending on restore '
        'height."',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      const syncingStatus = MoneroSyncStatus(
        state: MoneroScannerState.syncing,
        restoreHeight: 3220000,
        currentHeight: 3220100,
        targetHeight: 3220200,
        percent: 0.5,
      );
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: syncingStatus,
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Do not close the app while scanning.'),
        findsOneWidget,
      );
      expect(
        find.text('Sync can take time depending on restore height.'),
        findsOneWidget,
      );
    });
  });


  group('Privacy note — closed-set safe copy', () {

    testWidgets(
        'privacy note explicitly disavows sending seed/spend/view keys',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text(
          'Svaultai does not send your seed, spend key, or view key '
          'to a scanner.',
        ),
        findsOneWidget,
      );
    });
  });


  group('Monero balance card — compact closed-set copy', () {

    testWidgets(
        'disabled/unavailable state says "Scanner not enabled" — '
        'not the long "Scanning is not enabled yet." sentence',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(xmrOn: true),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Scanner not enabled'), findsOneWidget);
      expect(
        find.text(
          'Monero balance requires wallet scanning. Scanning is not '
          'enabled yet.',
        ),
        findsNothing,
      );
    });

    testWidgets('never renders a fake "0 XMR" in disabled state',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(xmrOn: true),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('0 XMR'),   findsNothing);
      expect(find.text('0.0 XMR'), findsNothing);
      expect(find.textContaining('0.00 XMR'), findsNothing);
    });

    testWidgets(
        'scanner_ready + real zero → renders 0 XMR — this is the '
        'only allowed way to render a zero',
        (tester) async {
      const syncedStatus = MoneroSyncStatus(
        state: MoneroScannerState.synced,
        restoreHeight: 3220000,
      );
      final realZero = MoneroBalanceReading.ready(
        total: '0.0', unlocked: '0.0', locked: '0.0',
      );
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(xmrOn: true),
          scannerStatus: syncedStatus,
          balance: realZero,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('0.0 XMR'), findsWidgets,
          reason: 'real zero from a synced scanner is honest');
    });
  });


  group('Monero activity card — closed-set gated copy', () {

    testWidgets(
        'disabled/unavailable state says exactly "Monero activity '
        'requires wallet scanning." — no trailing "Scanning is not '
        'enabled yet."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(xmrOn: true),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Monero activity requires wallet scanning.'),
        findsOneWidget,
      );
      expect(
        find.text(
          'Monero activity requires wallet scanning. Scanning is not '
          'enabled yet.',
        ),
        findsNothing,
      );
    });

    testWidgets('empty after sync → "No activity yet."', (tester) async {
      const syncedStatus = MoneroSyncStatus(
        state: MoneroScannerState.synced,
        restoreHeight: 3220000,
      );
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(xmrOn: true),
          scannerStatus: syncedStatus,
          transactions: const [],
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('No activity yet.'), findsOneWidget);
    });
  });


  group('Copy constants — closed-set values', () {

    test('balance disabled/not-enabled copies are the compact "Scanner '
        'not enabled"', () {
      expect(kMoneroBalanceScannerNotEnabledCopy, 'Scanner not enabled');
      expect(kMoneroBalanceDisabledCopy,          'Scanner not enabled');
    });

    test('balance syncing copy is "Scanner syncing"', () {
      expect(kMoneroBalanceSyncingCopy, 'Scanner syncing');
    });

    test('activity disabled/not-enabled copies are the compact '
        '"Monero activity requires wallet scanning."', () {
      expect(kMoneroActivityScannerNotEnabledCopy,
          'Monero activity requires wallet scanning.');
      expect(kMoneroActivityDisabledCopy,
          'Monero activity requires wallet scanning.');
    });

    test('activity syncing copy is "Monero scanner is syncing."', () {
      expect(kMoneroActivitySyncingCopy, 'Monero scanner is syncing.');
    });

    test('activity empty-after-sync copy is "No activity yet."', () {
      expect(kMoneroActivityEmptyAfterSyncCopy, 'No activity yet.');
    });

    test('scanner heading is "Monero scanner", not "Monero scanning"',
        () {
      expect(kMoneroScannerHeading, 'Monero scanner');
    });

    test('scanner unavailable copy is "Scanner not enabled"', () {
      expect(kMoneroScannerUnavailableCopy, 'Scanner not enabled');
    });

    test('scanner privacy note explicitly disavows sending seed/'
        'spend/view keys', () {
      expect(
        kMoneroScannerDaemonPrivacyNote,
        'Svaultai does not send your seed, spend key, or view key '
        'to a scanner.',
      );
    });
  });


  group('Copy is safe — no marketing / no fake balance / no fake '
      'activity language', () {

    test('every polished copy string is free of exchange language',
        () {
      const banned = <String>[
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
        ' bridge ', ' exchange ', ' convert ',
      ];
      final strings = <String>[
        kMoneroScannerHeading,
        kMoneroScannerUnavailableCopy,
        kMoneroScannerNotStartedCopy,
        kMoneroScannerSyncingCopy,
        kMoneroScannerSyncedCopy,
        kMoneroScannerFailedCopy,
        kMoneroScannerStoppedCopy,
        kMoneroScannerRequiresWalletCopy,
        kMoneroScannerRunsOnDeviceCopy,
        kMoneroScannerDoNotCloseAppCopy,
        kMoneroScannerSyncTimeCopy,
        kMoneroScannerDaemonPrivacyNote,
        kMoneroBalanceScannerNotEnabledCopy,
        kMoneroBalanceScannerNotStartedCopy,
        kMoneroBalanceSyncingCopy,
        kMoneroBalanceDisabledCopy,
        kMoneroActivityScannerNotEnabledCopy,
        kMoneroActivityScannerNotStartedCopy,
        kMoneroActivitySyncingCopy,
        kMoneroActivityDisabledCopy,
        kMoneroActivityEmptyAfterSyncCopy,
      ];
      for (final s in strings) {
        final padded = ' ${s.toLowerCase()} ';
        for (final b in banned) {
          expect(padded.contains(b), isFalse,
              reason: 'copy "$s" leaks "$b"');
        }
      }
    });

    test('no copy string contains "Monero scanning is not available '
        'in this build yet." — the obsolete duplicate sentence', () {
      const banned = 'Monero scanning is not available in this build yet.';
      for (final s in <String>[
        kMoneroScannerHeading,
        kMoneroScannerUnavailableCopy,
        kMoneroScannerNotStartedCopy,
        kMoneroScannerSyncingCopy,
        kMoneroScannerFailedCopy,
        kMoneroScannerStoppedCopy,
        kMoneroBalanceScannerNotEnabledCopy,
        kMoneroActivityScannerNotEnabledCopy,
      ]) {
        expect(s, isNot(equals(banned)));
      }
    });
  });


  group('Mobile — no overflow at 400 px width', () {

    testWidgets('scanner card renders at 400x900 without overflow',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'balance + activity cards render at 400x900 without overflow',
        (tester) async {
      await tester.pumpWidget(_wrap(
        Column(
          children: [
            CryptoWalletEngineMoneroBalanceCard(
              features: _features(xmrOn: true),
            ),
            const SizedBox(height: 12),
            CryptoWalletEngineMoneroActivityCard(
              features: _features(xmrOn: true),
            ),
          ],
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });
}
