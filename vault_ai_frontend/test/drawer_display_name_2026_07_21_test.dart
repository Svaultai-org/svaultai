// Regression for the 2026-07-21 production report:
//
//   The hamburger drawer header still displays the internal
//   vault_name ("Yola") after deployment e797516. The vault_name is
//   the login/AI identity — never a user-visible label. Every
//   user-facing surface must use display_name with a neutral fallback.
//
// This file locks the drawer + adjacent user-visible surfaces to
// display_name.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _mainDart() => File('lib/main.dart').readAsStringSync();


String _drawerHeaderWindow() {
  final src = _mainDart();
  // The drawer header is inside `_buildSidebar()` and the drawer Text
  // is followed almost immediately by the sidebar tiles. Anchor on
  // the ListView key so we grab the surrounding Text() literal.
  final anchor = src.indexOf("'vault_drawer_menu_list'");
  expect(anchor, greaterThan(-1),
      reason: 'vault_drawer_menu_list key anchor must exist');
  final start = (anchor - 1200).clamp(0, src.length);
  return src.substring(start, anchor);
}


String _askChipWindow() {
  final src = _mainDart();
  final anchor = src.indexOf('Hidden for privacy. Ask ');
  expect(anchor, greaterThan(-1),
      reason: '"Hidden for privacy. Ask ..." literal must exist as anchor');
  final end = (anchor + 400).clamp(0, src.length);
  return src.substring(anchor, end);
}


String _askButtonWindow() {
  final src = _mainDart();
  // The "Ask <name>" button is inside the file card row and uses a
  // string interpolation `'Ask $<something>'` — anchor on that shape
  // to avoid matching the unrelated dashboard subtitles that also
  // start with 'Ask '.
  final anchor = src.indexOf(r"'Ask $");
  expect(anchor, greaterThan(-1),
      reason: '"Ask <name>" button interpolation literal must exist '
              'as anchor');
  // Grab the enclosing ternary — 400 chars back covers the `? ... : `
  // branch and captures which state field is read.
  final start = (anchor - 400).clamp(0, src.length);
  final end = (anchor + 200).clamp(0, src.length);
  return src.substring(start, end);
}


String _loginsSectionWindow() {
  final src = _mainDart();
  // `_DashboardSection.logins` is preceded by "case " and followed
  // immediately by the `final vaultDisplayName = ...` assignment.
  final anchor = src.indexOf('case _DashboardSection.logins:');
  expect(anchor, greaterThan(-1),
      reason: '_DashboardSection.logins case must exist as anchor');
  final end = (anchor + 800).clamp(0, src.length);
  return src.substring(anchor, end);
}


String _typingIndicatorWindow() {
  final src = _mainDart();
  final anchor = src.indexOf('ChatMessageList(');
  expect(anchor, greaterThan(-1),
      reason: 'ChatMessageList(...) call site must exist as anchor');
  final end = (anchor + 3000).clamp(0, src.length);
  return src.substring(anchor, end);
}


void main() {
  group('Drawer header — display_name only, never vault_name', () {
    test('drawer header does NOT read app.vaultName', () {
      final win = _drawerHeaderWindow();
      expect(
        win.contains('app.vaultName'),
        isFalse,
        reason: 'drawer header must NOT interpolate app.vaultName — '
                'the vault_name is the internal login/AI identity, '
                'never a user-visible label',
      );
    });

    test('drawer header reads app.displayName', () {
      final win = _drawerHeaderWindow();
      expect(
        win.contains('app.displayName'),
        isTrue,
        reason: 'drawer header must interpolate app.displayName as '
                'the primary user-visible label',
      );
    });

    test('drawer header keeps a neutral "Vault" fallback', () {
      final win = _drawerHeaderWindow();
      expect(
        win.contains("'Vault'"),
        isTrue,
        reason: 'when display_name is missing, the drawer must fall '
                'back to the neutral "Vault" literal — never to '
                'vault_name, vault_handle, or an empty string',
      );
    });
  });

  group('"Ask <name>" surfaces — display_name only', () {
    test('"Hidden for privacy. Ask ..." chip does NOT read vaultName', () {
      final win = _askChipWindow();
      expect(
        win.contains('.vaultName'),
        isFalse,
        reason: 'the "Ask ... in chat" file-privacy chip must address '
                'the AI by display_name, never by the internal '
                'vault_name',
      );
      expect(
        win.contains('.displayName'),
        isTrue,
        reason: 'the "Ask ... in chat" chip must use display_name',
      );
    });

    test('"Ask <name>" button label does NOT read vaultName', () {
      final win = _askButtonWindow();
      expect(
        win.contains('.vaultName'),
        isFalse,
        reason: 'the "Ask <name>" button label must address the AI '
                'by display_name, never by the internal vault_name',
      );
      expect(
        win.contains('.displayName'),
        isTrue,
        reason: 'the "Ask <name>" button must use display_name',
      );
    });
  });

  group('LoginsPage vaultLabel — display_name only', () {
    test('vaultLabel for LoginsPage does NOT read vaultName', () {
      final win = _loginsSectionWindow();
      expect(
        win.contains('.vaultName'),
        isFalse,
        reason: 'LoginsPage.vaultLabel is a user-visible header — '
                'never surface vault_name here',
      );
      expect(
        win.contains('.displayName'),
        isTrue,
        reason: 'LoginsPage.vaultLabel must interpolate display_name',
      );
    });
  });

  group('Chat typing indicator — display_name for "X is thinking..."', () {
    test('ChatMessageList is passed displayName, not vaultName, as '
         'its typing-indicator identity', () {
      final win = _typingIndicatorWindow();
      // Find the "vaultName:" parameter passed to ChatMessageList.
      // (The param is still called `vaultName` on the widget side —
      // that's an internal API name and out of scope for this rename —
      // but the SOURCE of the value must be app.displayName so the
      // indicator reads "<display_name> is thinking..." to match the
      // drawer / greeting.)
      final vaultNameParamIdx = win.indexOf('vaultName:');
      expect(vaultNameParamIdx, greaterThan(-1));
      // Grab the value passed on the same line.
      final lineEnd = win.indexOf(',', vaultNameParamIdx);
      final line = win.substring(vaultNameParamIdx, lineEnd);
      expect(
        line.contains('app.displayName'),
        isTrue,
        reason: 'ChatMessageList.vaultName parameter must be sourced '
                'from app.displayName so the typing indicator reads '
                'the same identity the drawer/greeting use',
      );
      expect(
        line.contains('app.vaultName'),
        isFalse,
        reason: 'never pass app.vaultName to the typing indicator — '
                'vault_name is the internal login/AI identity',
      );
    });
  });
}
