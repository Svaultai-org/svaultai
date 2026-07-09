import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/services/monero_scanner_status.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_activity_card.dart';
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


CryptoWalletFeatures _features({bool xmrOn = true}) {
  return CryptoWalletFeatures.fromBackend(<String, dynamic>{
    'walletEngineEnabled':      true,
    'mainnetReceiveEnabled':    true,
    'mainnetErc20ReceiveEnabled': true,
    'xmrEnabled':               xmrOn,
    'xmrReceiveEnabled':        xmrOn,
    'xmrSendEnabled':           false,
  });
}


MoneroScannerStatus _statusReason(String reason,
    {String mode = 'client_local'}) {
  return MoneroScannerStatus(
    scannerStatus:   'configured',
    reason:          reason,
    canShowBalance:  false,
    canShowActivity: false,
    canSend:         false,
    mode:            mode,
  );
}


void main() {


  group('Scanner card overrides state line when backendStatus.reason '
      'is a closed-set non-default', () {

    testWidgets(
        'scanner_requires_desktop → primary line says "Monero '
        'scanning requires the desktop app."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
          backendStatus: _statusReason('scanner_requires_desktop'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Monero scanning requires the desktop app.'),
        findsAtLeastNWidgets(1),
      );

      expect(find.text('Scanner not enabled'), findsNothing);
    });


    testWidgets(
        'no backendStatus → falls back to client-side state line '
        '("Scanner not enabled")',
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
        find.text('Monero scanning requires the desktop app.'),
        findsNothing,
      );
    });


    testWidgets(
        'scanner_not_enabled backendStatus → keeps client-side line '
        '(no override needed for the default disabled state)',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
          backendStatus: _statusReason('scanner_not_enabled',
              mode: 'none'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Scanner not enabled'), findsOneWidget);
    });


    testWidgets('local_scanner_available → "Local scanner available"',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      addTearDown(adapter.dispose);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(),
          status: MoneroSyncStatus.notStarted(restoreHeight: 0),
          backendStatus: _statusReason('local_scanner_available'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Local scanner available'),
          findsAtLeastNWidgets(1));
    });
  });


  group('Balance card renders backendStatus reason when it is a '
      'closed-set non-default state', () {

    testWidgets(
        'scanner_requires_desktop → balance card says "Monero '
        'scanning requires the desktop app."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          backendStatus: _statusReason('scanner_requires_desktop'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Monero scanning requires the desktop app.'),
        findsOneWidget,
      );

      expect(find.text('0 XMR'),   findsNothing);
      expect(find.text('0.0 XMR'), findsNothing);
    });


    testWidgets(
        'scanner_not_enabled backendStatus → falls through to the '
        'existing "Scanner not enabled" copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          backendStatus:
              _statusReason('scanner_not_enabled', mode: 'none'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Scanner not enabled'), findsOneWidget);
    });


    testWidgets(
        'no backendStatus and no scanner state → default "Scanner '
        'not enabled"',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Scanner not enabled'), findsOneWidget);
    });
  });


  group('Activity card renders backendStatus reason', () {

    testWidgets(
        'scanner_requires_desktop → activity card says "Monero '
        'scanning requires the desktop app."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          backendStatus: _statusReason('scanner_requires_desktop'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.text('Monero scanning requires the desktop app.'),
        findsOneWidget,
      );

      expect(find.text('IN'),  findsNothing);
      expect(find.text('OUT'), findsNothing);
    });


    testWidgets(
        'scanner_syncing → "Monero scanner is syncing." (backend '
        'override applies BEFORE the client-side syncing branch)',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          backendStatus: _statusReason('scanner_syncing'),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Monero scanner is syncing.'), findsOneWidget);
    });
  });


  group('No fake balance from any override path', () {

    testWidgets(
        'scanner_requires_desktop balance card does not render a '
        'numeric XMR amount anywhere',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          backendStatus: _statusReason('scanner_requires_desktop'),
        ),
      ));
      await tester.pumpAndSettle();
      final numericXmr = RegExp(r'\d+(\.\d+)?\s*XMR');
      for (final el in find.byType(Text).evaluate()) {
        final t = (el.widget as Text).data ?? '';
        expect(
          numericXmr.hasMatch(t), isFalse,
          reason: 'balance card leaked numeric XMR: $t',
        );
      }
    });
  });


  group('MoneroScannerStatus carries mode', () {

    test('fromJson picks mode from the payload and coerces junk to '
        '"none"', () {
      for (final entry in const [
        ['client_local',      'client_local'],
        ['server_view_only',  'server_view_only'],
        ['none',              'none'],
        ['garbage',           'none'],
      ]) {
        final json = <String, dynamic>{
          'scannerStatus': 'disabled',
          'reason':        'scanner_not_enabled',
          'mode':          entry[0],
        };
        final s = MoneroScannerStatus.fromJson(json);
        expect(s.mode, entry[1],
            reason: 'mode value "${entry[0]}" should map to '
                '"${entry[1]}"');
      }
    });


    test('missing mode field defaults to "none"', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus': 'disabled',
        'reason':        'scanner_not_enabled',
      });
      expect(s.mode, 'none');
    });
  });


  group('Detail-page source references — the fetch is wired', () {

    test('detail page imports the monero_scanner_status service', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        src.contains(
          "import '../services/monero_scanner_status.dart';",
        ),
        isTrue,
        reason: 'the detail page must import the monero scanner '
            'status service so it can fetch and parse it',
      );
    });


    test('detail page calls getXmrScannerStatus with the '
        'clientPlatform hint', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        src.contains('getXmrScannerStatus('),
        isTrue,
      );
      expect(
        src.contains('clientPlatform: moneroClientPlatform()'),
        isTrue,
        reason: 'the platform hint must be passed to the endpoint',
      );
    });


    test('detail page threads _backendMoneroScannerStatus into all '
        'three Monero cards', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        src.contains('backendStatus: _backendMoneroScannerStatus'),
        isTrue,
        reason: 'the parsed backend status must be threaded into '
            'each Monero card',
      );
    });


    test('detail page emits the dev-only debug log line', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        src.contains('xmr_scanner_ui_state'),
        isTrue,
        reason: 'the safe dev log line must be emitted so we can '
            'stop guessing from screenshots',
      );

      expect(src.contains('debugPrint'), isTrue);


      const banned = <String>[
        'seed', 'mnemonic', 'privateSpendKey', 'privateViewKey',
        'spendKey', 'viewKey', 'encryptedWalletSecret',
        'authToken',
      ];

      final logCallStart = src.indexOf('xmr_scanner_ui_state');
      final logCallEnd = src.indexOf(');', logCallStart);
      final logCallBlock = src.substring(
        logCallStart, logCallEnd,
      );
      for (final b in banned) {
        expect(
          logCallBlock.toLowerCase().contains(b.toLowerCase()),
          isFalse,
          reason: 'the client log leaks $b: $logCallBlock',
        );
      }
    });


    test('detail page renders the dev-reason diagnostic widget with '
        'a stable key', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        src.contains(
          'crypto_wallet_engine_asset_detail_monero_dev_reason',
        ),
        isTrue,
      );
      expect(
        src.contains('kDebugMode'),
        isTrue,
        reason: 'the diagnostic widget must be visibility-gated by '
            'kDebugMode so it is only visible in debug builds',
      );
    });
  });


  group('Safety — override reason set is a closed subset', () {

    test('scanner card override set is a closed-set subset of the '
        'closed-set reasons', () {
      final src = _readLib(
        'ui/crypto_wallet_engine_monero_scanner_card.dart',
      );

      final regex = RegExp(r'kMoneroScannerReason\w+');
      final referenced = regex.allMatches(src)
          .map((m) => m.group(0)!).toSet();

      const allowedIdentifiers = <String>{
        'kMoneroScannerReasonNotEnabled',
        'kMoneroScannerReasonNotConfigured',
        'kMoneroScannerReasonViewKeyMissing',
        'kMoneroScannerReasonUnreachable',
        'kMoneroScannerReasonSyncing',
        'kMoneroScannerReasonReady',
        'kMoneroScannerReasonError',
        'kMoneroScannerReasonLocalAvailable',
        'kMoneroScannerReasonRequiresDesktop',
      };
      for (final id in referenced) {
        expect(
          allowedIdentifiers.contains(id), isTrue,
          reason: 'scanner card references an unrecognised reason '
              'identifier: $id',
        );
      }
    });
  });
}
