


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/responsive.dart';


const List<LocalizationsDelegate<Object?>> _l10n = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


const List<Size> _phoneSizes = [
  Size(320, 568),
  Size(375, 667),
  Size(390, 844),
  Size(414, 896),
  Size(430, 932),
];
const Size _tabletSize  = Size(768, 1024);
const Size _desktopSize = Size(1440, 900);


Widget _wrap(Widget child, {Size size = const Size(390, 844)}) {
  return MaterialApp(
    localizationsDelegates: _l10n,
    supportedLocales: AppLocalizations.supportedLocales,
    home: MediaQuery(
      data: MediaQueryData(
        size: size,
        devicePixelRatio: 2.0,
        disableAnimations: true,
      ),
      child: Scaffold(
        body: SizedBox(

          width: size.width,
          height: size.height,
          child: child,
        ),
      ),
    ),
  );
}


void main() {
  group('VaultResponsive breakpoints', () {
    test('320-599 px is compact/mobile', () {
      for (final w in [320.0, 375.0, 390.0, 414.0, 430.0, 599.0]) {
        final vr = VaultResponsive(
          width: w,
          height: 800,
          viewInsets: EdgeInsets.zero,
          viewPadding: EdgeInsets.zero,
        );
        expect(vr.isMobile, isTrue, reason: 'width=$w must be mobile');
        expect(vr.isTablet, isFalse);
        expect(vr.isDesktop, isFalse);
      }
    });

    test('320-360 px is narrow mobile', () {
      for (final w in [320.0, 340.0, 360.0]) {
        final vr = VaultResponsive(
          width: w,
          height: 800,
          viewInsets: EdgeInsets.zero,
          viewPadding: EdgeInsets.zero,
        );
        expect(vr.isNarrowMobile, isTrue);
      }
    });

    test('768-1199 px is tablet', () {
      for (final w in [768.0, 900.0, 1199.0]) {
        final vr = VaultResponsive(
          width: w,
          height: 800,
          viewInsets: EdgeInsets.zero,
          viewPadding: EdgeInsets.zero,
        );
        expect(vr.isMobile, isFalse);
        expect(vr.isTablet, isTrue);
        expect(vr.isDesktop, isFalse);
      }
    });

    test('1200+ px is desktop', () {
      for (final w in [1200.0, 1440.0, 1920.0]) {
        final vr = VaultResponsive(
          width: w,
          height: 800,
          viewInsets: EdgeInsets.zero,
          viewPadding: EdgeInsets.zero,
        );
        expect(vr.isDesktop, isTrue);
      }
    });

    test('drawer width = min(screen*0.86, 340)', () {
      final vr320 = VaultResponsive(
        width: 320, height: 568,
        viewInsets: EdgeInsets.zero, viewPadding: EdgeInsets.zero,
      );

      expect(vr320.drawerWidth, closeTo(275.2, 0.1));

      final vr430 = VaultResponsive(
        width: 430, height: 932,
        viewInsets: EdgeInsets.zero, viewPadding: EdgeInsets.zero,
      );

      expect(vr430.drawerWidth, 340.0);

      final vrDesktop = VaultResponsive(
        width: 1440, height: 900,
        viewInsets: EdgeInsets.zero, viewPadding: EdgeInsets.zero,
      );
      expect(vrDesktop.drawerWidth, 340.0);
    });

    test('composer dimensions are compact on mobile', () {
      final mobile = VaultResponsive(
        width: 375, height: 667,
        viewInsets: EdgeInsets.zero, viewPadding: EdgeInsets.zero,
      );
      expect(mobile.composerSendButtonSize, 36);
      expect(mobile.composerIconButtonSize, 36);
      expect(mobile.composerMinLines, 1);
      expect(mobile.composerMaxLines, 5);

      final desktop = VaultResponsive(
        width: 1440, height: 900,
        viewInsets: EdgeInsets.zero, viewPadding: EdgeInsets.zero,
      );
      expect(desktop.composerSendButtonSize, greaterThan(mobile.composerSendButtonSize));
    });

    test('keyboard inset > 0 wins over bottom safe inset', () {
      final withKeyboard = VaultResponsive(
        width: 375, height: 667,
        viewInsets: const EdgeInsets.only(bottom: 320),
        viewPadding: const EdgeInsets.only(bottom: 34),
      );
      expect(withKeyboard.bottomComposerInset, 320);

      final withoutKeyboard = VaultResponsive(
        width: 375, height: 667,
        viewInsets: EdgeInsets.zero,
        viewPadding: const EdgeInsets.only(bottom: 34),
      );
      expect(withoutKeyboard.bottomComposerInset, 34);
    });
  });

  group('ResponsiveActionBar layout', () {
    testWidgets('at 320 px: heading gets full row (was 1-char-per-line '
        'before), Wrap present for actions', (t) async {
      final key = GlobalKey();
      final headingKey = const Key('heading');
      final aKey = const Key('action_a');
      final bKey = const Key('action_b');

      await t.pumpWidget(_wrap(
        Padding(
          padding: const EdgeInsets.all(16),
          child: ResponsiveActionBar(
            key: key,
            heading: Container(
              key: headingKey,
              color: Colors.white24,
              child: const Text('People I\'ve added'),
            ),
            actions: [
              ElevatedButton(
                key: aKey,
                onPressed: () {},
                child: const Text('Refresh'),
              ),
              ElevatedButton(
                key: bKey,
                onPressed: () {},
                child: const Text('Add beneficiary'),
              ),
            ],
          ),
        ),
        size: const Size(320, 568),
      ));

      await t.pump();


      final headingBox = t.renderObject<RenderBox>(find.byKey(headingKey));
      expect(headingBox.size.width, greaterThan(200),
        reason: 'the actual production bug had heading collapse to a '
                'one-char column (~16 px). It must now get the full row.');



      expect(find.byType(Wrap), findsOneWidget,
        reason: 'on narrow widths the ResponsiveActionBar must render '
                'the actions inside a Wrap so they stack instead of '
                'squeezing the heading.');
    });

    testWidgets('at 1440 px: heading + actions inline on one row', (t) async {
      final headingKey = const Key('heading');
      final aKey = const Key('action_a');

      await t.pumpWidget(_wrap(
        Padding(
          padding: const EdgeInsets.all(16),
          child: ResponsiveActionBar(
            heading: Container(
              key: headingKey,
              color: Colors.white24,
              child: const Text('People I\'ve added'),
            ),
            actions: [
              ElevatedButton(
                key: aKey,
                onPressed: () {},
                child: const Text('Refresh'),
              ),
              ElevatedButton(
                onPressed: () {},
                child: const Text('Add beneficiary'),
              ),
            ],
          ),
        ),
        size: const Size(1440, 900),
      ));
      await t.pump();

      final headingBox = t.renderObject<RenderBox>(find.byKey(headingKey));
      final aBox       = t.renderObject<RenderBox>(find.byKey(aKey));

      final headingTop = headingBox.localToGlobal(Offset.zero).dy;
      final aTop       = aBox.localToGlobal(Offset.zero).dy;

      expect((aTop - headingTop).abs(), lessThan(60),
          reason: 'on desktop, action must be on the SAME row as heading');
    });
  });

  group('No RenderFlex overflow at any phone width', () {

    for (final size in _phoneSizes) {
      testWidgets('ResponsiveActionBar renders at ${size.width.toInt()} px '
          'without overflow', (t) async {
        await t.pumpWidget(_wrap(
          Padding(
            padding: const EdgeInsets.all(16),
            child: ResponsiveActionBar(
              heading: const Text(
                'People I\'ve added — including a fairly long heading',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
              ),
              actions: [
                OutlinedButton.icon(
                  onPressed: () {},
                  icon: const Icon(Icons.refresh, size: 18),
                  label: const Text('Refresh'),
                ),
                FilledButton.icon(
                  onPressed: () {},
                  icon: const Icon(Icons.person_add_alt_1, size: 18),
                  label: const Text('Add beneficiary'),
                ),
              ],
            ),
          ),
          size: size,
        ));
        await t.pump();


        final exception = t.takeException();
        expect(exception, isNull,
            reason: 'no RenderFlex/overflow at ${size.width}x${size.height}');
      });
    }

    testWidgets('ResponsiveActionBar at tablet width has no overflow', (t) async {
      await t.pumpWidget(_wrap(
        Padding(
          padding: const EdgeInsets.all(24),
          child: ResponsiveActionBar(
            heading: const Text('People I\'ve added',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
            actions: [
              OutlinedButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('Refresh'),
              ),
              FilledButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.person_add_alt_1, size: 18),
                label: const Text('Add beneficiary'),
              ),
            ],
          ),
        ),
        size: _tabletSize,
      ));
      await t.pump();
      expect(t.takeException(), isNull);
    });

    testWidgets('ResponsiveActionBar at desktop width has no overflow', (t) async {
      await t.pumpWidget(_wrap(
        Padding(
          padding: const EdgeInsets.all(32),
          child: ResponsiveActionBar(
            heading: const Text('People I\'ve added',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
            actions: [
              OutlinedButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('Refresh'),
              ),
              FilledButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.person_add_alt_1, size: 18),
                label: const Text('Add beneficiary'),
              ),
            ],
          ),
        ),
        size: _desktopSize,
      ));
      await t.pump();
      expect(t.takeException(), isNull);
    });
  });

  group('Source guards: main.dart wiring', () {

    String _mainSrc() {
      final f = File('lib/main.dart');
      return f.readAsStringSync();
    }

    test('main.dart imports the responsive helper', () {
      expect(_mainSrc(), contains("import 'ui/responsive.dart';"));
    });

    test('drawer uses VaultResponsive.drawerWidth', () {
      expect(_mainSrc(), contains('width: _vr.drawerWidth'));
    });

    test('drawer wraps menu items in a scrollable ListView', () {
      expect(_mainSrc(), contains("key: const Key('vault_drawer_menu_list')"));
      expect(_mainSrc(),
        contains("key: const Key('vault_drawer_menu_tail_sentinel')"));
    });

    test('drawer respects bottom SafeArea', () {
      final src = _mainSrc();

      expect(src.contains('bottomSafeInset'), isTrue,
        reason: 'drawer padding must respect vr.bottomSafeInset');
    });

    test('inheritance page uses ResponsiveActionBar for the '
         '"People I\'ve added" heading (no more collapsing Row)', () {
      final src = _mainSrc();




      final peopleIdx = src.indexOf("People I\\'ve added");
      expect(peopleIdx, greaterThan(0),
        reason: 'the heading text must still be present in main.dart');

      final windowStart = (peopleIdx - 500).clamp(0, src.length);
      final windowEnd   = (peopleIdx + 1500).clamp(0, src.length);
      final window = src.substring(windowStart, windowEnd);
      expect(window.contains('ResponsiveActionBar('), isTrue,
        reason: 'the People-I\'ve-added heading must be wrapped by '
                'ResponsiveActionBar (no more collapsing Row)');


      expect(window.contains("key: const Key('inheritance_refresh_button')"),
             isTrue);
      expect(window.contains("key: const Key('inheritance_add_beneficiary_button')"),
             isTrue);
    });

    test('composer uses circular send button (Semantics + Material), '
         'not a wide FilledButton.icon with a Send label on mobile', () {
      final src = _mainSrc();

      expect(src.contains("key: const Key('composer_send_button')"), isTrue);


      final composerIdx = src.indexOf('_buildComposer(bool isMobile)');
      expect(composerIdx, greaterThan(0));
      final composerBody = src.substring(
        composerIdx,
        (composerIdx + 4000).clamp(0, src.length),
      );

      expect(composerBody.contains('shape: const CircleBorder()'), isTrue,
        reason: 'send button must be circular on all widths');
    });

    test('composer wraps in SafeArea(bottom: true) for keyboard/'
         'bottom-safe handling', () {
      final src = _mainSrc();
      final composerIdx = src.indexOf('_buildComposer(bool isMobile)');
      final composerBody = src.substring(
        composerIdx,
        (composerIdx + 4000).clamp(0, src.length),
      );
      expect(composerBody.contains('SafeArea('), isTrue);
      expect(composerBody.contains('bottom: true'), isTrue);
    });

    test('composer TextField uses minLines=1 and mobile maxLines=5', () {
      final src = _mainSrc();
      final composerIdx = src.indexOf('_buildComposer(bool isMobile)');
      final composerBody = src.substring(
        composerIdx,
        (composerIdx + 4000).clamp(0, src.length),
      );

      expect(composerBody.contains('vr.composerMinLines'), isTrue);
      expect(composerBody.contains('vr.composerMaxLines'), isTrue);
    });

    test('drawer tiles are compact on mobile (compact: true '
         '+ smaller vertical padding)', () {
      final src = _mainSrc();

      expect(src.contains('compact: _vr.isMobile'), isTrue);

      expect(src.contains('verticalPadding: _drawerTileVpad'), isTrue);
    });

    test('no fixed "Sending..." wide FilledButton.icon label survives '
         'in the composer on mobile', () {
      final src = _mainSrc();
      final composerIdx = src.indexOf('_buildComposer(bool isMobile)');
      final composerBody = src.substring(
        composerIdx,
        (composerIdx + 4000).clamp(0, src.length),
      );


      expect(composerBody.contains("Text(sending ? 'Sending...' : 'Send')"),
             isFalse,
        reason:
          'the wide "Sending..." / "Send" label must be gone from mobile — '
          'replaced by the compact circular icon');
    });
  });
}


