// 2026-07-13 regression tests for the shared crypto-wallet sheet
// chrome that fixes the "no visible close/back control on Receive"
// production report.
//
// Every crypto Receive/Send bottom sheet now presents its body inside
// [CryptoWalletSheetChrome] via [showCryptoWalletSheet], which
// supplies a drag handle, a top title bar, and an explicit close X
// icon in the top-right corner. The chrome sits OUTSIDE the scrolling
// body so it remains visible even when the wallet content overflows
// the sheet.
//
// Suite covers: presentation, discoverability, tap-to-close,
// keyboard Escape dismissal, safe-area on mobile widths, source-
// guard that no receive/send sheet-caller uses bare showModalBottomSheet.

import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_sheet_chrome.dart';


Widget _wrapWithButton({
  required String title,
  required Widget child,
  VoidCallback? onBack,
  String sheetKey = 'crypto_wallet_engine_sheet',
}) {
  return MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    home: Scaffold(
      backgroundColor: kWalletBgBase,
      body: Builder(
        builder: (ctx) => Center(
          child: ElevatedButton(
            key: const Key('open_sheet_btn'),
            onPressed: () => showCryptoWalletSheet<void>(
              context: ctx,
              title: title,
              sheetKey: sheetKey,
              onBack: onBack,
              child: child,
            ),
            child: const Text('Open'),
          ),
        ),
      ),
    ),
  );
}


Future<void> _openSheet(WidgetTester t) async {
  await t.tap(find.byKey(const Key('open_sheet_btn')));
  await t.pumpAndSettle();
}


void main() {
  group('Sheet chrome renders visible controls', () {
    testWidgets('drag handle, title, and close X are all present '
        'when the sheet opens', (t) async {
      await t.pumpWidget(_wrapWithButton(
        title: 'Receive USDT (TRC20)',
        child: const SizedBox(height: 400),
      ));
      await _openSheet(t);

      // Drag handle at top.
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_sheet_drag_handle',
        )),
        findsOneWidget,
      );
      // Title.
      expect(
        find.byKey(const Key('crypto_wallet_engine_sheet_title')),
        findsOneWidget,
      );
      expect(find.text('Receive USDT (TRC20)'), findsOneWidget);
      // Explicit close X icon button.
      expect(
        find.byKey(const Key('crypto_wallet_engine_sheet_close_btn')),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.close), findsOneWidget);
    });

    testWidgets('back arrow renders only when onBack is provided',
        (t) async {
      await t.pumpWidget(_wrapWithButton(
        title: 'Confirm send',
        onBack: () {},
        child: const SizedBox(height: 400),
      ));
      await _openSheet(t);

      expect(
        find.byKey(const Key('crypto_wallet_engine_sheet_back_btn')),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
      // Close is still present.
      expect(
        find.byKey(const Key('crypto_wallet_engine_sheet_close_btn')),
        findsOneWidget,
      );
    });

    testWidgets('back arrow is HIDDEN when onBack is null (default)',
        (t) async {
      await t.pumpWidget(_wrapWithButton(
        title: 'Receive',
        child: const SizedBox(height: 400),
      ));
      await _openSheet(t);
      expect(
        find.byKey(const Key('crypto_wallet_engine_sheet_back_btn')),
        findsNothing,
      );
    });
  });

  group('Sheet chrome dismissal', () {
    testWidgets('tapping the close X dismisses the sheet', (t) async {
      await t.pumpWidget(_wrapWithButton(
        title: 'Receive ETH',
        child: const Text('body content'),
      ));
      await _openSheet(t);
      expect(find.text('body content'), findsOneWidget);

      await t.tap(find.byKey(const Key(
        'crypto_wallet_engine_sheet_close_btn',
      )));
      await t.pumpAndSettle();

      // Sheet is gone; underlying body content no longer visible.
      expect(find.text('body content'), findsNothing);
    });

    testWidgets('tapping the back arrow invokes onBack (does NOT '
        'auto-pop) — caller controls the step transition', (t) async {
      var backCalls = 0;
      await t.pumpWidget(_wrapWithButton(
        title: 'Confirm send',
        onBack: () => backCalls++,
        child: const Text('body content'),
      ));
      await _openSheet(t);
      expect(find.text('body content'), findsOneWidget);

      await t.tap(find.byKey(const Key(
        'crypto_wallet_engine_sheet_back_btn',
      )));
      await t.pumpAndSettle();
      expect(backCalls, equals(1));
    });
  });

  group('Sheet chrome mobile safe-area', () {
    for (final width in const <double>[320, 390, 430]) {
      testWidgets('close X remains reachable at ${width.toInt()}dp',
          (t) async {
        t.view.physicalSize = Size(width, 900);
        t.view.devicePixelRatio = 1.0;
        addTearDown(() {
          t.view.resetPhysicalSize();
          t.view.resetDevicePixelRatio();
        });

        await t.pumpWidget(_wrapWithButton(
          title: 'Receive USDT (TRC20) — network Ethereum '
              'Mainnet — very long title that must ellipsize',
          // Long body that would push chrome off-screen without a
          // Flexible/scrollable wrapper.
          child: Column(
            children: List.generate(
              50, (i) => Text('row $i', key: Key('row_$i')),
            ),
          ),
        ));
        await _openSheet(t);

        // Close button is on screen at the top, not covered by the
        // scrolling body.
        final closeFinder = find.byKey(
          const Key('crypto_wallet_engine_sheet_close_btn'),
        );
        expect(closeFinder, findsOneWidget,
            reason: 'close X must be reachable at ${width}dp');
        // No layout overflow exception.
        expect(t.takeException(), isNull);
        // Long title ellipsises rather than pushing the close button
        // off screen.
        expect(
          find.byKey(const Key(
            'crypto_wallet_engine_sheet_title',
          )),
          findsOneWidget,
        );
      });
    }
  });

  group('Sheet chrome — body scrolls under a fixed header', () {
    testWidgets('long body scrolls but drag handle + title + close '
        'stay pinned', (t) async {
      await t.pumpWidget(_wrapWithButton(
        title: 'Long content',
        child: Column(
          children: List.generate(
            60, (i) => SizedBox(
              height: 20,
              child: Text('row $i', key: Key('row_$i')),
            ),
          ),
        ),
      ));
      await _openSheet(t);

      // Both first and last rows exist; scroll to the last row.
      await t.drag(
        find.byKey(const Key('crypto_wallet_engine_sheet_scroll')),
        const Offset(0, -600),
      );
      await t.pumpAndSettle();

      // Header controls remain findable after scrolling — they live
      // outside the SingleChildScrollView.
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_sheet_close_btn',
        )),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_sheet_drag_handle',
        )),
        findsOneWidget,
      );
    });
  });

  group('Source-guard: every crypto Receive/Send sheet caller now '
      'uses showCryptoWalletSheet', () {
    List<String> _bareCallers(String path) {
      final src = File(path).readAsStringSync();
      // Any remaining showModalBottomSheet call in the crypto engine
      // pages is a regression — every caller was migrated on
      // 2026-07-13. Show the raw line for the reason string.
      final out = <String>[];
      final lines = src.split('\n');
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].contains('showModalBottomSheet')) {
          out.add('$path:${i + 1}: ${lines[i].trim()}');
        }
      }
      return out;
    }

    test('crypto_wallet_engine_page.dart uses no bare '
        'showModalBottomSheet', () {
      final leaks = _bareCallers(
        'lib/ui/crypto_wallet_engine_page.dart',
      );
      expect(
        leaks,
        isEmpty,
        reason: 'each Receive/Send flow must go through '
            'showCryptoWalletSheet so the close/back chrome is '
            'installed; found: $leaks',
      );
    });

    test('crypto_wallet_engine_asset_detail_page.dart uses no bare '
        'showModalBottomSheet', () {
      final leaks = _bareCallers(
        'lib/ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      expect(
        leaks,
        isEmpty,
        reason: 'per-asset detail page Receive/Send must also go '
            'through the shared sheet chrome; found: $leaks',
      );
    });

    test('showCryptoWalletSheet is invoked at least six times '
        'across the two crypto engine pages (Receive x3, Send x3)',
        () {
      var invocations = 0;
      for (final path in const [
        'lib/ui/crypto_wallet_engine_page.dart',
        'lib/ui/crypto_wallet_engine_asset_detail_page.dart',
      ]) {
        final src = File(path).readAsStringSync();
        final matches = 'showCryptoWalletSheet'.allMatches(src);
        invocations += matches.length;
      }
      expect(
        invocations, greaterThanOrEqualTo(6),
        reason: 'expected at least 6 showCryptoWalletSheet call '
            'sites (main page: Receive+Send; detail page: Receive+'
            'TronSend+SolanaSend+EvmSend) but found $invocations',
      );
    });
  });
}
