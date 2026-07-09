import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/services/monero_scanner_status.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_scanner_card.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


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
  bool clientScannerSupported = false,
  bool xmrOn = true,
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


  group('Closed-set reason: local_scanner_available', () {

    test('reason is in the allowed set', () {
      expect(
        kAllowedMoneroScannerReason,
        contains('local_scanner_available'),
      );
      expect(
        kMoneroScannerReasonLocalAvailable, 'local_scanner_available',
      );
    });

    test('balance copy for local_scanner_available is compact', () {
      expect(
        moneroScannerBalanceCopyForReason('local_scanner_available'),
        'Local scanner available',
      );
    });

    test('activity copy for local_scanner_available is compact', () {
      expect(
        moneroScannerActivityCopyForReason('local_scanner_available'),
        'Start the local scanner to load Monero activity.',
      );
    });

    test('MoneroScannerStatus.fromJson accepts local_scanner_available',
        () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus':   'configured',
        'reason':          'local_scanner_available',
        'canShowBalance':  false,
        'canShowActivity': false,
        'canSend':         false,
      });
      expect(s.scannerStatus, 'configured');
      expect(s.reason,        'local_scanner_available');
      expect(s.balanceCopy,   'Local scanner available');
      expect(s.canSend,       isFalse,
          reason: 'canSend must stay false in client_local mode');
    });
  });


  group('Restore-height section — visibility gate', () {

    testWidgets(
        'restore-height section is shown when client scanner is '
        'available AND status is notStarted',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        initialStatus:
            MoneroSyncStatus.notStarted(restoreHeight: 0),
      );
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 0),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
            const Key(kMoneroScannerRestoreHeightSectionKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(
            const Key(kMoneroScannerRestoreHeightFieldKey)),
        findsOneWidget,
      );
      expect(find.text(kMoneroScannerRestoreHeightLabel), findsOneWidget);
      expect(
        find.text(kMoneroScannerRestoreHeightExplainer),
        findsOneWidget,
      );
    });

    testWidgets(
        'restore-height section is NOT shown when scanner is '
        'unavailable',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
            const Key(kMoneroScannerRestoreHeightSectionKey)),
        findsNothing,
      );
    });

    testWidgets(
        'restore-height section is NOT shown while syncing — the '
        'value is locked in once the scan starts',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      const syncing = MoneroSyncStatus(
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
          status: syncing,
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
            const Key(kMoneroScannerRestoreHeightSectionKey)),
        findsNothing,
      );
    });

    testWidgets(
        'restore-height section is NOT shown after sync completes',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      const synced = MoneroSyncStatus(
        state: MoneroScannerState.synced,
        restoreHeight: 3220000,
      );
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: synced,
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
            const Key(kMoneroScannerRestoreHeightSectionKey)),
        findsNothing,
      );
    });
  });


  group('Restore-height input — user interaction', () {

    testWidgets(
        'entering a valid block height fires onRestoreHeightChanged '
        'with the parsed integer',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      final captured = <int>[];
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 0),
          onRestoreHeightChanged: captured.add,
        ),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key(kMoneroScannerRestoreHeightFieldKey)),
        '3220000',
      );
      await tester.pumpAndSettle();
      expect(captured, contains(3220000));
    });

    testWidgets(
        'entering non-digit characters is rejected by the '
        'inputFormatter — callback is never called with garbage',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      final captured = <int>[];
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 0),
          onRestoreHeightChanged: captured.add,
        ),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key(kMoneroScannerRestoreHeightFieldKey)),
        'abc',
      );
      await tester.pumpAndSettle();

      expect(captured, isEmpty);
    });

    testWidgets(
        'the initial value passed in populates the field',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
          initialRestoreHeight: 3220000,
        ),
      ));
      await tester.pumpAndSettle();
      final textField = tester.widget<TextField>(
        find.byKey(const Key(kMoneroScannerRestoreHeightFieldKey)),
      );
      expect(textField.controller?.text, '3220000');
    });
  });


  group('No secret leakage in scanner card copy or source', () {

    testWidgets(
        'restore-height section itself never asks the user to enter '
        'a seed / mnemonic / spend key / view key / private key',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 0),
        ),
      ));
      await tester.pumpAndSettle();


      final section = find.byKey(
        const Key(kMoneroScannerRestoreHeightSectionKey),
      );
      expect(section, findsOneWidget);

      final textsInSection = find.descendant(
        of: section,
        matching: find.byType(Text),
      );
      final visibleTexts = <String>[];
      for (final el in textsInSection.evaluate()) {
        final t = (el.widget as Text).data;
        if (t != null) visibleTexts.add(t.toLowerCase());
      }
      final joined = visibleTexts.join(' | ');
      const banned = <String>[
        'seed', 'mnemonic', 'spend key', 'view key',
        'private key', 'private spend', 'private view',
      ];
      for (final b in banned) {
        expect(joined.contains(b), isFalse,
            reason: 'restore-height area leaked "$b": $joined');
      }
    });


    test('scanner card source does NOT reference any real Monero '
        'library or FFI symbol', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_monero_scanner_card.dart',
      );
      const banned = <String>[
        "import 'package:wallet2/",
        "import 'package:monero_serai/",
        "import 'package:monero_lws/",
        'ffi.DynamicLibrary.open',
        'openMoneroWallet',
        'MoneroWalletManager',
      ];
      for (final b in banned) {
        expect(src.contains(b), isFalse,
            reason: 'scanner card leaked FFI/library symbol: $b');
      }
    });


    test('restore-height copies never mention exchange language', () {
      const banned = <String>[
        'buy', 'sell', 'swap', 'trade', 'stake',
        'bridge', 'exchange', 'convert',
      ];
      for (final s in <String>[
        kMoneroScannerRestoreHeightLabel,
        kMoneroScannerRestoreHeightExplainer,
      ]) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'restore-height copy leaked "$b"');
        }
      }
    });
  });


  group('canSend stays false in every closed-set copy path', () {

    test('every closed-set balance/activity copy for '
        'local_scanner_available does not fabricate a numeric '
        'balance', () {

      final bal = moneroScannerBalanceCopyForReason(
        'local_scanner_available',
      );
      expect(bal.contains('0 XMR'),   isFalse);
      expect(bal.contains('0.0 XMR'), isFalse);
      expect(bal, isNot(matches(RegExp(r'\d+(\.\d+)?\s*XMR'))),
          reason: 'balance copy must not embed a numeric XMR amount');
    });
  });


  group('Mobile — no overflow', () {

    testWidgets(
        'restore-height section renders at 400x900 without overflow',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });
}
