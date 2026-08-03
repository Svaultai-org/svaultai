import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';

Widget _app(
        {Locale locale = const Locale('en'),
        ThemeMode mode = ThemeMode.dark}) =>
    MaterialApp(
      locale: locale,
      supportedLocales: AppLocalizations.supportedLocales,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      theme: ThemeData.light(),
      darkTheme: ThemeData.dark(),
      themeMode: mode,
      routes: {
        '/privacy': (_) =>
            const Scaffold(body: Text('Privacy policy test route'))
      },
      home: const Scaffold(body: HelpCenterPage(mode: HelpCenterMode.public)),
    );

void main() {
  test('all required categories and trust topics exist', () {
    expect(kFaqCategories, hasLength(12));
    expect(kFaqEntries, hasLength(216));
    for (final entry in kFaqEntries) {
      expect(entry.question.trim(), isNotEmpty, reason: entry.id);
      expect(entry.answer.trim(), isNotEmpty, reason: entry.id);
    }
    expect(
        kFaqCategories.map((e) => e.label),
        containsAll(<String>[
          'About SVaultAI',
          'Privacy and Encryption',
          'Vault Access and PIN Security',
          'Files, Photos, Videos, and Voice Notes',
          'Saved Logins and Credentials',
          'Personal Memories and Private AI',
          'Devices and Account Security',
          'Crypto Wallet Privacy',
          'Inheritance and Beneficiaries',
          'Subscription and Inactivity',
          'Deleting Files and Vaults',
          'Safety and Best Practices',
        ]));
    for (final category in kFaqCategories) {
      expect(faqEntriesInCategory(category.id), isNotEmpty,
          reason: category.id);
    }
  });

  test('support and legal destinations use production URLs', () {
    expect(kHelpContactSupportMailtoUrl,
        startsWith('mailto:vaultai@svaultai.com'));
    expect(kHelpPrivacyPolicyUrl, 'https://app.svaultai.com/privacy');
    expect(kHelpTermsOfServiceUrl, 'https://app.svaultai.com/terms');
  });

  test('search, privacy, inactivity, wallet, and PIN wording are safe', () {
    expect(faqEntriesMatchingQuery('master key'), isNotEmpty);
    final all = kFaqEntries
        .map((e) => '${e.question} ${e.answer}')
        .join('\n')
        .toLowerCase();
    for (final phrase in <String>[
      'military-grade encryption',
      '100% unhackable',
      'completely anonymous',
      'impossible to breach',
      'guaranteed recovery'
    ]) {
      expect(all, isNot(contains(phrase)));
    }
    expect(faqEntryById('operational-metadata')!.answer,
        contains('limited operational records'));
    expect(faqEntryById('six-months')!.answer, contains('six months'));
    expect(faqEntryById('six-months')!.answer, contains('Logging in resets'));
    expect(faqEntryById('six-months')!.answer, contains('Subscribed vaults'));
    expect(faqEntryById('wallet-custody')!.answer.toLowerCase(),
        contains('non-custodial'));
    expect(faqEntryById('reset-pin')!.answer.toLowerCase(),
        isNot(contains('support can reset')));
    expect(all, isNot(contains('that is a bug')));
    expect(all, isNot(contains('specific phrase misroutes')));
  });

  testWidgets('search, categories, expansion, support, and legal links render',
      (tester) async {
    await tester.pumpWidget(_app());
    expect(find.byKey(const Key('help_center_search_field')), findsOneWidget);
    expect(
        find.byKey(const Key('help_center_contact_support')), findsOneWidget);
    expect(find.byKey(const Key('help_privacy_policy_link')), findsOneWidget);
    expect(find.byKey(const Key('help_terms_link')), findsOneWidget);
    await tester.enterText(
        find.byKey(const Key('help_center_search_field')), 'master key');
    await tester.pump();
    expect(find.text('Is there a master key or backdoor?'), findsOneWidget);
    await tester.ensureVisible(find.text('Is there a master key or backdoor?'));
    await tester.tap(find.text('Is there a master key or backdoor?'));
    await tester.pumpAndSettle();
    expect(
        find.byKey(const Key('help_entry_answer_master-key')), findsOneWidget);
  });

  for (final mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets(
        'supports ${mode.name}, text scaling, mobile width, and locale fallback',
        (tester) async {
      tester.view.physicalSize = const Size(320, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
          child: _app(locale: const Locale('de'), mode: mode)));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('SVaultAI Help Center'), findsOneWidget);
    });
  }
}
