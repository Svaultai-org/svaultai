
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/i18n/language_registry.dart';


void main() {


  group('language_registry — data hygiene', () {
    test('exactly 24 languages are declared', () {
      expect(kSupportedLanguages.length, 24);
    });

    test('all seven fully-localised codes exist in the registry', () {
      for (final code in kFullyLocalisedCodes) {
        final info = findLanguageByCode(code);
        expect(info, isNotNull,
            reason: 'expected registry entry for "$code"');
        expect(info!.fullyLocalised, isTrue,
            reason: '$code must be marked fullyLocalised');
      }
    });

    test('every language has non-empty native and English names', () {
      for (final info in kSupportedLanguages) {
        expect(info.nativeName.trim(), isNotEmpty,
            reason: '${info.code} needs native name');
        expect(info.englishName.trim(), isNotEmpty,
            reason: '${info.code} needs english name');
        expect(info.code.length, 2,
            reason: '${info.code} must be a 2-letter code');
      }
    });

    test('RTL flag is set for Arabic and Urdu, nowhere else', () {
      final rtl = kSupportedLanguages
          .where((info) => info.rtl)
          .map((info) => info.code)
          .toSet();
      expect(rtl, equals({'ar', 'ur'}));
    });

    test('no duplicate codes', () {
      final codes = kSupportedLanguages.map((i) => i.code).toList();
      expect(codes.length, codes.toSet().length,
          reason: 'each code must be unique');
    });

    test('findLanguageByCode is case- and region-insensitive', () {
      expect(findLanguageByCode('EN')?.code, 'en');
      expect(findLanguageByCode('en')?.code, 'en');
      expect(findLanguageByCode('en-US')?.code, 'en');
      expect(findLanguageByCode('pt-BR')?.code, 'pt');
      expect(findLanguageByCode(null), isNull);
      expect(findLanguageByCode(''), isNull);
      expect(findLanguageByCode('xx'), isNull);
    });

    test('isFullyLocalised only true for en/ar/es/fr/ja/ko/zh', () {
      for (final info in kSupportedLanguages) {
        final expected = kFullyLocalisedCodes.contains(info.code);
        expect(isFullyLocalised(info.code), expected,
            reason: '${info.code} fully-localised flag mismatch');
      }
    });

    test('isRtlLanguage matches only ar/ur', () {
      expect(isRtlLanguage('ar'), isTrue);
      expect(isRtlLanguage('ur'), isTrue);
      for (final code in const <String>[
        'en', 'fr', 'es', 'ja', 'ko', 'zh', 'pt', 'de', 'ru',
      ]) {
        expect(isRtlLanguage(code), isFalse,
            reason: '$code must not be RTL');
      }
    });
  });


  group('language search — selector filtering', () {
    test('empty query matches everyone', () {
      for (final info in kSupportedLanguages) {
        expect(info.matchesQuery(''), isTrue);
      }
    });

    test('search by English name is case-insensitive', () {
      final french = findLanguageByCode('fr')!;
      expect(french.matchesQuery('french'), isTrue);
      expect(french.matchesQuery('FRENCH'), isTrue);
      expect(french.matchesQuery('fren'), isTrue);
    });

    test('search by native name works', () {
      final arabic = findLanguageByCode('ar')!;
      expect(arabic.matchesQuery('العربية'), isTrue);
      final korean = findLanguageByCode('ko')!;
      expect(korean.matchesQuery('한국'), isTrue);
    });

    test('search by alias picks up common romanisations', () {
      final japanese = findLanguageByCode('ja')!;
      expect(japanese.matchesQuery('nihongo'), isTrue);
      final spanish = findLanguageByCode('es')!;
      expect(spanish.matchesQuery('castellano'), isTrue);
    });

    test('bogus query matches no language', () {
      for (final info in kSupportedLanguages) {
        expect(info.matchesQuery('zzzzzz-not-a-real-language'),
            isFalse);
      }
    });
  });


  group('AppLocalizations — 7 language ARBs', () {


    Future<AppLocalizations> _load(String code) async {
      final locale = Locale(code);
      return await AppLocalizations.delegate.load(locale);
    }

    test('English loads and exposes the new keys', () async {
      final l = await _load('en');
      expect(l.deleteVaultTitle, isNotEmpty);
      expect(l.deleteVaultBody, contains('permanent'));
      expect(l.helpCenterTitle, isNotEmpty);
      expect(l.helpCategorySecurity, 'Security');
      expect(l.errorRateLimited, isNotEmpty);
      expect(l.settingsLanguageSearchHint, isNotEmpty);
    });

    test('Korean loads and translates Settings/Help/Delete keys',
        () async {
      final l = await _load('ko');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.helpCenterTitle, isNot(equals('Help & FAQ')));
      expect(l.deleteVaultConfirmButton,
          isNot(equals('Delete vault')));
      expect(l.helpCategorySecurity, isNot(equals('Security')));
    });

    test('Arabic loads and translates Settings/Help/Delete keys',
        () async {
      final l = await _load('ar');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.deleteVaultTitle, isNot(equals('Delete vault permanently?')));

      expect(l.deleteVaultBody, contains('VaultAI'));
    });

    test('French loads and translates', () async {
      final l = await _load('fr');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.deleteVaultConfirmButton,
          isNot(equals('Delete vault')));
    });

    test('Spanish loads and translates', () async {
      final l = await _load('es');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.deleteVaultConfirmButton,
          isNot(equals('Delete vault')));
    });

    test('Japanese loads and translates', () async {
      final l = await _load('ja');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.deleteVaultConfirmButton,
          isNot(equals('Delete vault')));
    });

    test('Chinese loads and translates', () async {
      final l = await _load('zh');
      expect(l.settingsTitle, isNotEmpty);
      expect(l.settingsTitle, isNot(equals('Settings')));
      expect(l.deleteVaultConfirmButton,
          isNot(equals('Delete vault')));
    });

    test(
      'delete-vault crypto warning MUST NOT overpromise safety '
      'in any of the 7 languages',
      () async {
        const badWordsByLang = <String, List<String>>{
          'en': ['unhackable', 'impossible to attack', 'guaranteed'],
          'ar': ['غير قابل للاختراق'],
          'fr': ['impossible à pirater'],
          'es': ['imposible de atacar'],
          'ja': ['ハック不可能'],
          'ko': ['해킹 불가능'],
          'zh': ['无法攻击'],
        };
        for (final code in const [
          'en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh',
        ]) {
          final l = await _load(code);
          final answer = l.deleteVaultCryptoWarning;
          for (final bad in badWordsByLang[code] ?? const <String>[]) {
            expect(answer.contains(bad), isFalse,
                reason:
                    '$code deleteVaultCryptoWarning must not '
                    'contain "$bad"');
          }
        }
      },
    );

    test(
      'delete-vault body still mentions blockchain-asset caveat '
      'across languages',
      () async {

        expect(
          (await _load('en')).deleteVaultCryptoWarning
              .toLowerCase()
              .contains('blockchain'),
          isTrue,
        );
      },
    );
  });


  group(
    'RTL — Arabic renders without overflow at 360x800',
    () {
      testWidgets(
        'localised widget in ar mounts + Directionality is rtl',
        (tester) async {
          await tester.binding.setSurfaceSize(const Size(360, 800));
          addTearDown(() async {
            await tester.binding.setSurfaceSize(null);
          });
          await tester.pumpWidget(
            MaterialApp(
              locale: const Locale('ar'),
              supportedLocales: AppLocalizations.supportedLocales,
              localizationsDelegates: const [
                AppLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              home: Builder(builder: (context) {
                final l = AppLocalizations.of(context);
                return Scaffold(
                  body: SafeArea(
                    child: Column(
                      children: [
                        Text(l.settingsTitle),
                        Text(l.deleteVaultTitle),
                        Text(l.helpCenterTitle),
                      ],
                    ),
                  ),
                );
              }),
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);


          final direction =
              Directionality.of(tester.element(find.byType(Scaffold)));
          expect(direction, TextDirection.rtl);
        },
      );

      testWidgets(
        'English renders LTR at 360x800',
        (tester) async {
          await tester.binding.setSurfaceSize(const Size(360, 800));
          addTearDown(() async {
            await tester.binding.setSurfaceSize(null);
          });
          await tester.pumpWidget(
            MaterialApp(
              locale: const Locale('en'),
              supportedLocales: AppLocalizations.supportedLocales,
              localizationsDelegates: const [
                AppLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              home: Builder(builder: (context) {
                final l = AppLocalizations.of(context);
                return Scaffold(body: Text(l.settingsTitle));
              }),
            ),
          );
          await tester.pumpAndSettle();
          final direction =
              Directionality.of(tester.element(find.byType(Scaffold)));
          expect(direction, TextDirection.ltr);
        },
      );

      testWidgets(
        'Korean at 360x800 does not overflow with common labels',
        (tester) async {
          await tester.binding.setSurfaceSize(const Size(360, 800));
          addTearDown(() async {
            await tester.binding.setSurfaceSize(null);
          });
          await tester.pumpWidget(
            MaterialApp(
              locale: const Locale('ko'),
              supportedLocales: AppLocalizations.supportedLocales,
              localizationsDelegates: const [
                AppLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              home: Builder(builder: (context) {
                final l = AppLocalizations.of(context);
                return Scaffold(
                  body: Wrap(
                    children: [
                      Text(l.settingsTitle),
                      Text(l.helpCategorySecurity),
                      Text(l.helpCategoryTroubleshooting),
                      Text(l.deleteVaultConfirmButton),
                      Text(l.errorRateLimited),
                    ],
                  ),
                );
              }),
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
        },
      );
    },
  );


  group('ARB safety — no unwanted signup / pending-deletion / '
      'unhackable claims', () {
    Future<AppLocalizations> _load(String code) =>
        AppLocalizations.delegate.load(Locale(code));

    test('no help-shell strings contain "sign up with email"',
        () async {
      const bads = <String>['sign up with an email', 'sign up with email'];
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);
        for (final s in [
          l.helpCenterTitle, l.helpCenterSubtitle,
          l.helpCenterEmptyBody, l.helpCenterSupportNote,
          l.helpCenterPublicHint, l.helpCenterSignInToAsk,
        ]) {
          final lower = s.toLowerCase();
          for (final bad in bads) {
            expect(lower.contains(bad), isFalse,
                reason: 'Locale $code contained forbidden phrase "$bad" '
                    'in a help shell string');
          }
        }
      }
    });

    test('no delete-vault strings contain "pending deletion" or '
        '"grace period"', () async {
      const bads = <String>['pending deletion', 'grace period'];
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);
        for (final s in [
          l.deleteVaultTitle, l.deleteVaultBody,
          l.deleteVaultCryptoWarning,
          l.deleteVaultPhraseInstruction,
          l.deleteVaultPinInstruction,
        ]) {
          final lower = s.toLowerCase();
          for (final bad in bads) {
            expect(lower.contains(bad), isFalse,
                reason: 'Locale $code contained forbidden phrase "$bad" '
                    'in a delete-vault string');
          }
        }
      }
    });

    test('no strings claim VaultAI is impossible to attack', () async {
      const bads = <String>[
        'unhackable', 'impossible to hack', 'impossible to attack',
      ];
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);
        for (final s in [
          l.settingsSubtitle, l.deleteVaultBody,
          l.deleteVaultCryptoWarning,
          l.helpCenterSubtitle, l.helpCenterSupportNote,
        ]) {
          final lower = s.toLowerCase();
          for (final bad in bads) {
            expect(lower.contains(bad), isFalse,
                reason: 'Locale $code contained "$bad"');
          }
        }
      }
    });
  });
}
