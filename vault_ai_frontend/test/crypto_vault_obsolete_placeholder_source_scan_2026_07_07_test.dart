import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_scanner_status.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


final _libDir = Directory('${Directory.current.path}/lib');


Iterable<File> _allLibDartFiles() sync* {
  for (final entity in _libDir.listSync(recursive: true)) {
    if (entity is File && entity.path.endsWith('.dart')) {
      yield entity;
    }
  }
}


Widget _pumpEngine() =>
    const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage()));


void main() {


  group('Obsolete placeholder text is ABSENT from every lib/ file', () {


    const _forbiddenStrings = <String>[
      "'Coming next'",
      "'Privacy wallet later'",
      "'Solana wallet support is coming next.'",
      "'USDT TRC20 support is planned.'",
      'Monero requires a special',
      'no Send, no Receive, no QR',
      'No Send, no Receive, no QR',
    ];


    test('no lib/ file mentions the obsolete placeholder strings',
        () {
      for (final file in _allLibDartFiles()) {
        final content = file.readAsStringSync();
        for (final banned in _forbiddenStrings) {
          expect(
            content.contains(banned),
            isFalse,
            reason:
                '${file.path} still contains obsolete placeholder '
                'text: $banned',
          );
        }
      }
    });


    test('kSolanaReceiveDisabledMessage no longer says "coming next"',
        () {
      const src = 'lib/ui/crypto_wallet_engine_solana_receive_panel.dart';
      final content = File(
        '${Directory.current.path}/$src',
      ).readAsStringSync();
      expect(
        content,
        isNot(contains("Solana wallet support is coming next.")),
      );
    });


    test('kTronReceiveDisabledMessage and kTronActivityDisabledCopy '
        'no longer say "support is planned"', () {
      for (final rel in const [
        'lib/ui/crypto_wallet_engine_tron_receive_panel.dart',
        'lib/ui/crypto_wallet_engine_tron_activity_card.dart',
      ]) {
        final content = File(
          '${Directory.current.path}/$rel',
        ).readAsStringSync();
        expect(
          content,
          isNot(contains("USDT TRC20 support is planned.")),
        );
      }
    });


    test('detail page no longer defines the "Monero needs a separate" '
        'banner copy', () {
      const src = 'lib/ui/crypto_wallet_engine_asset_detail_page.dart';
      final content = File(
        '${Directory.current.path}/$src',
      ).readAsStringSync();
      expect(
        content,
        isNot(contains('Monero needs a separate')),
      );
      expect(
        content,
        isNot(contains("'Privacy wallet later'")),
      );
      expect(
        content,
        isNot(contains("?? 'Planned'")),
      );
    });
  });


  group('Crypto Vault first-frame render: no obsolete text, ever', () {

    const _bannedTextsAtRender = <String>[
      'Coming next',
      'Planned',
      'Privacy wallet later',
      'Solana wallet support is coming next.',
      'USDT TRC20 support is planned.',
      'no Send, no Receive, no QR',
      'No Send, no Receive, no QR',
    ];


    testWidgets(
        'first frame — before any pump — never contains obsolete text',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_pumpEngine());


      for (final banned in _bannedTextsAtRender) {
        expect(
          find.text(banned),
          findsNothing,
          reason: 'first frame contains obsolete text: $banned',
        );
      }
    });


    testWidgets(
        'after pumpAndSettle — still no obsolete text',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_pumpEngine());
      await tester.pumpAndSettle();

      for (final banned in _bannedTextsAtRender) {
        expect(
          find.text(banned),
          findsNothing,
          reason:
              'after settle contains obsolete text: $banned',
        );
      }
    });


    testWidgets(
        'every launched asset carries the Live badge — never any '
        'future-state badge',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_pumpEngine());
      await tester.pumpAndSettle();

      for (final asset in kCryptoWalletEngineLaunchedAssets) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_live_$asset')),
          findsOneWidget,
          reason: '$asset must show Live badge on first frame',
        );
        expect(
          find.byKey(
              Key('crypto_wallet_engine_card_future_state_$asset')),
          findsNothing,
          reason: '$asset must not carry a future-state badge',
        );
      }
    });
  });


  group('XMR local_scanner_available closed-set copy is safe too', () {

    test('the balance and activity copies for local_scanner_available '
        'never contain obsolete placeholder text', () {
      const banned = <String>[
        'Coming next',
        'Planned',
        'Privacy wallet later',
        'Solana wallet support is coming next.',
        'USDT TRC20 support is planned.',
        'no Send, no Receive, no QR',
        'coming soon',
      ];
      final strings = <String>[
        moneroScannerBalanceCopyForReason('local_scanner_available'),
        moneroScannerActivityCopyForReason('local_scanner_available'),
        moneroScannerBalanceCopyForReason('scanner_not_enabled'),
        moneroScannerActivityCopyForReason('scanner_not_enabled'),
      ];
      for (final s in strings) {
        for (final b in banned) {
          expect(s.toLowerCase().contains(b.toLowerCase()), isFalse,
              reason: 'closed-set copy "$s" leaks "$b"');
        }
      }
    });


    test('local_scanner_available balance copy does not fabricate a '
        'numeric XMR amount', () {
      final s = moneroScannerBalanceCopyForReason(
        'local_scanner_available',
      );
      expect(s, isNot(contains('0 XMR')));
      expect(s, isNot(matches(RegExp(r'\d+(\.\d+)?\s*XMR'))));
    });
  });


  group('Detail-page constants — safe honest copy after the polish', () {

    test('kAssetDetailComingSoonHeading is "Unavailable", not '
        '"Coming soon"', () {

      const src = 'lib/ui/crypto_wallet_engine_asset_detail_page.dart';
      final content = File(
        '${Directory.current.path}/$src',
      ).readAsStringSync();
      expect(
        content,
        contains(
          "const String kAssetDetailComingSoonHeading = 'Unavailable';",
        ),
      );
    });


    test('kAssetDetailMoneroBanner is now the scanner-gated body, '
        'not "ships in a later phase"', () {
      const src = 'lib/ui/crypto_wallet_engine_asset_detail_page.dart';
      final content = File(
        '${Directory.current.path}/$src',
      ).readAsStringSync();
      expect(content, isNot(contains('ships in a later phase')));
      expect(content, isNot(contains('later phase')));
    });
  });
}
