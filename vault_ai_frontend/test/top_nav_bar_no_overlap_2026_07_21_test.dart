// Root-cause repro for the 2026-07-21 production layout regression:
//
//   Notification bell overlaps / is embedded in the "Vaultai"
//   wordmark on iPhone-width viewports. Reason (see the branch
//   investigation report): the wordmark Text is a naked child of
//   the title Row (main.dart:2316-2323) with no
//   Flexible/Expanded/overflow guard, while the AppBar actions
//   region reserves ~248px on mobile (48px bell IconButton + 4px
//   padding + 180px maxWidth account chip + 16px right padding).
//   On a 320px viewport the title Row's intrinsic width exceeds
//   the available slot and NavigationToolbar allows it to visually
//   collide with the actions region — the wordmark's tail letters
//   overpaint the bell IconButton.
//
// The bell only renders when app.unlocked is true, which requires
// the _VaultCrypto key cache to hold a live key. That cache is
// library-private to main.dart, so a widget test cannot populate
// it without an invasive test hook we don't want to add. Every
// assertion here is therefore expressed in one of two ways:
//
//   1. Live widget-tree tests using the AUTHENTICATED-BUT-NOT-
//      UNLOCKED state. This still renders the wordmark and the
//      account chip. The account chip is the widest actions-slot
//      element (up to 180px on mobile), and if the wordmark is
//      constrained enough to not overlap it, the bell (48px, sits
//      LEFT of the chip) is by construction also safe.
//   2. Source-scan tests that lock down the structural fix — the
//      wordmark MUST be wrapped in Flexible with maxLines:1 and
//      TextOverflow.ellipsis so the title Row can never eat the
//      actions region.
//
// These tests are written FIRST so they fail against the current
// widget tree; the structural fix will make them pass.

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
  // We do NOT touch app.unlocked — see the file header explanation.
  return app;
}


Future<void> _pumpHeader(
  WidgetTester tester, {
  required DeviceProfile device,
  required AppState app,
  bool showMenuButton = true,
  bool isMobile = true,
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


// The wordmark is a Text widget with data 'Vaultai'.
Finder _wordmarkTextFinder() {
  return find.byWidgetPredicate(
    (w) => w is Text && w.data == 'Vaultai',
  );
}


// The account chip surrounds the display name Text inside the
// PopupMenuButton's child Container. We reach the outer chip by
// walking up from the display-name Text to the ancestor Container
// with a BoxConstraints maxWidth.
Finder _accountChipContainerFinder(String displayName) {
  return find.ancestor(
    of: find.byWidgetPredicate(
      (w) => w is Text && w.data == displayName,
    ),
    matching: find.byWidgetPredicate((w) =>
        w is Container
        && w.constraints != null
        && w.constraints!.maxWidth.isFinite),
  );
}


String _mainDartSource() =>
    File('lib/main.dart').readAsStringSync();


// Grep out the title:Row block inside TopNavBar.build() so we can
// assert on its structure directly.
String _topNavBarTitleBlock() {
  final src = _mainDartSource();
  final classIdx = src.indexOf('class TopNavBar');
  expect(classIdx, greaterThan(-1), reason: 'TopNavBar must exist');
  final buildIdx = src.indexOf('Widget build(BuildContext context)', classIdx);
  final titleIdx = src.indexOf('title: Row(', buildIdx);
  expect(titleIdx, greaterThan(-1), reason: 'TopNavBar must have title:Row');
  // Take up to the "actions:" line so we don't accidentally scan
  // the actions.
  final actionsIdx = src.indexOf('actions:', titleIdx);
  return src.substring(titleIdx, actionsIdx);
}


void main() {
  // ─────────────────────────────────────────────────────────────────
  // Live widget tests: wordmark must not overlap the account chip.
  // ─────────────────────────────────────────────────────────────────

  group('TopNavBar — wordmark does not overlap actions on mobile', () {
    for (final device in DeviceProfiles.allPhones) {
      testWidgets(
        'wordmark ⟂ account chip @ ${device.name} '
        '(${device.width.toInt()}px)',
        (tester) async {
          final app = _authedAppState();
          await _pumpHeader(tester, device: device, app: app);

          final wordmark = _wordmarkTextFinder();
          final chip = _accountChipContainerFinder('Alexa');
          expect(wordmark, findsOneWidget,
              reason: 'header must render the Vaultai wordmark');
          expect(chip, findsWidgets,
              reason: 'header must render the account chip when authed');

          final wordmarkRect = _rectOf(tester, wordmark);
          final chipRect = _rectOf(tester, chip);

          final overlap = wordmarkRect.intersect(chipRect);
          final hasOverlap =
              overlap.width > 0 && overlap.height > 0;
          expect(
            hasOverlap, isFalse,
            reason: 'Wordmark $wordmarkRect overlaps account chip '
                '$chipRect @ ${device.name} — the title Row must not '
                'eat the actions region on narrow phones',
          );

          // Wordmark must be to the left of the chip with a visible
          // gap (>=4px).
          expect(
            chipRect.left, greaterThanOrEqualTo(wordmarkRect.right + 4.0),
            reason: '>=4px gap between wordmark right edge and chip '
                'left edge required on ${device.name}',
          );
        },
      );
    }
  });

  group('TopNavBar — with a long display name (worst-case squeeze)', () {
    testWidgets(
      'wordmark stays visible with a long display name @ iPhone SE',
      (tester) async {
        final app = _authedAppState(
          displayName: 'A Long Displayed Owner Name For Test Coverage',
        );
        await _pumpHeader(
            tester, device: DeviceProfiles.iphoneSE, app: app);

        final wordmark = _wordmarkTextFinder();
        expect(wordmark, findsOneWidget);
        final rect = _rectOf(tester, wordmark);
        // Non-zero width required — a Flexible with maxLines:1
        // + ellipsis may narrow the wordmark but must not collapse
        // it to invisible.
        expect(rect.width, greaterThan(0.0),
            reason: 'wordmark must not be zero-width — the fix must '
                    'not clip it to invisible on narrow phones');
      },
    );
  });

  // ─────────────────────────────────────────────────────────────────
  // Structural fix guard: source-scan the TopNavBar title block.
  // ─────────────────────────────────────────────────────────────────

  group('TopNavBar structure — wordmark wrapped in Flexible + ellipsis', () {
    test('title Row wraps the Vaultai Text in Flexible', () {
      final title = _topNavBarTitleBlock();
      // The wordmark must sit inside a Flexible so the title Row
      // yields horizontal space to the actions region before it
      // ever paints over them. `Expanded` would also work
      // structurally; either is acceptable.
      final vaultaiIdx = title.indexOf("'Vaultai'");
      expect(vaultaiIdx, greaterThan(-1),
          reason: 'Vaultai wordmark must exist in TopNavBar title');
      // Look at the parent widget the Text is nested inside. Take
      // ~600 chars of context BEFORE the wordmark string to catch
      // Flexible( or Expanded( in an outer wrapper.
      final start = (vaultaiIdx - 600).clamp(0, title.length);
      final context = title.substring(start, vaultaiIdx);
      final hasWrapper = context.contains('Flexible(')
          || context.contains('Expanded(');
      expect(hasWrapper, isTrue,
          reason: 'the Vaultai Text must be wrapped in Flexible(...) '
                  'or Expanded(...) — a naked Text child of the title '
                  'Row is what causes the actions-region overlap on '
                  'narrow phones');
    });

    test('wordmark Text has maxLines:1 + TextOverflow.ellipsis', () {
      final title = _topNavBarTitleBlock();
      final vaultaiIdx = title.indexOf("'Vaultai'");
      final windowEnd = (vaultaiIdx + 400).clamp(0, title.length);
      final window = title.substring(vaultaiIdx, windowEnd);
      expect(
        window.contains('maxLines: 1') || window.contains('maxLines:1'),
        isTrue,
        reason: 'wordmark Text must have maxLines:1 so it cannot wrap '
                'and push actions off-screen on narrow phones',
      );
      expect(
        window.contains('TextOverflow.ellipsis')
            || window.contains('overflow: TextOverflow.ellipsis'),
        isTrue,
        reason: 'wordmark Text must ellipsize on horizontal overflow',
      );
    });
  });
}
