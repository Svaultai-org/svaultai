
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';


AppState _freshAppState({String device = 'en'}) {
  AppState.deviceLanguageCodeResolver = () => device;
  return AppState();
}


Future<Locale> _resolveLocale(WidgetTester tester) async {
  final ctx = tester.element(find.byType(Placeholder));
  return Localizations.localeOf(ctx);
}


Future<Widget> _buildApp({
  required AppState app,
  Locale? deviceLocale,
}) async {

  return MaterialApp(
    locale: app.shellLocale,
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    supportedLocales: AppLocalizations.supportedLocales,
    localeListResolutionCallback: resolveShellLocale,
    home: const Placeholder(),
  );
}

void main() {
  setUp(() {
    NativeSecureStore.useSharedPreferencesForTesting = true;
    AppState.deviceLanguageCodeResolver = () => 'en';
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    AppState.deviceLanguageCodeResolver = () => 'en';
  });



  group('default is device-detected — never hardcoded Korean', () {
    testWidgets(
      'no stored preference + English device → shell resolves to English',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        tester.binding.platformDispatcher.localeTestValue =
            const Locale('en', 'US');
        tester.binding.platformDispatcher.localesTestValue =
            const <Locale>[Locale('en', 'US')];
        addTearDown(() {
          tester.binding.platformDispatcher.clearLocaleTestValue();
          tester.binding.platformDispatcher.clearLocalesTestValue();
        });

        final app = _freshAppState(device: 'en');
        await app.hydrate();

        expect(app.appLocale, isNull,
            reason: 'no manual selection was made');
        expect(app.shellLocale, isNull,
            reason: 'MaterialApp should defer to device detection when '
                'no manual selection exists');
        expect(app.effectiveLanguageCode, 'en',
            reason: 'English device → English effective locale');

        await tester.pumpWidget(await _buildApp(app: app));
        await tester.pumpAndSettle();
        final resolved = await _resolveLocale(tester);
        expect(resolved.languageCode, 'en');
      },
    );

    testWidgets(
      'no stored preference + French device → shell resolves to French, '
      'not Korean',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        tester.binding.platformDispatcher.localeTestValue =
            const Locale('fr', 'FR');
        tester.binding.platformDispatcher.localesTestValue =
            const <Locale>[Locale('fr', 'FR')];
        addTearDown(() {
          tester.binding.platformDispatcher.clearLocaleTestValue();
          tester.binding.platformDispatcher.clearLocalesTestValue();
        });

        final app = _freshAppState(device: 'fr');
        await app.hydrate();

        expect(app.appLocale, isNull);
        expect(app.effectiveLanguageCode, 'fr');

        await tester.pumpWidget(await _buildApp(app: app));
        await tester.pumpAndSettle();
        final resolved = await _resolveLocale(tester);
        expect(resolved.languageCode, 'fr',
            reason: "device-detected locale should win when the user "
                "hasn't manually chosen a language");
      },
    );

    testWidgets(
      'no stored preference + unsupported device (Zulu) → falls back to '
      'English',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        tester.binding.platformDispatcher.localeTestValue =
            const Locale('zu', 'ZA');
        tester.binding.platformDispatcher.localesTestValue =
            const <Locale>[Locale('zu', 'ZA')];
        addTearDown(() {
          tester.binding.platformDispatcher.clearLocaleTestValue();
          tester.binding.platformDispatcher.clearLocalesTestValue();
        });

        final app = _freshAppState(device: 'zu');
        await app.hydrate();

        expect(app.effectiveLanguageCode, 'en',
            reason: 'unsupported device locale must fall back to '
                'English, never Korean or any other example language');

        await tester.pumpWidget(await _buildApp(app: app));
        await tester.pumpAndSettle();
        final resolved = await _resolveLocale(tester);
        expect(resolved.languageCode, 'en');
      },
    );

    test(
      'AppState never hardcodes Korean as its default',
      () {
        AppState.deviceLanguageCodeResolver = () => 'en';
        final app = AppState();
        expect(app.appLocale, isNull);


        expect(app.effectiveLanguageCode, isNot(equals('ko')));
        expect(app.chatReplyLanguageCode, isNot(equals('ko')));
        expect(app.shellLocale?.languageCode, isNot(equals('ko')));
      },
    );
  });



  group('safe migration clears stale Korean from old test-era key', () {
    test(
      'v1 key with "ko" is CLEARED on load; effective locale falls back '
      'to device (not Korean)',
      () async {

        SharedPreferences.setMockInitialValues(<String, Object>{
          'app_locale': 'ko',
        });

        final app = _freshAppState(device: 'en');
        await app.hydrate();

        expect(app.appLocale, isNull,
            reason: 'v1 stale key must not be loaded — it was written '
                'by a pre-fix test session where Korean was picked '
                'only as an example');
        expect(app.effectiveLanguageCode, 'en',
            reason: 'device (English) wins after migration wipes the '
                'stale v1 preference');


        final sp = await SharedPreferences.getInstance();
        expect(sp.containsKey('app_locale'), isFalse,
            reason: 'v1 storage key must be removed to prevent it '
                'ever reasserting Korean');
      },
    );

    test(
      'v1 stale + French device → user gets French shell, not Korean',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{
          'app_locale': 'ko',
        });

        final app = _freshAppState(device: 'fr');
        await app.hydrate();

        expect(app.appLocale, isNull);
        expect(app.effectiveLanguageCode, 'fr',
            reason: 'the migration must not force ANY specific '
                'language — it must yield to device detection');
      },
    );

    test(
      'invalid v2 stored code (e.g. "xx") is cleared, effective falls '
      'back to device',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{
          'app_locale_v2': 'xx',
        });
        final app = _freshAppState(device: 'ja');
        await app.hydrate();
        expect(app.appLocale, isNull);
        expect(app.effectiveLanguageCode, 'ja');
        final sp = await SharedPreferences.getInstance();
        expect(sp.containsKey('app_locale_v2'), isFalse);
      },
    );
  });



  group('manual language persistence via v2 storage key', () {
    testWidgets(
      'manually selecting Korean persists it and updates the UI to '
      'Korean',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        tester.binding.platformDispatcher.localeTestValue =
            const Locale('en', 'US');
        tester.binding.platformDispatcher.localesTestValue =
            const <Locale>[Locale('en', 'US')];
        addTearDown(() {
          tester.binding.platformDispatcher.clearLocaleTestValue();
          tester.binding.platformDispatcher.clearLocalesTestValue();
        });

        final app = _freshAppState(device: 'en');
        await app.hydrate();

        await app.setAppLocale(const Locale('ko'));


        final sp = await SharedPreferences.getInstance();
        expect(sp.getString('app_locale_v2'), 'ko');
        expect(sp.containsKey('app_locale'), isFalse,
            reason: 'v1 key must never be written after the fix');

        expect(app.effectiveLanguageCode, 'ko');
        expect(app.chatReplyLanguageCode, 'ko');
        expect(app.shellLocale?.languageCode, 'ko');
      },
    );

    testWidgets(
      'manually selecting Arabic persists it and marks the shell RTL',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        tester.binding.platformDispatcher.localeTestValue =
            const Locale('en', 'US');
        tester.binding.platformDispatcher.localesTestValue =
            const <Locale>[Locale('en', 'US')];
        addTearDown(() {
          tester.binding.platformDispatcher.clearLocaleTestValue();
          tester.binding.platformDispatcher.clearLocalesTestValue();
        });

        final app = _freshAppState(device: 'en');
        await app.hydrate();
        await app.setAppLocale(const Locale('ar'));

        expect(app.effectiveLanguageCode, 'ar');
        expect(app.shellLocale?.languageCode, 'ar');

        await tester.pumpWidget(
          MaterialApp(
            locale: app.shellLocale,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            supportedLocales: AppLocalizations.supportedLocales,
            home: Builder(
              builder: (ctx) {
                final l = AppLocalizations.of(ctx);
                return Directionality(
                  key: const Key('probe'),
                  textDirection: Directionality.of(ctx),
                  child: Text(l.commonCancel),
                );
              },
            ),
          ),
        );
        await tester.pumpAndSettle();

        final probe = tester.widget<Directionality>(find.byKey(
            const Key('probe')));
        expect(probe.textDirection, TextDirection.rtl,
            reason: 'Arabic must render RTL');
      },
    );

    test(
      'setAppLocale(null) resets to auto-detect and removes v2 key',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{
          'app_locale_v2': 'ko',
        });
        final app = _freshAppState(device: 'en');
        await app.hydrate();
        expect(app.appLocale?.languageCode, 'ko',
            reason: 'v2 preserved Korean if manually selected earlier');

        await app.setAppLocale(null);

        expect(app.appLocale, isNull);
        expect(app.effectiveLanguageCode, 'en');
        final sp = await SharedPreferences.getInstance();
        expect(sp.containsKey('app_locale_v2'), isFalse);
      },
    );

    test(
      'setAppLocale(unsupported code) is rejected silently — never '
      'persists garbage',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();

        await app.setAppLocale(const Locale('xx'));

        expect(app.appLocale, isNull);
        final sp = await SharedPreferences.getInstance();
        expect(sp.containsKey('app_locale_v2'), isFalse);
      },
    );
  });



  group('switching language propagates to the entire UI', () {
    testWidgets(
      'switching Settings dropdown from English to Korean rebuilds the '
      'MaterialApp locale',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();

        Widget build() => MaterialApp(
              locale: app.shellLocale,
              localizationsDelegates: const [
                AppLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              supportedLocales: AppLocalizations.supportedLocales,
              home: Builder(
                builder: (ctx) => Text(
                  AppLocalizations.of(ctx).commonCancel,
                  key: const Key('cancel_label'),
                ),
              ),
            );

        await tester.pumpWidget(build());
        await tester.pumpAndSettle();
        final englishLabel = tester
            .widget<Text>(find.byKey(const Key('cancel_label'))).data!;
        expect(englishLabel.toLowerCase(), contains('cancel'),
            reason: 'default English UI shows English cancel button');

        await app.setAppLocale(const Locale('ko'));
        await tester.pumpWidget(build());
        await tester.pumpAndSettle();
        final koreanLabel = tester
            .widget<Text>(find.byKey(const Key('cancel_label'))).data!;

        expect(koreanLabel, isNot(equals(englishLabel)),
            reason: "switching to Korean must actually change the "
                "rendered label — no mixed-language screens");
      },
    );

    testWidgets(
      'switching from Korean → French → Japanese updates every surface',
      (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();

        Widget build() => MaterialApp(
              locale: app.shellLocale,
              localizationsDelegates: const [
                AppLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              supportedLocales: AppLocalizations.supportedLocales,
              home: Builder(
                builder: (ctx) {
                  final l = AppLocalizations.of(ctx);
                  return Column(
                    children: [
                      Text(l.commonCancel, key: const Key('cancel')),
                      Text(l.commonRefresh, key: const Key('refresh')),
                      Text(l.settingsLanguage, key: const Key('lang')),
                    ],
                  );
                },
              ),
            );

        final observed = <String, String>{};
        for (final code in const <String>['ko', 'fr', 'ja']) {
          await app.setAppLocale(Locale(code));
          await tester.pumpWidget(build());
          await tester.pumpAndSettle();
          observed['${code}_cancel'] = tester
              .widget<Text>(find.byKey(const Key('cancel'))).data!;
          observed['${code}_refresh'] = tester
              .widget<Text>(find.byKey(const Key('refresh'))).data!;
          observed['${code}_lang'] = tester
              .widget<Text>(find.byKey(const Key('lang'))).data!;
        }


        expect(observed['ko_cancel'], isNot(observed['fr_cancel']));
        expect(observed['fr_cancel'], isNot(observed['ja_cancel']));
        expect(observed['ko_lang'], isNot(observed['fr_lang']));
        expect(observed['fr_lang'], isNot(observed['ja_lang']));
      },
    );
  });



  group('chat reply language hint mirrors effective locale', () {
    test(
      'chatReplyLanguageCode returns effective locale, never null',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();
        expect(app.chatReplyLanguageCode, isNotNull);
        expect(app.chatReplyLanguageCode.isNotEmpty, isTrue);
        expect(app.chatReplyLanguageCode, 'en',
            reason: 'no manual + English device → English hint');
      },
    );

    test(
      'manual Korean → chat hint is "ko" so the router can bias reply '
      'to Korean when the message is language-ambiguous',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();
        await app.setAppLocale(const Locale('ko'));
        expect(app.chatReplyLanguageCode, 'ko');
      },
    );

    test(
      'manual Arabic → chat hint is "ar"',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'en');
        await app.hydrate();
        await app.setAppLocale(const Locale('ar'));
        expect(app.chatReplyLanguageCode, 'ar');
      },
    );

    test(
      'no manual + Japanese device → chat hint is "ja"',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'ja');
        await app.hydrate();
        expect(app.appLocale, isNull);
        expect(app.chatReplyLanguageCode, 'ja',
            reason: 'device-detected supported locale becomes the '
                'chat hint so FAQ + AI replies are in the same language '
                'as the shell');
      },
    );

    test(
      'no manual + unsupported device → chat hint is "en"',
      () async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final app = _freshAppState(device: 'zu');
        await app.hydrate();
        expect(app.chatReplyLanguageCode, 'en');
      },
    );
  });



  group('no untranslated fallback text on any fully-localised surface',
      () {
    const fullyLocalised = <String>['en', 'ar', 'fr', 'es', 'ja', 'ko',
        'zh'];



    final englishGetterProbes = <String, String Function(AppLocalizations)>{
      'commonCancel':          (l) => l.commonCancel,
      'commonRefresh':         (l) => l.commonRefresh,
      'commonDownload':        (l) => l.commonDownload,
      'commonOpen':            (l) => l.commonOpen,
      'landingHowItWorks':     (l) => l.landingHowItWorks,
      'authDontHaveVault':     (l) => l.authDontHaveVault,
      'authAlreadyHaveVault':  (l) => l.authAlreadyHaveVault,
      'notificationsTitle':    (l) => l.notificationsTitle,
      'settingsLanguage':      (l) => l.settingsLanguage,
    };

    for (final code in fullyLocalised) {
      test('$code — every visible key is non-empty and non-null',
          () async {
        final l =
            await AppLocalizations.delegate.load(Locale(code));
        for (final entry in englishGetterProbes.entries) {
          final v = entry.value(l);
          expect(v, isNotNull,
              reason: '$code ${entry.key} must not be null');
          expect(v.trim(), isNotEmpty,
              reason: '$code ${entry.key} must not be empty');
        }
      });
    }

    test(
      'Korean and Arabic labels differ from English for representative '
      'keys — no English fallback bleeding through',
      () async {
        final en =
            await AppLocalizations.delegate.load(const Locale('en'));
        final ko =
            await AppLocalizations.delegate.load(const Locale('ko'));
        final ar =
            await AppLocalizations.delegate.load(const Locale('ar'));

        final probes = <String, String Function(AppLocalizations)>{
          'commonCancel':          (l) => l.commonCancel,
          'commonDownload':        (l) => l.commonDownload,
          'landingHowItWorks':     (l) => l.landingHowItWorks,
          'authDontHaveVault':     (l) => l.authDontHaveVault,
          'settingsLanguage':      (l) => l.settingsLanguage,
        };

        for (final entry in probes.entries) {
          expect(entry.value(ko), isNot(equals(entry.value(en))),
              reason: 'Korean ${entry.key} must not be the English '
                  'string (would signal a missing translation and a '
                  'mixed-language screen)');
          expect(entry.value(ar), isNot(equals(entry.value(en))),
              reason: 'Arabic ${entry.key} must not be the English '
                  'string');
        }
      },
    );
  });
}
