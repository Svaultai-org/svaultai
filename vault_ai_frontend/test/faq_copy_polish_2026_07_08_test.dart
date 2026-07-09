
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


Future<void> _pumpHelpCenter(
  WidgetTester tester, {
  HelpCenterMode mode = HelpCenterMode.signedIn,
  Size size = const Size(1400, 12000),
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: HelpCenterPage(mode: mode)),
    ),
  );
  await tester.pumpAndSettle();
}


String _requireAnswer(String id) {
  final e = faqEntryById(id);
  expect(e, isNotNull, reason: 'FAQ $id must exist in kFaqEntries');
  return e!.answer;
}


void main() {


  group('Part A — What is VaultAI?', () {
    test('uses the physical vault / safe analogy', () {
      final lower = _requireAnswer('what-is-vaultai').toLowerCase();
      expect(
        lower.contains('bank vault') || lower.contains('safe at home'),
        isTrue,
        reason:
            'answer must include a bank-vault / safe-at-home '
            'analogy so non-technical users get the concept',
      );
    });

    test('lists every kind of record a user can keep', () {
      final lower = _requireAnswer('what-is-vaultai').toLowerCase();
      for (final k in <String>[
        'files', 'documents', 'photos', 'videos', 'audio',
        'passwords', 'secure notes', 'id documents',
        'crypto vault',
      ]) {
        expect(lower.contains(k), isTrue,
            reason: 'answer must list "$k"');
      }
    });

    test('contrasts with scattered password storage', () {
      final lower = _requireAnswer('what-is-vaultai').toLowerCase();
      expect(
        lower.contains('emails, notes, screenshots') ||
            lower.contains('random folders') ||
            lower.contains('instead of saving'),
        isTrue,
      );
    });

    test('does NOT overpromise security', () {
      final lower = _requireAnswer('what-is-vaultai').toLowerCase();
      for (final bad in <String>[
        'hackers won', 'hackers will never',
        'impossible to hack', 'guaranteed safe',
        'anonymous vault', 'nobody will know',
        'no one can ever access', 'unhackable',
        'perfect security', 'perfectly safe',
        'completely anonymous',
      ]) {
        expect(lower.contains(bad), isFalse,
            reason: 'answer must not contain "$bad"');
      }
    });
  });


  group('Part B — What can I save?', () {
    test('does not use "wallet records" as user-facing category', () {
      final lower = _requireAnswer('what-can-i-save').toLowerCase();
      expect(
        lower.contains('crypto vault wallet records'), isFalse,
        reason:
            'the previous wording ("Crypto Vault wallet records") '
            'confused users — the fix must not restore it',
      );
    });

    test('mentions internal wallet records are separately managed',
        () {
      final lower = _requireAnswer('what-can-i-save').toLowerCase();
      expect(lower.contains('internal wallet records'), isTrue);
      expect(lower.contains('not shown as normal secure items'), isTrue);
    });

    test('lists photos, videos, audio as savable', () {
      final lower = _requireAnswer('what-can-i-save').toLowerCase();
      for (final k in <String>['photos', 'videos', 'audio']) {
        expect(lower.contains(k), isTrue, reason: 'missing "$k"');
      }
    });

    test('mentions Crypto Vault assets', () {
      final lower = _requireAnswer('what-can-i-save').toLowerCase();
      expect(lower.contains('crypto vault assets'), isTrue);
    });
  });


  group('Part C — How do I create my vault?', () {
    test('does NOT claim email sign-up', () {
      final lower = _requireAnswer('how-do-i-create-my-vault')
          .toLowerCase();
      for (final bad in <RegExp>[
        RegExp(r'sign\s+up\s+with\s+an\s+email'),
        RegExp(r'sign\s+up\s+with\s+your\s+email'),
        RegExp(r'register\s+with\s+(?:an\s+)?email'),
        RegExp(r'email\s+registration'),
      ]) {
        expect(bad.hasMatch(lower), isFalse,
            reason:
                'answer must not describe email sign-up '
                '(pattern: ${bad.pattern})');
      }
    });

    test('mentions the vault sign-in flow, not email sign-up', () {
      final lower = _requireAnswer('how-do-i-create-my-vault')
          .toLowerCase();
      expect(lower.contains('sign-in flow'), isTrue);
    });

    test('is honest about recovery limits', () {
      final lower = _requireAnswer('how-do-i-create-my-vault')
          .toLowerCase();
      expect(lower.contains('recovery is not available'), isTrue,
          reason:
              'answer must not promise recovery if not implemented');
    });

    test('mentions PIN', () {
      expect(
        _requireAnswer('how-do-i-create-my-vault').contains('PIN'),
        isTrue,
      );
    });
  });


  group('Part D — How do I unlock my vault?', () {
    test('uses trusted-device + PIN wording', () {
      final lower = _requireAnswer('how-do-i-unlock-my-vault')
          .toLowerCase();
      expect(lower.contains('trusted device'), isTrue);
      expect(lower.contains('pin'), isTrue);
    });

    test('does NOT claim email login', () {
      final lower = _requireAnswer('how-do-i-unlock-my-vault')
          .toLowerCase();
      for (final bad in <String>[
        'log in with your email', 'log in with email',
        'sign in with your email', 'sign in with email',
        'email login',
      ]) {
        expect(lower.contains(bad), isFalse);
      }
    });
  });


  group('Part E — no overpromising across every FAQ entry', () {
    final forbidden = <RegExp>[
      RegExp(r'hackers?\s+will\s+never', caseSensitive: false),
      RegExp(r"hackers?\s+won['’]?t\s+know", caseSensitive: false),
      RegExp(r"hackers?\s+can['’]?t", caseSensitive: false),
      RegExp(r'impossible\s+to\s+hack', caseSensitive: false),
      RegExp(r'guaranteed\s+safe', caseSensitive: false),
      RegExp(r'anonymous\s+vault', caseSensitive: false),
      RegExp(r'nobody\s+will\s+know\s+you\s+own',
          caseSensitive: false),
      RegExp(r'no\s+one\s+can\s+ever\s+access',
          caseSensitive: false),
      RegExp(r'perfectly\s+safe', caseSensitive: false),
      RegExp(r'unhackable', caseSensitive: false),
      RegExp(r'completely\s+anonymous', caseSensitive: false),
      RegExp(r'perfect\s+security', caseSensitive: false),
      RegExp(r'total\s+privacy', caseSensitive: false),
    ];

    test('no forbidden phrase in any of the 60 entries', () {
      final offenders = <String>[];
      for (final e in kFaqEntries) {
        for (final r in forbidden) {
          if (r.hasMatch(e.answer)) {
            offenders.add('${e.id} matched ${r.pattern}');
          }
        }
      }
      expect(offenders, isEmpty,
          reason: 'FAQ overpromises:\n${offenders.join('\n')}');
    });
  });


  group('Help Center renders the improved copy', () {
    testWidgets(
      'signed-in Help Center renders new What-is-VaultAI copy',
      (tester) async {
        await _pumpHelpCenter(tester);
        expect(
          find.textContaining('private digital vault',
              findRichText: true),
          findsWidgets,
          reason: 'improved answer must render',
        );
      },
    );

    testWidgets(
      'public Help Center renders new create-vault copy without '
      'email sign-up wording',
      (tester) async {
        await _pumpHelpCenter(tester,
            mode: HelpCenterMode.public);
        expect(
          find.textContaining('sign-in flow',
              findRichText: true),
          findsWidgets,
        );
        expect(
          find.textContaining('Sign up with an email',
              findRichText: true),
          findsNothing,
          reason: 'the old email-sign-up copy must not render',
        );
      },
    );

    testWidgets(
      'Help Center at 400x900 mobile has no overflow with new copy',
      (tester) async {
        await _pumpHelpCenter(tester,
            size: const Size(400, 900));
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'Help Center at 360x800 mobile has no overflow with new copy',
      (tester) async {
        await _pumpHelpCenter(tester,
            size: const Size(360, 800));
        expect(tester.takeException(), isNull);
      },
    );
  });


  group('Part F — no forbidden phrases in raw content module', () {
    test('no email-sign-up wording anywhere in kFaqEntries', () {
      final offenders = <String>[];
      final r = RegExp(
          r'sign\s+up\s+with\s+(?:an\s+|your\s+)?email',
          caseSensitive: false);
      for (final e in kFaqEntries) {
        if (r.hasMatch(e.answer)) offenders.add(e.id);
      }
      expect(offenders, isEmpty,
          reason: 'email-sign-up copy in: $offenders');
    });

    test('no answer says "Crypto Vault wallet records" as a normal '
        'secure item', () {
      final offenders = <String>[];
      for (final e in kFaqEntries) {
        if (e.answer.toLowerCase()
            .contains('crypto vault wallet records')) {
          offenders.add(e.id);
        }
      }
      expect(offenders, isEmpty,
          reason:
              'wallet-records-as-secure-items copy in: $offenders');
    });
  });
}
