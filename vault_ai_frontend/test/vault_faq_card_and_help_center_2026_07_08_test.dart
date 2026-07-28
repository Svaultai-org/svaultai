
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart'
    as vcr;
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Map<String, dynamic> _faqEnvelope({
  required String faqId,
  required String category,
  required String categoryLabel,
  required String question,
  required String answer,
  List<Map<String, String>> relatedQuestions = const [],
  List<String> relatedActions = const [],
  Map<String, dynamic>? extraCardFields,
}) {
  return {
    'intent': vcr.kVcrIntentFaq,
    'card': <String, dynamic>{
      'schema':            'vault_faq_v1',
      'cardType':          vcr.kVcrCardFaq,
      'faqId':             faqId,
      'category':          category,
      'categoryLabel':     categoryLabel,
      'question':          question,
      'answer':            answer,
      'relatedIds':        relatedQuestions.map((e) => e['id']).toList(),
      'relatedQuestions':  relatedQuestions,
      'relatedActions':    relatedActions,
      'message':           answer,
      if (extraCardFields != null) ...extraCardFields,
    },
  };
}


Future<void> _pumpChatCard(
  WidgetTester tester,
  Map<String, dynamic> envelope, {
  Size size = const Size(1400, 1200),
  void Function()?          onOpenHelpCenter,
  void Function()?          onOpenLoginsPage,
  void Function()?          onOpenIdDocumentsPage,
  void Function()?          onOpenCryptoVaultPage,
  void Function()?          onOpenBillingPage,
  void Function()?          onOpenStoragePage,
  void Function()?          onOpenSecurityPage,
  void Function()?          onOpenUploadPage,
  void Function()?          onOpenVault,
  void Function(String id)? onAskRelatedFaq,
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  final response = vcr.VaultChatResponse.fromJson(envelope);
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: VaultChatCardView(
          response: response,
          onOpenHelpCenter:       onOpenHelpCenter,
          onOpenLoginsPage:       onOpenLoginsPage,
          onOpenIdDocumentsPage:  onOpenIdDocumentsPage,
          onOpenCryptoVaultPage:  onOpenCryptoVaultPage,
          onOpenBillingPage:      onOpenBillingPage,
          onOpenStoragePage:      onOpenStoragePage,
          onOpenSecurityPage:     onOpenSecurityPage,
          onOpenUploadPage:       onOpenUploadPage,
          onOpenVault:            onOpenVault,
          onAskRelatedFaq:        onAskRelatedFaq,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


Future<void> _pumpHelpCenter(
  WidgetTester tester, {
  Size size = const Size(1400, 1200),
  void Function(String q)? onAskAssistant,
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
        body: HelpCenterPage(onAskAssistant: onAskAssistant),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {

  group('FAQ content module', () {
    test('exposes 8 categories', () {
      expect(kFaqCategories.length, 8);
    });

    test('has at least 40 entries', () {
      expect(kFaqEntries.length, greaterThanOrEqualTo(40));
    });

    test('every entry references a real category', () {
      final ids = kFaqCategories.map((c) => c.id).toSet();
      for (final e in kFaqEntries) {
        expect(ids.contains(e.category), isTrue,
            reason: '${e.id} references unknown category ${e.category}');
      }
    });

    test('faqEntryById round-trips', () {
      final ent = faqEntryById('what-is-vaultai');
      expect(ent, isNotNull);
      expect(ent!.question, 'What is Svaultai?');
    });

    test('faqEntriesMatchingQuery filters case-insensitively', () {
      final results = faqEntriesMatchingQuery('MONERO');
      expect(results, isNotEmpty);
      for (final e in results) {
        expect(
          e.question.toLowerCase().contains('monero') ||
              e.answer.toLowerCase().contains('monero'),
          isTrue,
        );
      }
    });

    test('faqEntriesInCategory only returns that category', () {
      final crypto = faqEntriesInCategory('crypto');
      expect(crypto, isNotEmpty);
      for (final e in crypto) {
        expect(e.category, 'crypto');
      }
    });

    test('crypto FAQ answers match product truths', () {
      final custodial = faqEntryById('is-crypto-custodial');
      expect(custodial, isNotNull);
      expect(custodial!.answer.toLowerCase(),
          contains('non-custodial'));

      final buySell = faqEntryById('buy-sell-swap');
      expect(buySell, isNotNull);
      final ans = buySell!.answer.toLowerCase();
      expect(ans.contains('does not support'), isTrue);
      expect(
          ans.contains('buy') && ans.contains('swap') &&
              ans.contains('trade'),
          isTrue);

      final xmrSend = faqEntryById('monero-send-disabled');
      expect(xmrSend, isNotNull);
      expect(xmrSend!.answer.toLowerCase(),
          contains('disabled'));

      final xmrBrowser = faqEntryById('monero-balance-in-browser');
      expect(xmrBrowser, isNotNull);
      expect(xmrBrowser!.answer.toLowerCase(),
          contains('desktop'));
    });

    test('security FAQ answers do NOT tell user to share secrets',
        () {
      for (final e in kFaqEntries) {
        if (e.category != 'security') continue;
        final lower = e.answer.toLowerCase();


        for (final bad in <String>[
          'send us your seed',
          'send your seed',
          'paste your seed',
          'here is your seed',
          'here is your private key',
          'please share your pin',
          'please share your seed',
        ]) {
          expect(lower.contains(bad), isFalse,
              reason: '${e.id}: forbidden phrase "$bad" in answer');
        }
      }
    });
  });


  group('FAQ card rendering', () {
    testWidgets('renders question and answer',
        (tester) async {
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'what-is-vaultai',
          category:      'getting_started',
          categoryLabel: 'Getting started',
          question:      'What is Svaultai?',
          answer:
              'Svaultai is your private digital vault. Think of a '
              'bank vault or a safe at home.',
        ),
      );

      expect(
        find.byKey(const Key(kVcrCardKeyFaq)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('vault_faq_card_question')),
        findsOneWidget,
      );
      expect(find.text('What is Svaultai?'), findsOneWidget);
      expect(
        find.textContaining('private digital vault',
            findRichText: true),
        findsOneWidget,
      );
    });

    testWidgets('renders category label',
        (tester) async {
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'is-my-vault-encrypted',
          category:      'security',
          categoryLabel: 'Security',
          question:      'Is my vault encrypted?',
          answer:        'Yes. Svaultai stores sensitive vault data '
              'encrypted.',
        ),
      );
      expect(
        find.textContaining('Security', findRichText: true),
        findsOneWidget,
      );
    });

    testWidgets('renders related questions as chips',
        (tester) async {
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'why-monero-different',
          category:      'crypto',
          categoryLabel: 'Crypto Vault',
          question:      'Why is Monero different?',
          answer:        'Monero is private.',
          relatedQuestions: const [
            {'id': 'monero-balance-in-browser',
             'question': "Why can't I see my Monero balance?"},
            {'id': 'monero-send-disabled',
             'question': 'Why is Monero send disabled?'},
          ],
        ),
      );
      expect(
        find.byKey(const Key('vault_faq_card_related')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
            'vault_faq_related_monero-balance-in-browser')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
            'vault_faq_related_monero-send-disabled')),
        findsOneWidget,
      );
    });

    testWidgets('related-question chip fires callback with id',
        (tester) async {
      String? asked;
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'why-monero-different',
          category:      'crypto',
          categoryLabel: 'Crypto Vault',
          question:      'Why is Monero different?',
          answer:        'Monero is private.',
          relatedQuestions: const [
            {'id': 'monero-balance-in-browser',
             'question': "Why can't I see my Monero balance?"},
          ],
        ),
        onAskRelatedFaq: (id) => asked = id,
      );

      await tester.tap(
        find.byKey(const Key(
            'vault_faq_related_monero-balance-in-browser')),
      );
      await tester.pumpAndSettle();
      expect(asked, 'monero-balance-in-browser');
    });

    testWidgets('related-action button renders when handler wired',
        (tester) async {
      var pressed = false;
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'what-is-crypto-vault',
          category:      'crypto',
          categoryLabel: 'Crypto Vault',
          question:      'What is Crypto Vault?',
          answer:        'Crypto Vault is the non-custodial wallet.',
          relatedActions: const ['open_crypto_vault'],
        ),
        onOpenCryptoVaultPage: () => pressed = true,
      );
      expect(
        find.byKey(const Key('vault_faq_action_open_crypto_vault')),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(const Key('vault_faq_action_open_crypto_vault')),
      );
      await tester.pumpAndSettle();
      expect(pressed, isTrue);
    });

    testWidgets('related-action button HIDDEN when handler NOT wired',
        (tester) async {

      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'what-is-crypto-vault',
          category:      'crypto',
          categoryLabel: 'Crypto Vault',
          question:      'What is Crypto Vault?',
          answer:        'Crypto Vault is the non-custodial wallet.',
          relatedActions: const ['open_crypto_vault'],
        ),
      );
      expect(
        find.byKey(const Key('vault_faq_action_open_crypto_vault')),
        findsNothing,
      );
    });

    testWidgets('open Help Center button fires callback',
        (tester) async {
      var openedHelp = false;
      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'what-is-vaultai',
          category:      'getting_started',
          categoryLabel: 'Getting started',
          question:      'What is Svaultai?',
          answer:        'Svaultai is a secure digital vault.',
        ),
        onOpenHelpCenter: () => openedHelp = true,
      );
      await tester.tap(
        find.byKey(const Key('vault_faq_card_open_help_center')),
      );
      await tester.pumpAndSettle();
      expect(openedHelp, isTrue);
    });

    testWidgets('crypto FAQ card DOES NOT leak seed / private key words',
        (tester) async {

      await _pumpChatCard(
        tester,
        _faqEnvelope(
          faqId:         'never-share-seed',
          category:      'security',
          categoryLabel: 'Security',
          question:      'Why should I not share my seed phrase?',
          answer:
              'Anyone with your seed phrase, private key, mnemonic, '
              'spend key, or view key can access or spend your crypto.',
        ),
      );

      final answerFinder = find.byKey(const Key('vault_faq_card_answer'));
      expect(answerFinder, findsOneWidget);
      final text = tester.widget<Text>(answerFinder).data ?? '';
      expect(text.toLowerCase().contains('share your seed'), isFalse);
      expect(text.toLowerCase().contains('paste your seed'), isFalse);
      expect(text.toLowerCase().contains('send us your'), isFalse);
    });

    testWidgets('mobile no overflow at 400×900',
        (tester) async {
      await _pumpChatCard(
        tester,
        size: const Size(400, 900),
        _faqEnvelope(
          faqId:         'usdt-erc20-vs-trc20',
          category:      'crypto',
          categoryLabel: 'Crypto Vault',
          question:      'Why does USDT have ERC20 and TRC20?',
          answer:
              'USDT exists on multiple networks. Svaultai supports '
              'USDT ERC20 on Ethereum and USDT TRC20 on TRON. You '
              'must pick the correct network — addresses, fees, and '
              'transfers are network-specific.',
          relatedQuestions: const [
            {'id': 'usdc-uses-eth-address',
             'question': 'Why does USDC use my Ethereum address?'},
            {'id': 'erc20-needs-eth-gas',
             'question': 'Why do token transfers need ETH for gas?'},
          ],
        ),
      );
      expect(tester.takeException(), isNull);
    });
  });


  group('Help Center page', () {
    testWidgets('renders heading and support note',
        (tester) async {
      await _pumpHelpCenter(tester);
      expect(
        find.byKey(const Key('help_center_heading')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('help_center_support_note')),
        findsOneWidget,
      );
    });

    testWidgets('renders every category chip',
        (tester) async {
      await _pumpHelpCenter(tester);
      for (final c in kFaqCategories) {
        expect(
          find.byKey(Key('help_center_chip_${c.id}')),
          findsOneWidget,
          reason: 'chip for ${c.id} missing',
        );
      }
    });

    testWidgets('renders every FAQ entry by default',
        (tester) async {
      await _pumpHelpCenter(tester);


      for (final e in [
        'what-is-vaultai',
        'is-my-vault-encrypted',
        'why-monero-different',
        'buy-sell-swap',
        'how-do-i-get-support',
      ]) {
        final finder = find.byKey(Key('help_center_entry_$e'));
        expect(finder, findsOneWidget,
            reason: 'entry $e not in widget tree');
      }
    });

    testWidgets(
      'search filters entries by term',
      (tester) async {
        await _pumpHelpCenter(tester);
        await tester.enterText(
          find.byKey(const Key('help_center_search_field')),
          'monero',
        );
        await tester.pumpAndSettle();


        expect(
          find.byKey(const Key('help_center_entry_why-monero-different')),
          findsOneWidget,
        );

        expect(
          find.byKey(const Key('help_center_entry_what-is-vaultai')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'category chip filters entries',
      (tester) async {
        await _pumpHelpCenter(tester);
        await tester.tap(find.byKey(const Key('help_center_chip_crypto')));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const Key('help_center_entry_what-is-crypto-vault')),
          findsOneWidget,
        );

        expect(
          find.byKey(const Key('help_center_entry_what-is-vaultai')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'search + no results shows empty state',
      (tester) async {
        await _pumpHelpCenter(tester);
        await tester.enterText(
          find.byKey(const Key('help_center_search_field')),
          'znthisdoesnotexistanywhere',
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('help_center_empty')),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'ask-assistant button fires callback with the question',
      (tester) async {
        String? asked;
        await _pumpHelpCenter(tester,
            size: const Size(1400, 12000),
            onAskAssistant: (q) => asked = q);


        final finder = find.byKey(
            const Key('help_entry_ask_what-is-vaultai'));
        expect(finder, findsOneWidget);
        await tester.tap(finder);
        await tester.pumpAndSettle();
        expect(asked, 'What is Svaultai?');
      },
    );

    testWidgets(
      'mobile no overflow at 400×900',
      (tester) async {
        await _pumpHelpCenter(tester,
            size: const Size(400, 900));
        expect(tester.takeException(), isNull);
      },
    );
  });
}
