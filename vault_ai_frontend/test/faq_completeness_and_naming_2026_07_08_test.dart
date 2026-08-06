
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


String _readLibFile(String rel) {
  final f = File('lib/$rel');
  expect(f.existsSync(), isTrue, reason: 'lib/$rel not found');
  return f.readAsStringSync();
}


const List<String> _kBackendFaqIds = <String>[

  'what-is-vaultai', 'what-can-i-save', 'how-do-i-create-my-vault',
  'how-do-i-unlock-my-vault', 'trusted-device', 'files-vs-secure-items',

  'is-my-vault-encrypted', 'can-vaultai-read-secrets',
  'if-i-forget-my-pin', 'can-someone-else-access', 'lost-my-device',
  'how-local-signing-works', 'never-share-seed',
  'delete-my-vault', 'what-happens-when-i-delete-my-vault',
  'can-i-recover-deleted-vault',

  'how-do-i-upload-files', 'what-file-types', 'search-inside-documents',
  'summarize-pdf', 'why-cant-find-file', 'how-do-i-delete-a-file',

  'how-do-i-save-a-password', 'how-do-i-view-a-password',
  'why-are-passwords-masked', 'generated-login',
  'edit-delete-secure-item', 'duplicate-logins',

  'save-passport-license', 'ids-masked-by-default',
  'id-expiry-reminders', 'how-do-i-search-ids',

  'what-is-crypto-vault', 'supported-assets', 'is-crypto-custodial',
  'can-vaultai-move-crypto', 'pin-before-sending',
  'usdt-erc20-vs-trc20', 'usdc-uses-eth-address',
  'erc20-needs-eth-gas', 'why-monero-different',
  'monero-balance-in-browser', 'monero-send-disabled',
  'buy-sell-swap', 'provider-unavailable', 'why-balance-zero',
  'receive-when-balance-zero',
  'crypto-when-vault-deleted',

  'what-plan-am-i-on', 'storage-limits', 'storage-exceeded',
  'how-do-i-upgrade', 'how-do-i-cancel', 'why-checkout-opens',
  'how-storage-calculated',
  'why-inactive-unpaid-deleted', 'how-to-prevent-auto-deletion',

  'why-balance-unavailable', 'why-file-not-showing',
  'why-chat-searches-files', 'monero-desktop-required',
  'tron-provider-unavailable', 'why-subscription-checking',
  'how-do-i-refresh', 'how-do-i-report-bug', 'how-do-i-get-support',
];


Future<void> _pumpHelpCenter(WidgetTester tester, {
  HelpCenterMode mode = HelpCenterMode.signedIn,
  Size size = const Size(1400, 12000),
  void Function(String q)? onAskAssistant,
  VoidCallback? onRequireSignIn,
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
          onAskAssistant: onAskAssistant,
          onRequireSignIn: onRequireSignIn,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {


  group('Cross-language FAQ ID consistency', () {
    test('every backend FAQ id has a frontend counterpart', () {
      final frontIds = kFaqEntries.map((e) => e.id).toSet();
      final missing = _kBackendFaqIds
          .where((id) => !frontIds.contains(id))
          .toList(growable: false);
      expect(missing, isEmpty,
          reason: 'frontend kFaqEntries is missing IDs: $missing');
    });

    test('frontend has no orphaned IDs not shipped by backend', () {

      final backendSet = _kBackendFaqIds.toSet();
      final orphans = kFaqEntries
          .map((e) => e.id)
          .where((id) => !backendSet.contains(id))
          .toList(growable: false);
      expect(orphans, isEmpty,
          reason:
              'frontend has FAQ IDs not present in backend: $orphans');
    });

    test('every frontend FAQ entry belongs to a valid category',
        () {
      final catIds = kFaqCategories.map((c) => c.id).toSet();
      for (final e in kFaqEntries) {
        expect(catIds.contains(e.category), isTrue,
            reason: '${e.id} references unknown category ${e.category}');
      }
    });
  });


  group('No Aisha in generic frontend product copy', () {

    const List<String> _libFiles = <String>[
      'help_center_page.dart',
      'help_center_content.dart',
      'ui/vault_chat_cards.dart',
    ];

    test('no generic "Aisha" in scanned frontend copy files', () {
      final offenders = <String>[];
      for (final rel in _libFiles) {
        final src = _readLibFile(rel);
        int lineNo = 0;
        for (final line in src.split('\n')) {
          lineNo++;
          if (RegExp(r'\bAisha\b', caseSensitive: false)
              .hasMatch(line)) {
            offenders.add('$rel:$lineNo: ${line.trim()}');
          }
        }
      }
      expect(offenders, isEmpty,
          reason:
              "Frontend lib copy contains 'Aisha'. Use "
              "'SVaultAI Chat' / 'Ask SVaultAI' / 'the assistant' "
              "instead. Offenders:\n${offenders.join('\n')}");
    });

    test('kFaqEntries answers never say "Aisha"', () {
      final offenders = kFaqEntries
          .where((e) => e.answer.contains('Aisha'))
          .map((e) => e.id)
          .toList(growable: false);
      expect(offenders, isEmpty,
          reason: 'FAQ answers mention "Aisha": $offenders');
    });
  });


  group('Copy naming constants', () {
    test('support note says "ask SVaultAI Chat" not "ask Aisha"',
        () {
      expect(kHelpCenterSupportNote,
          contains('ask SVaultAI Chat for help'));
      expect(kHelpCenterSupportNote.contains('Aisha'), isFalse);
    });

    test('public hint says "ask SVaultAI" not "ask Aisha"', () {
      expect(kHelpCenterPublicHint, contains('ask'));
      expect(kHelpCenterPublicHint, contains('SVaultAI'));
      expect(kHelpCenterPublicHint.contains('Aisha'), isFalse);
    });

    test('page title is "Help & FAQ"', () {
      expect(kHelpCenterTitle, 'Help & FAQ');
    });
  });


  group('FAQ card ask-button labels', () {
    testWidgets(
      'signed-in ask button label reads "Ask SVaultAI"',
      (tester) async {
        String? asked;
        await _pumpHelpCenter(
          tester, onAskAssistant: (q) => asked = q,
        );

        final askButtonFinder = find.byKey(
            const Key('help_entry_ask_what-is-vaultai'));
        expect(askButtonFinder, findsOneWidget);
        expect(
          find.descendant(
            of: askButtonFinder,
            matching: find.text('Ask SVaultAI'),
          ),
          findsOneWidget,
          reason: 'signed-in ask button must say "Ask SVaultAI"',
        );

        await tester.tap(askButtonFinder);
        await tester.pumpAndSettle();
        expect(asked, 'What is SVaultAI?');
      },
    );

    testWidgets(
      'public sign-in button label reads "Sign in to ask SVaultAI"',
      (tester) async {
        await _pumpHelpCenter(
          tester, mode: HelpCenterMode.public,
          onRequireSignIn: () {},
        );
        final signInButtonFinder = find.byKey(
            const Key('help_entry_signin_what-is-vaultai'));
        expect(signInButtonFinder, findsOneWidget);
        expect(
          find.descendant(
            of: signInButtonFinder,
            matching: find.text('Sign in to ask SVaultAI'),
          ),
          findsOneWidget,
        );
      },
    );
  });


  group('Help Center category and content coverage', () {
    test('has 8 categories', () {
      expect(kFaqCategories.length, 8);

      final labels = kFaqCategories.map((c) => c.label).toSet();
      expect(labels, containsAll(<String>[
        'Getting started', 'Security', 'Files', 'Secure items',
        'IDs', 'Crypto Vault', 'Billing', 'Troubleshooting',
      ]));
    });

    testWidgets(
      'renders every required FAQ id at 1400×12000',
      (tester) async {
        await _pumpHelpCenter(tester);
        for (final id in _kBackendFaqIds) {
          expect(
            find.byKey(Key('help_center_entry_$id')),
            findsOneWidget,
            reason: 'Help Center missing entry $id',
          );
        }
      },
    );

    test('crypto FAQ content includes required entries', () {
      final cryptoIds = kFaqEntries
          .where((e) => e.category == 'crypto')
          .map((e) => e.id).toSet();
      for (final required in <String>[
        'what-is-crypto-vault', 'supported-assets',
        'is-crypto-custodial', 'can-vaultai-move-crypto',
        'why-monero-different', 'monero-balance-in-browser',
        'monero-send-disabled', 'buy-sell-swap',
      ]) {
        expect(cryptoIds.contains(required), isTrue,
            reason: 'crypto category missing $required');
      }
    });

    test('security FAQ content includes forgot-PIN', () {
      final securityIds = kFaqEntries
          .where((e) => e.category == 'security')
          .map((e) => e.id).toSet();
      expect(securityIds.contains('if-i-forget-my-pin'), isTrue);
      expect(securityIds.contains('lost-my-device'), isTrue);
    });

    test('troubleshooting FAQ includes report-bug and support', () {
      final troublesIds = kFaqEntries
          .where((e) => e.category == 'troubleshooting')
          .map((e) => e.id).toSet();
      expect(troublesIds.contains('how-do-i-report-bug'), isTrue);
      expect(troublesIds.contains('how-do-i-get-support'), isTrue);
    });
  });


  group('Public Help Center safety', () {
    testWidgets(
      'public mode still shows all required FAQ IDs',
      (tester) async {
        await _pumpHelpCenter(
            tester, mode: HelpCenterMode.public);
        for (final id in _kBackendFaqIds) {
          expect(
            find.byKey(Key('help_center_entry_$id')),
            findsOneWidget,
            reason: 'Public Help Center missing $id',
          );
        }
      },
    );

    testWidgets(
      'public mode uses the "Sign in to ask SVaultAI" label '
      'consistently, not "Ask SVaultAI" directly',
      (tester) async {
        await _pumpHelpCenter(
            tester, mode: HelpCenterMode.public,
            onRequireSignIn: () {});

        expect(
          find.byKey(const Key(
              'help_entry_signin_what-is-vaultai')),
          findsOneWidget,
        );

        expect(
          find.byKey(const Key(
              'help_entry_ask_what-is-vaultai')),
          findsNothing,
        );
      },
    );
  });


  group('Forgot-PIN answer is honest', () {
    test('forgot-PIN answer mentions "recovery may not be possible"',
        () {
      final e = faqEntryById('if-i-forget-my-pin');
      expect(e, isNotNull);
      expect(
        e!.answer.toLowerCase(),
        contains('recovery may not be possible'),
        reason:
            'forgot-PIN answer must be honest — not promise '
            'recovery if not implemented',
      );
    });

    test('no FAQ promises 24/7 or live-agent support', () {
      for (final e in kFaqEntries) {
        for (final bad in <String>[
          '24/7', '24-7', 'live agent', 'call us', 'our agents',
        ]) {
          expect(
            e.answer.toLowerCase().contains(bad.toLowerCase()),
            isFalse,
            reason:
                '${e.id} answer promises live support that does '
                'not exist: "$bad"',
          );
        }
      }
    });
  });
}
