// Regression for the c2f917e production report:
//
//   Dashboard welcome shows "Welcome to Yola" where "Yola" is the
//   vault_name. The vault_name is the user's login identity and
//   AI identity — it should NOT be the visible greeting. Use the
//   display_name instead.
//
// Fix contract:
//   * Primary greeting reads from app.displayName.
//   * Neutral fallback "Welcome to your vault" when no displayName.
//   * Never greets using the vault_name.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _mainDart() => File('lib/main.dart').readAsStringSync();


String _welcomeCardWindow() {
  final src = _mainDart();
  // The dashboard welcome is followed immediately by the marketing
  // subtitle "Ask naturally, upload documents..." — that pair only
  // appears in the dashboard home widget, so we anchor on the
  // subtitle to reach the surrounding welcome text without matching
  // the unrelated "Welcome back" on the PIN sheet.
  final anchor = src.indexOf('Ask naturally, upload documents');
  expect(anchor, greaterThan(-1),
      reason: 'dashboard subtitle must exist as an anchor');
  // Grab ~800 chars before the anchor (welcome text + fallback +
  // any greeting closure sits within that window).
  final start = (anchor - 800).clamp(0, src.length);
  final end   = (anchor + 100).clamp(0, src.length);
  return src.substring(start, end);
}


void main() {
  group('Dashboard welcome card — displayName not vault_name', () {

    test(
      'the welcome heading does NOT interpolate app.vaultName',
      () {
        final win = _welcomeCardWindow();
        // Exact anti-pattern from the pre-fix code:
        //   'Welcome to ${app.vaultName ?? app.displayName ?? "your vault"}'
        // Must not appear.
        expect(
          win.contains('app.vaultName'),
          isFalse,
          reason: 'welcome heading must NOT interpolate '
                  'app.vaultName — the vault_name is the login/AI '
                  'identity, not a user-facing greeting label',
        );
      },
    );

    test(
      'the welcome heading interpolates app.displayName',
      () {
        final win = _welcomeCardWindow();
        expect(
          win.contains('app.displayName'),
          isTrue,
          reason: 'welcome heading must interpolate app.displayName '
                  'as the primary greeting',
        );
      },
    );

    test(
      'a neutral "your vault" fallback exists for the null case',
      () {
        final win = _welcomeCardWindow();
        // When displayName is null/empty we need a neutral fallback
        // ("Welcome to your vault") — anything that would leak
        // vault_name or handle here is a regression.
        expect(
          win.contains('your vault'),
          isTrue,
          reason: 'the null-displayName fallback must be a neutral '
                  '"your vault" string; must never leak vault_name '
                  'or vault_handle',
        );
      },
    );
  });
}
