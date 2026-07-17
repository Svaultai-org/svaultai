
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Future<void> _pump(
  WidgetTester tester, {
  HelpCenterMode mode = HelpCenterMode.signedIn,
  HelpLaunchMailFn? launchMailOverride,
  HelpClipboardWriteFn? clipboardWriteOverride,
  Size size = const Size(1400, 2000),
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: HelpCenterPage(
          mode: mode,
          launchMailOverride: launchMailOverride,
          clipboardWriteOverride: clipboardWriteOverride,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


Future<void> _scrollToContactSupport(WidgetTester tester) async {
  final finder = find.byKey(const Key('help_center_contact_support'));
  await tester.scrollUntilVisible(
    finder,
    400,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pumpAndSettle();
}


void main() {
  group('Contact Support section', () {
    testWidgets('renders title, body, and tappable email row', (tester) async {
      await _pump(tester);
      await _scrollToContactSupport(tester);

      expect(
        find.byKey(const Key('help_center_contact_support')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('help_contact_support_title')),
        findsOneWidget,
      );
      expect(find.text('Contact Support'), findsOneWidget);

      expect(
        find.byKey(const Key('help_contact_support_body')),
        findsOneWidget,
      );
      expect(
        find.text('Need help with VaultAI? Contact our support team.'),
        findsOneWidget,
      );

      expect(
        find.byKey(const Key('help_contact_support_email_link')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('help_contact_support_email_text')),
        findsOneWidget,
      );
      expect(find.text(kHelpContactSupportEmail), findsOneWidget);

      expect(find.byIcon(Icons.mail_outline), findsOneWidget);
    });

    testWidgets(
        'tapping the email row invokes launcher with prefilled mailto URI',
        (tester) async {
      Uri? captured;
      await _pump(
        tester,
        launchMailOverride: (uri) async {
          captured = uri;
          return true;
        },
      );
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_email_link')),
      );
      await tester.pumpAndSettle();

      expect(captured, isNotNull);
      expect(captured!.scheme, 'mailto');
      expect(captured!.path, kHelpContactSupportEmail);


      final decoded = Uri.decodeComponent(captured!.query);
      expect(decoded, contains('subject=VaultAI Support'));
      expect(decoded, contains('body=Please describe your issue below.'));
      expect(decoded, contains('Device:'));
      expect(decoded, contains('Platform: Android/iPhone/Web/Desktop'));
      expect(decoded, contains('App Version:'));


      expect(captured!.toString(), kHelpContactSupportMailtoUrl);


      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets(
        'shows friendly SnackBar (not a crash) when launcher returns false',
        (tester) async {
      await _pump(
        tester,
        launchMailOverride: (uri) async => false,
      );
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_email_link')),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(tester.takeException(), isNull);

      expect(
        find.byKey(const Key('help_contact_support_snackbar')),
        findsOneWidget,
      );

      expect(
        find.textContaining(kHelpContactSupportEmail),
        findsWidgets,
      );
    });

    testWidgets(
        'shows friendly SnackBar when the launcher throws an exception',
        (tester) async {
      await _pump(
        tester,
        launchMailOverride: (uri) async {
          throw Exception('PlatformException: no email app');
        },
      );
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_email_link')),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(tester.takeException(), isNull);
      expect(
        find.byKey(const Key('help_contact_support_snackbar')),
        findsOneWidget,
      );
    });

    testWidgets('renders in the public (signed-out) mode too', (tester) async {
      await _pump(tester, mode: HelpCenterMode.public);
      await _scrollToContactSupport(tester);
      expect(
        find.byKey(const Key('help_center_contact_support')),
        findsOneWidget,
      );
    });

    testWidgets('mailto constant matches the exact spec', (tester) async {
      expect(kHelpContactSupportEmail, 'vaultai@svaultai.com');
      expect(
        kHelpContactSupportMailtoUrl,
        'mailto:vaultai@svaultai.com'
        '?subject=VaultAI%20Support'
        '&body=Please%20describe%20your%20issue%20below.'
        '%0A%0ADevice:%20'
        '%0APlatform:%20Android/iPhone/Web/Desktop'
        '%0AApp%20Version:%20',
      );
    });

    testWidgets(
        'Copy email button renders with copy icon and localized label',
        (tester) async {
      await _pump(tester);
      await _scrollToContactSupport(tester);

      expect(
        find.byKey(const Key('help_contact_support_copy_email_button')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('help_contact_support_copy_email_text')),
        findsOneWidget,
      );
      expect(find.text('Copy email address'), findsOneWidget);
      expect(find.byIcon(Icons.copy_rounded), findsOneWidget);
    });

    testWidgets(
        'tapping Copy email writes the plain email to the clipboard '
        'and shows a friendly SnackBar', (tester) async {
      String? captured;
      await _pump(
        tester,
        clipboardWriteOverride: (text) async {
          captured = text;
        },
      );
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_copy_email_button')),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(tester.takeException(), isNull);
      expect(captured, kHelpContactSupportEmail);


      expect(captured, isNot(contains('mailto:')));
      expect(captured, isNot(contains('subject=')));
      expect(captured, isNot(contains('body=')));

      expect(
        find.byKey(const Key('help_contact_support_copy_snackbar')),
        findsOneWidget,
      );
      expect(find.text('Email copied to clipboard'), findsOneWidget);
    });

    testWidgets(
        'Copy email button stays silent (no crash, no snackbar) '
        'when the clipboard write throws', (tester) async {
      await _pump(
        tester,
        clipboardWriteOverride: (_) async {
          throw Exception('PlatformException: clipboard unavailable');
        },
      );
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_copy_email_button')),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(tester.takeException(), isNull);
      expect(
        find.byKey(const Key('help_contact_support_copy_snackbar')),
        findsNothing,
      );
    });

    testWidgets(
        'Copy email button uses the real Clipboard.setData channel '
        'when no override is provided', (tester) async {

      final List<MethodCall> log = <MethodCall>[];
      TestDefaultBinaryMessengerBinding
              .instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        log.add(call);
        return null;
      });
      addTearDown(() {
        TestDefaultBinaryMessengerBinding
                .instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform, null);
      });

      await _pump(tester);
      await _scrollToContactSupport(tester);

      await tester.tap(
        find.byKey(const Key('help_contact_support_copy_email_button')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      final setDataCall = log.firstWhere(
        (c) => c.method == 'Clipboard.setData',
        orElse: () => const MethodCall('missing'),
      );
      expect(setDataCall.method, 'Clipboard.setData',
          reason: 'expected a Clipboard.setData platform call');
      final args = setDataCall.arguments as Map<Object?, Object?>;
      expect(args['text'], kHelpContactSupportEmail);


      expect(
        find.byKey(const Key('help_contact_support_copy_snackbar')),
        findsOneWidget,
      );
    });

    testWidgets('no overflow on narrow mobile viewport (400×900)',
        (tester) async {
      await _pump(
        tester,
        mode: HelpCenterMode.public,
        size: const Size(400, 900),
      );
      expect(tester.takeException(), isNull);
    });
  });
}
