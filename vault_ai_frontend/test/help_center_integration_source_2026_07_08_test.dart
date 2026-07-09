
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _readMain() {
  final file = File('lib/main.dart');
  expect(file.existsSync(), isTrue,
      reason: 'lib/main.dart not found');
  return file.readAsStringSync();
}


String _window(String src, String marker, {int length = 6000}) {
  final idx = src.indexOf(marker);
  expect(idx, greaterThan(-1),
      reason: 'expected to find marker "$marker" in main.dart');
  return src.substring(idx, (idx + length).clamp(0, src.length));
}


void main() {


  group('main.dart imports help_center_page', () {
    test('imports help_center_page.dart', () {
      final src = _readMain();
      expect(
        src.contains("import 'help_center_page.dart'"),
        isTrue,
        reason: 'main.dart must import help_center_page.dart',
      );
    });
  });


  group('openHelpCenter helper', () {
    test('function is declared', () {
      final src = _readMain();
      expect(
        src.contains('Future<void> openHelpCenter('),
        isTrue,
        reason:
            'main.dart must declare openHelpCenter(BuildContext, '
            '{required HelpCenterMode mode})',
      );
    });

    test('function accepts HelpCenterMode via required param', () {
      final src = _readMain();
      expect(
        src.contains('required hc.HelpCenterMode mode'),
        isTrue,
      );
    });

    test('function routes public + signedIn distinctly', () {
      final src = _readMain();
      final window = _window(src, 'Future<void> openHelpCenter(',
          length: 2000);
      expect(window, contains("'/help-and-faq-public'"));
      expect(window, contains("'/help-and-faq'"));
    });

    test(
      'public route pop → pushNamed to /login when Sign in triggered',
      () {
        final src = _readMain();
        final window = _window(src, 'Future<void> openHelpCenter(',
            length: 2000);


        expect(
          window,
          contains("Navigator.of(context).pushNamed('/login')"),
        );
      },
    );
  });


  group('Top-nav (pre-sign-in) Help & FAQ entry', () {
    test('renders a Help & FAQ button when !app.authed', () {
      final src = _readMain();

      final window = _window(src, 'if (!app.authed) ...[', length: 1200);
      expect(
        window,
        contains("top_nav_help_and_faq_public"),
        reason: 'The pre-sign-in top-nav must include a button '
                'keyed "top_nav_help_and_faq_public"',
      );
      expect(
        window,
        contains('openHelpCenter'),
      );
      expect(
        window,
        contains('HelpCenterMode.public'),
      );
    });

    test('desktop top-nav uses TextButton.icon with "Help & FAQ"',
        () {
      final src = _readMain();

      final anchor = src.indexOf("if (!app.authed) ...[");
      expect(anchor, greaterThan(-1));
      final window = src.substring(
        anchor, (anchor + 1500).clamp(0, src.length),
      );
      expect(window, contains("'Help & FAQ'"));
      expect(window, contains('TextButton.icon('));
    });

    test('LoginPage form body has a Help & FAQ link (mobile-visible)',
        () {
      final src = _readMain();
      expect(
        src.contains("Key('login_form_help_and_faq')"),
        isTrue,
        reason:
            'LoginPage form must include a Help & FAQ link keyed '
            '"login_form_help_and_faq" so mobile users have '
            'access without the top-nav button',
      );
      final window = _window(
          src, "login_form_help_and_faq", length: 400);
      expect(window, contains('openHelpCenter'));
      expect(window, contains('HelpCenterMode.public'));
    });
  });


  group('Account menu (post-sign-in) Help & FAQ entry', () {
    test('account PopupMenuButton exposes a Help & FAQ item', () {
      final src = _readMain();

      final window = _window(
          src, "PopupMenuButton<String>(", length: 3000);
      expect(
        window,
        contains('account_menu_help_and_faq'),
        reason:
            'account menu must include a PopupMenuItem keyed '
            '"account_menu_help_and_faq"',
      );
      expect(window, contains("value: 'help_and_faq'"));


      expect(
        window.contains('Help & FAQ') ||
        window.contains('helpCenterTitle'),
        isTrue,
        reason:
            'account menu must show a Help & FAQ label, either as '
            'the literal string or via AppLocalizations.helpCenterTitle',
      );
    });

    test('menu selection opens help center in signed-in mode', () {
      final src = _readMain();

      final window = _window(src, "if (v == 'help_and_faq')",
          length: 400);
      expect(window, contains('openHelpCenter'));
      expect(window, contains('HelpCenterMode.signedIn'));
    });
  });


  group('Settings page Help & FAQ tile', () {
    test('Settings section includes a Help & FAQ InkWell tile', () {
      final src = _readMain();
      expect(
        src.contains("Key('settings_help_and_faq_tile')"),
        isTrue,
        reason:
            'Settings section must include an InkWell tile keyed '
            '"settings_help_and_faq_tile"',
      );
    });

    test('tile opens Help Center in signed-in mode', () {
      final src = _readMain();
      final window = _window(
          src, "settings_help_and_faq_tile", length: 800);
      expect(window, contains('openHelpCenter'));
      expect(window, contains('HelpCenterMode.signedIn'));
    });
  });


  group('LoginPage renders TopNavBar (so Help button is visible)', () {
    test('LoginPage.build uses TopNavBar with default showActions',
        () {
      final src = _readMain();
      final window = _window(src, 'class LoginPage extends StatefulWidget',
          length: 5000);


      expect(
        window.contains('TopNavBar(isMobile:'),
        isTrue,
        reason:
            'LoginPage must render TopNavBar so the pre-sign-in '
            'Help & FAQ button appears in the header',
      );

      expect(
        window.contains('TopNavBar(showActions: false'),
        isFalse,
        reason:
            'LoginPage TopNavBar must NOT set showActions:false '
            'or the Help & FAQ button would be hidden',
      );
    });
  });
}
