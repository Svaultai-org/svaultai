// Origin: 2026-07-21 production layout regression — the notification
// bell overlapped / was embedded in the "Svaultai" wordmark on iPhone-
// width viewports.
//
// UPDATED 2026-07-21 (c2f917e follow-up): the original fix wrapped
// the wordmark in Flexible + maxLines:1 + TextOverflow.ellipsis so
// the title Row would yield space to the actions region. In
// production that produced "V..." at 320-412px, which reads as
// broken. The new fix HIDES the wordmark entirely on
// screenWidth < 600 and keeps the full "Svaultai" text on tablet+
// (>= 600).
//
// This test file was rewritten to reflect the new invariant:
//
//   * On phones (all DeviceProfiles.allPhones widths): the wordmark
//     Text('Svaultai') is NOT in the tree at all — proved by
//     the sibling suite in top_nav_bar_mobile_shield_only_2026_07_21_test.dart.
//     Nothing here re-asserts that; this file's mobile group is
//     removed.
//   * At tablet width (600+): the wordmark IS rendered AND does
//     not overlap the account chip.
//   * The wordmark, when rendered, is still wrapped in Flexible +
//     maxLines:1 + TextOverflow.ellipsis so a translated / longer
//     wordmark can still shrink safely without pushing actions off
//     screen at edge-case narrow tablet widths.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'dart:io';

import 'package:vault_ai_frontend/main.dart' show AppState, TopNavBar;

import '_helpers/responsive_harness.dart';

AppState _authedAppState({String displayName = 'Alexa'}) {
  final app = AppState();
  app.sessionToken = 'sess';
  app.vaultId = 'v-1';
  app.vaultName = 'Alexa';
  app.displayName = displayName;
  app.authed = true;
  return app;
}

class _UnlockedHeaderAppState extends AppState {
  _UnlockedHeaderAppState({required String displayName}) {
    sessionToken = 'sess';
    vaultId = 'v-1';
    vaultName = 'review-vault';
    this.displayName = displayName;
    authed = true;
  }

  @override
  bool get unlocked => true;

  @override
  set unlocked(bool value) {}
}

Future<void> _pumpHeader(
  WidgetTester tester, {
  required DeviceProfile device,
  required AppState app,
  bool showMenuButton = true,
  bool isMobile = false,
}) async {
  await pumpAtDevice(
    tester,
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: Scaffold(
        appBar: TopNavBar(
          isMobile: isMobile,
          showMenuButton: showMenuButton,
          onMenuTap: () {},
          onCreateTap: () {},
        ),
        body: const SizedBox.shrink(),
      ),
    ),
    device: device,
    wrapInScaffold: false,
  );
}

Rect _rectOf(WidgetTester tester, Finder finder) {
  final element = finder.evaluate().first;
  final box = element.renderObject as RenderBox;
  final topLeft = box.localToGlobal(Offset.zero);
  return topLeft & box.size;
}

Finder _wordmarkTextFinder() {
  return find.byWidgetPredicate(
    (w) => w is Text && w.data == 'Svaultai',
  );
}

Finder _accountChipContainerFinder(String displayName) {
  return find.ancestor(
    of: find.byWidgetPredicate(
      (w) => w is Text && w.data == displayName,
    ),
    matching: find.byWidgetPredicate((w) =>
        w is Container &&
        w.constraints != null &&
        w.constraints!.maxWidth.isFinite),
  );
}

String _mainDartSource() => File('lib/main.dart').readAsStringSync();

String _topNavBarTitleBlock() {
  final src = _mainDartSource();
  final classIdx = src.indexOf('class TopNavBar');
  expect(classIdx, greaterThan(-1), reason: 'TopNavBar must exist');
  final buildIdx = src.indexOf('Widget build(BuildContext context)', classIdx);
  final titleIdx = src.indexOf('title: Row(', buildIdx);
  expect(titleIdx, greaterThan(-1), reason: 'TopNavBar must have title:Row');
  final actionsIdx = src.indexOf('actions:', titleIdx);
  return src.substring(titleIdx, actionsIdx);
}

void main() {
  group('TopNavBar — unlocked phone actions never overflow', () {
    for (final device in DeviceProfiles.allPhones) {
      testWidgets(
        'menu, logo, create, bell, and long account fit @ ${device.name}',
        (tester) async {
          final app = _UnlockedHeaderAppState(
            displayName: 'A Long App Review Account Name',
          );
          await _pumpHeader(
            tester,
            device: device,
            app: app,
            isMobile: true,
          );

          expectNoOverflow(tester, context: '${device.name} unlocked header');
          expect(find.byKey(const Key('svaultai_brand_logo')), findsOneWidget);
          expect(
              find.byKey(const Key('top_nav_create_button')), findsOneWidget);
        },
      );
    }
  });

  // ─────────────────────────────────────────────────────────────────
  // Tablet + desktop still render the wordmark; it must not overlap
  // the account chip.
  // ─────────────────────────────────────────────────────────────────

  group('TopNavBar — wordmark does not overlap actions on tablet+', () {
    for (final device in <DeviceProfile>[
      DeviceProfiles.ipad, // 820x1180
      DeviceProfiles.desktop, // 1440x900
    ]) {
      testWidgets(
        'wordmark ⟂ account chip @ ${device.name} '
        '(${device.width.toInt()}px)',
        (tester) async {
          final app = _authedAppState();
          await _pumpHeader(tester, device: device, app: app);

          final wordmark = _wordmarkTextFinder();
          final chip = _accountChipContainerFinder('Alexa');
          expect(wordmark, findsOneWidget,
              reason: 'tablet+ must render the Svaultai wordmark');
          expect(chip, findsWidgets);

          final wordmarkRect = _rectOf(tester, wordmark);
          final chipRect = _rectOf(tester, chip);

          final overlap = wordmarkRect.intersect(chipRect);
          final hasOverlap = overlap.width > 0 && overlap.height > 0;
          expect(hasOverlap, isFalse,
              reason: 'Wordmark $wordmarkRect overlaps chip $chipRect '
                  '@ ${device.name}');
          expect(chipRect.left, greaterThanOrEqualTo(wordmarkRect.right + 4.0));
        },
      );
    }
  });

  group('TopNavBar — long display name at tablet width', () {
    testWidgets(
      'wordmark stays visible with a long display name @ iPad',
      (tester) async {
        final app = _authedAppState(
          displayName: 'A Long Displayed Owner Name For Test Coverage',
        );
        await _pumpHeader(tester, device: DeviceProfiles.ipad, app: app);
        final wordmark = _wordmarkTextFinder();
        expect(wordmark, findsOneWidget);
        expect(_rectOf(tester, wordmark).width, greaterThan(0.0));
      },
    );
  });

  // ─────────────────────────────────────────────────────────────────
  // Structural fix guard: when rendered, the wordmark must still be
  // wrapped in Flexible + maxLines:1 + TextOverflow.ellipsis so it
  // shrinks safely at edge-case narrow tablet widths.
  // ─────────────────────────────────────────────────────────────────

  group('TopNavBar structure — wordmark, when rendered, is Flexible+ellipsis',
      () {
    test('title Row wraps the Svaultai Text in Flexible when shown', () {
      final title = _topNavBarTitleBlock();
      final vaultaiIdx = title.indexOf("'Svaultai'");
      expect(vaultaiIdx, greaterThan(-1),
          reason: 'Svaultai wordmark literal must exist in title');
      final start = (vaultaiIdx - 600).clamp(0, title.length);
      final context = title.substring(start, vaultaiIdx);
      final hasWrapper =
          context.contains('Flexible(') || context.contains('Expanded(');
      expect(hasWrapper, isTrue,
          reason: 'wordmark, when rendered, must sit inside a '
              'Flexible/Expanded so it never pushes actions off '
              'screen at edge-case narrow tablet widths');
    });

    test('wordmark Text has maxLines:1 + TextOverflow.ellipsis', () {
      final title = _topNavBarTitleBlock();
      final vaultaiIdx = title.indexOf("'Svaultai'");
      final windowEnd = (vaultaiIdx + 400).clamp(0, title.length);
      final window = title.substring(vaultaiIdx, windowEnd);
      expect(
        window.contains('maxLines: 1') || window.contains('maxLines:1'),
        isTrue,
      );
      expect(
        window.contains('TextOverflow.ellipsis') ||
            window.contains('overflow: TextOverflow.ellipsis'),
        isTrue,
      );
    });

    test('wordmark is gated on screenWidth >= 600 (tablet+)', () {
      // Positive assertion that the wordmark is now behind a
      // tablet-width gate — this is what prevents "V..." on phones.
      final title = _topNavBarTitleBlock();
      final vaultaiIdx = title.indexOf("'Svaultai'");
      final start = (vaultaiIdx - 200).clamp(0, title.length);
      final context = title.substring(start, vaultaiIdx);
      expect(
        context.contains('screenWidth >= 600') ||
            context.contains('screenWidth >=600'),
        isTrue,
        reason: 'wordmark must be conditionally rendered behind a '
            '>= 600 tablet-width gate so phones show only the '
            'shield brand mark',
      );
    });
  });
}
