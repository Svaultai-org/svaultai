
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_content_i18n.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Future<void> _pumpHelpCenter(
  WidgetTester tester,
  Locale locale, {
  Size size = const Size(1400, 1200),
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      locale: locale,
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const Scaffold(
        body: HelpCenterPage(mode: HelpCenterMode.signedIn),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {


  group('help_center_content_i18n — data hygiene', () {
    test('every canonical FAQ id has a localized entry in every '
        'supported locale', () {
      const supported = <String>[
        'en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh',
      ];
      final canonicalIds = kFaqEntries.map((e) => e.id).toSet();
      expect(canonicalIds.length, 66,
          reason: 'expected 66 canonical FAQ entries');
      for (final loc in supported) {
        final table = kFaqTranslations[loc];
        expect(table, isNotNull,
            reason: 'no i18n table for $loc');
        for (final id in canonicalIds) {
          final entry = table![id];
          expect(entry, isNotNull,
              reason: 'missing $loc translation for $id');
          expect(entry!.question.trim(), isNotEmpty,
              reason: '$loc $id empty question');
          expect(entry.answer.trim(), isNotEmpty,
              reason: '$loc $id empty answer');
        }
      }
    });

    test('localizedFaqEntry falls back to English for unknown locale',
        () {
      final english = kFaqTranslations['en']!['delete-my-vault']!;
      final got = localizedFaqEntry('delete-my-vault', 'pt');
      expect(got, isNotNull);
      expect(got!.answer, equals(english.answer),
          reason:
              'Portuguese has no translation yet; must fall back to '
              'English canonical answer');
    });

    test('localizedFaqEntry returns null for unknown id', () {
      expect(localizedFaqEntry('this-id-does-not-exist', 'en'), isNull);
    });

    test('every localized delete-my-vault answer keeps the exact '
        'DELETE MY VAULT phrase', () {
      const supported = <String>[
        'en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh',
      ];
      for (final loc in supported) {
        final entry = kFaqTranslations[loc]!['delete-my-vault']!;
        expect(
          entry.answer.contains('DELETE MY VAULT'), isTrue,
          reason:
              '$loc: delete-my-vault answer must contain literal '
              '"DELETE MY VAULT"',
        );
      }
    });
  });


  group('safety phrases — every locale', () {
    const unsafeByLang = <String, List<String>>{
      'en': [
        'unhackable', 'impossible to attack', 'guaranteed safe',
        'hackers will never know', 'sign up with an email',
        'sign up with email', 'pending deletion', 'grace period',
        'crypto will be recovered',
      ],
      'ar': [
        'غير قابل للاختراق', 'مستحيل الاختراق',
        'مضمون الأمان', 'الحذف المعلق', 'فترة سماح',
      ],
      'fr': [
        'impossible à pirater', 'sécurité garantie',
        'suppression en attente', 'période de grâce',
      ],
      'es': [
        'imposible de atacar', 'seguridad garantizada',
        'eliminación pendiente', 'período de gracia',
      ],
      'ja': [
        'ハック不可能', '安全性を保証', '削除保留中', '猶予期間',
      ],
      'ko': [
        '해킹 불가능', '안전 보장', '삭제 대기', '유예 기간',
      ],
      'zh': [
        '无法攻击', '保证安全', '待删除', '宽限期',
      ],
    };
    test('no localized entry contains a forbidden phrase for its language',
        () {
      for (final entry in unsafeByLang.entries) {
        final lang = entry.key;
        final phrases = entry.value;
        final table = kFaqTranslations[lang]!;
        for (final faq in table.entries) {
          final text = '${faq.value.question} ${faq.value.answer}'
              .toLowerCase();
          for (final bad in phrases) {
            expect(text.contains(bad.toLowerCase()), isFalse,
                reason:
                    'Locale $lang FAQ ${faq.key} contains forbidden '
                    'phrase "$bad"');
          }
        }
      }
    });
  });


  group('localizedFaqEntriesMatchingQuery', () {

    test('empty query returns all entries in the given locale', () {
      final all = localizedFaqEntriesMatchingQuery('ko', '');
      expect(all.length, 66);

      final delete = all.firstWhere(
        (e) => e.id == 'delete-my-vault',
      );
      expect(delete.answer.contains('DELETE MY VAULT'), isTrue);
    });

    test('search matches Korean question text', () {
      final results = localizedFaqEntriesMatchingQuery('ko', '삭제');
      expect(results, isNotEmpty,
          reason: 'Korean search for "삭제" (delete) must find results');
      expect(
        results.any((e) => e.id == 'delete-my-vault'),
        isTrue,
      );
    });

    test('search matches Arabic answer text', () {
      final results = localizedFaqEntriesMatchingQuery('ar', 'خزينتي');
      expect(results, isNotEmpty,
          reason: 'Arabic search for "خزينتي" must find results');
    });

    test('search matches Japanese answer text', () {
      final results = localizedFaqEntriesMatchingQuery('ja', '削除');
      expect(results, isNotEmpty);
      expect(
        results.any((e) => e.id == 'delete-my-vault'),
        isTrue,
      );
    });

    test('search matches Chinese question text', () {
      final results = localizedFaqEntriesMatchingQuery('zh', '删除');
      expect(results, isNotEmpty);
      expect(
        results.any((e) => e.id == 'delete-my-vault'),
        isTrue,
      );
    });

    test('unknown locale search falls back to English matches', () {
      final results = localizedFaqEntriesMatchingQuery(
        'pt', 'delete',
      );
      expect(results, isNotEmpty);
      expect(
        results.any((e) => e.id == 'delete-my-vault'),
        isTrue,
      );
    });
  });


  group('localizedFaqCategoryLabelFor', () {
    test('Korean category labels resolve to Korean text', () {
      expect(
        localizedFaqCategoryLabelFor('security', 'ko'),
        '보안',
      );
      expect(
        localizedFaqCategoryLabelFor('crypto', 'ko'),
        'Crypto Vault',
      );
    });
    test('Arabic category labels resolve to Arabic text', () {
      expect(
        localizedFaqCategoryLabelFor('security', 'ar'),
        'الأمان',
      );
    });
    test('unknown locale falls back to English', () {
      expect(
        localizedFaqCategoryLabelFor('security', 'pt'),
        'Security',
      );
    });
  });


  group('Help Center page renders localized FAQ', () {
    testWidgets(
      'Korean shell renders Korean FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('ko'));
        expect(find.text('SVaultAI가 뭐야?'), findsOneWidget);


        expect(find.text('보관소를 어떻게 삭제해?'), findsOneWidget);
      },
    );

    testWidgets(
      'Arabic shell renders Arabic FAQ questions and RTL',
      (tester) async {
        await _pumpHelpCenter(
          tester, const Locale('ar'), size: const Size(360, 900),
        );

        final direction = Directionality.of(
          tester.element(find.byType(HelpCenterPage)),
        );
        expect(direction, TextDirection.rtl);

        expect(find.text('ما هو SVaultAI؟'), findsOneWidget);
        expect(find.text('كيف أحذف خزينتي؟'), findsOneWidget);
      },
    );

    testWidgets(
      'French shell renders French FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('fr'));
        expect(find.text("Qu'est-ce que SVaultAI ?"), findsOneWidget);
        expect(
          find.text('Comment supprimer mon coffre ?'), findsOneWidget,
        );
      },
    );

    testWidgets(
      'Spanish shell renders Spanish FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('es'));
        expect(find.text('¿Qué es SVaultAI?'), findsOneWidget);
        expect(find.text('¿Cómo elimino mi bóveda?'), findsOneWidget);
      },
    );

    testWidgets(
      'Japanese shell renders Japanese FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('ja'));
        expect(find.text('SVaultAI とは?'), findsOneWidget);
        expect(
          find.text('保管庫はどうやって削除しますか?'), findsOneWidget,
        );
      },
    );

    testWidgets(
      'Chinese shell renders Chinese FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('zh'));
        expect(find.text('SVaultAI 是什么?'), findsOneWidget);
        expect(find.text('如何删除我的保险库?'), findsOneWidget);
      },
    );

    testWidgets(
      'English shell keeps English FAQ questions',
      (tester) async {
        await _pumpHelpCenter(tester, const Locale('en'));
        expect(find.text('What is SVaultAI?'), findsOneWidget);
      },
    );
  });


  group('Mobile 360x800 no overflow with localized FAQ', () {
    for (final entry in const <MapEntry<String, Locale>>[
      MapEntry('Korean', Locale('ko')),
      MapEntry('Arabic', Locale('ar')),
    ]) {
      testWidgets(
        '${entry.key} at 360x800 does not throw exceptions',
        (tester) async {
          await _pumpHelpCenter(
            tester, entry.value, size: const Size(360, 800),
          );
          expect(tester.takeException(), isNull);
        },
      );
    }
  });
}
