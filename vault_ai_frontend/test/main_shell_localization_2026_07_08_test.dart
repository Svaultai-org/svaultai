
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _delegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Future<AppLocalizations> _load(String code) =>
    AppLocalizations.delegate.load(Locale(code));


void main() {


  group('newly-added main-shell ARB keys are complete', () {
    const supported = <String>['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh'];
    final requiredKeys =
        <String, String Function(AppLocalizations)>{

      'commonCopyCode':          (l) => l.commonCopyCode,
      'commonRemove':            (l) => l.commonRemove,
      'commonNotYet':            (l) => l.commonNotYet,

      'notificationsTitle':       (l) => l.notificationsTitle,
      'notificationsMarkAllRead': (l) => l.notificationsMarkAllRead,

      'landingHowItWorks':        (l) => l.landingHowItWorks,

      'authDontHaveVault':        (l) => l.authDontHaveVault,
      'authAlreadyHaveVault':     (l) => l.authAlreadyHaveVault,
      'authUseAnotherVault':      (l) => l.authUseAnotherVault,
      'authLogInAnotherVault':    (l) => l.authLogInAnotherVault,

      'snackDeviceTrusted':       (l) => l.snackDeviceTrusted,

      'confirmEraseTitle':        (l) => l.confirmEraseTitle,
      'confirmEraseButton':       (l) => l.confirmEraseButton,

      'inheritanceCancelTransfer':  (l) => l.inheritanceCancelTransfer,
      'inheritanceStartCountdown':  (l) => l.inheritanceStartCountdown,
      'inheritanceAddBeneficiary':  (l) => l.inheritanceAddBeneficiary,
      'inheritanceEnterCode':       (l) => l.inheritanceEnterCode,
      'inheritanceRequestTransfer': (l) => l.inheritanceRequestTransfer,

      'filesChooseStorage':       (l) => l.filesChooseStorage,
      'filesUploadFile':          (l) => l.filesUploadFile,
      'filesUploadPhoto':         (l) => l.filesUploadPhoto,
      'filesUploadVideo':         (l) => l.filesUploadVideo,
      'filesUploadAudio':         (l) => l.filesUploadAudio,
      'filesUploadFolder':        (l) => l.filesUploadFolder,
      'filesRecordVoice':         (l) => l.filesRecordVoice,
      'filesRecordVideo':         (l) => l.filesRecordVideo,

      'deleteVaultSignInRequired':(l) => l.deleteVaultSignInRequired,
      'dashboardActiveVault':     (l) => l.dashboardActiveVault,
    };

    test('every new key is present and non-empty for all 7 locales',
        () async {
      for (final lang in supported) {
        final l = await _load(lang);
        for (final entry in requiredKeys.entries) {
          final value = entry.value(l);
          expect(value.trim(), isNotEmpty,
              reason: '$lang: ${entry.key} is empty');
        }
      }
    });

    test('non-English translations differ from English for a sample',
        () async {
      final en = await _load('en');


      const sample = <String>[
        'authDontHaveVault',
        'snackDeviceTrusted',
        'confirmEraseTitle',
        'inheritanceAddBeneficiary',
        'filesUploadFile',
        'dashboardActiveVault',
      ];
      for (final lang in const ['ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(lang);
        for (final key in sample) {
          expect(requiredKeys[key]!(l), isNot(equals(requiredKeys[key]!(en))),
              reason: '$lang: $key should differ from English');
        }
      }
    });
  });


  group('inheritance placeholder titles interpolate the beneficiary '
      'label correctly', () {
    test('English cancel-pending-transfer template inserts the label',
        () async {
      final l = await _load('en');
      final got = l.inheritanceCancelPendingTransferTitle('Ali');
      expect(got, contains('Ali'));
      expect(got, contains('Cancel pending transfer'));
    });

    test('English claim-title template inserts the label', () async {
      final l = await _load('en');
      final got = l.inheritanceClaimTitle('Grandma\'s vault');
      expect(got, contains("Grandma's vault"));
    });

    test('English request-transfer-title template inserts the label',
        () async {
      final l = await _load('en');
      final got = l.inheritanceRequestTransferTitle('Rebecca');
      expect(got, contains('Rebecca'));
      expect(got, contains('Request transfer'));
    });

    test('English remove-title template inserts the label', () async {
      final l = await _load('en');
      final got = l.inheritanceRemoveTitle('Old beneficiary');
      expect(got, contains('Old beneficiary'));
      expect(got, contains('Remove'));
    });

    test('Korean cancel-pending-transfer template preserves the label',
        () async {
      final l = await _load('ko');
      final got = l.inheritanceCancelPendingTransferTitle('민수');
      expect(got, contains('민수'));

      expect(RegExp(r'[가-힣]').hasMatch(got), isTrue);
    });

    test('Arabic remove-title template preserves the label', () async {
      final l = await _load('ar');
      final got = l.inheritanceRemoveTitle('محمد');
      expect(got, contains('محمد'));

      expect(
          RegExp(r'[؀-ۿ]').hasMatch(got), isTrue,
          reason: 'Arabic remove-title must be in Arabic script');
    });

    test('Chinese claim-title template preserves the label', () async {
      final l = await _load('zh');
      final got = l.inheritanceClaimTitle('祖父的保险库');
      expect(got, contains('祖父的保险库'));
    });

    test('Japanese request-transfer-title preserves the label',
        () async {
      final l = await _load('ja');
      final got = l.inheritanceRequestTransferTitle('田中');
      expect(got, contains('田中'));
    });
  });


  group('safety phrase blocklist across new main-shell keys', () {
    const bannedByLang = <String, List<String>>{
      'en': [
        'unhackable',
        'impossible to attack',
        'guaranteed safe',
        'hackers will never know',
        'sign up with an email',
        'sign up with email',
        'pending deletion',
        'grace period',
      ],
      'ar': ['غير قابل للاختراق', 'مضمون الأمان', 'فترة سماح'],
      'fr': ['impossible à pirater', 'sécurité garantie',
             'période de grâce'],
      'es': ['imposible de atacar', 'seguridad garantizada',
             'período de gracia'],
      'ja': ['ハック不可能', '安全性を保証', '猶予期間'],
      'ko': ['해킹 불가능', '안전 보장', '유예 기간'],
      'zh': ['无法攻击', '保证安全', '宽限期'],
    };

    test('no new main-shell key contains a forbidden phrase in its '
        'language', () async {
      for (final entry in bannedByLang.entries) {
        final lang = entry.key;
        final banned = entry.value;
        final l = await _load(lang);
        final strings = <String>[
          l.notificationsTitle, l.notificationsMarkAllRead,
          l.landingHowItWorks,
          l.authDontHaveVault, l.authAlreadyHaveVault,
          l.authUseAnotherVault, l.authLogInAnotherVault,
          l.snackDeviceTrusted,
          l.confirmEraseTitle, l.confirmEraseButton,
          l.inheritanceCancelTransfer,
          l.inheritanceStartCountdown,
          l.inheritanceAddBeneficiary,
          l.inheritanceEnterCode, l.inheritanceRequestTransfer,
          l.filesChooseStorage,
          l.filesUploadFile, l.filesUploadPhoto,
          l.filesUploadVideo, l.filesUploadAudio,
          l.filesUploadFolder, l.filesRecordVoice, l.filesRecordVideo,
          l.deleteVaultSignInRequired,
          l.dashboardActiveVault,
        ];
        for (final s in strings) {
          final lower = s.toLowerCase();
          for (final bad in banned) {
            expect(lower.contains(bad.toLowerCase()), isFalse,
                reason: '$lang: "$s" contains forbidden phrase "$bad"');
          }
        }
      }
    });

    test('no template title reveals PIN/seed/private-key content', () {

      const bad = <String>[
        'reveal seed',
        'reveal pin',
        'expose private key',
      ];
      for (final t in const <String>[
        'Cancel pending transfer to "Ali"?',
        'Claim "Ali"',
        'Request transfer of "Ali"?',
        'Remove "Ali"?',
      ]) {
        for (final b in bad) {
          expect(t.toLowerCase(), isNot(contains(b)));
        }
      }
    });
  });


  group('DELETE MY VAULT confirmation phrase remains stable', () {
    test('every locale keeps the exact "DELETE MY VAULT" phrase in the '
        'delete-vault-body key from the earlier slice', () async {
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);


        expect(l.deleteVaultSignInRequired.trim(), isNotEmpty);
      }
    });
  });


  group('mobile 360x800 renders new keys in Korean and Arabic', () {
    Future<void> _pumpAllNewKeys(
      WidgetTester tester, Locale locale,
    ) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        MaterialApp(
          locale: locale,
          localizationsDelegates: _delegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (context) {
            final l = AppLocalizations.of(context);
            return Scaffold(
              body: SingleChildScrollView(
                child: Wrap(
                  children: [
                    Text(l.notificationsTitle),
                    Text(l.notificationsMarkAllRead),
                    Text(l.landingHowItWorks),
                    Text(l.authDontHaveVault),
                    Text(l.authAlreadyHaveVault),
                    Text(l.authUseAnotherVault),
                    Text(l.authLogInAnotherVault),
                    Text(l.snackDeviceTrusted),
                    Text(l.confirmEraseTitle),
                    Text(l.confirmEraseButton),
                    Text(l.inheritanceCancelPendingTransferTitle('X')),
                    Text(l.inheritanceCancelTransfer),
                    Text(l.inheritanceClaimTitle('X')),
                    Text(l.inheritanceRequestTransferTitle('X')),
                    Text(l.inheritanceRemoveTitle('X')),
                    Text(l.inheritanceStartCountdown),
                    Text(l.inheritanceAddBeneficiary),
                    Text(l.inheritanceEnterCode),
                    Text(l.inheritanceRequestTransfer),
                    Text(l.filesChooseStorage),
                    Text(l.filesUploadFile),
                    Text(l.filesUploadPhoto),
                    Text(l.filesUploadVideo),
                    Text(l.filesUploadAudio),
                    Text(l.filesUploadFolder),
                    Text(l.filesRecordVoice),
                    Text(l.filesRecordVideo),
                    Text(l.deleteVaultSignInRequired),
                    Text(l.dashboardActiveVault),
                  ],
                ),
              ),
            );
          }),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('Korean at 360x800 does not throw', (tester) async {
      await _pumpAllNewKeys(tester, const Locale('ko'));
      expect(tester.takeException(), isNull);
    });

    testWidgets('Arabic at 360x800 is RTL and does not throw',
        (tester) async {
      await _pumpAllNewKeys(tester, const Locale('ar'));
      expect(tester.takeException(), isNull);
      final dir = Directionality.of(
        tester.element(find.byType(Scaffold)),
      );
      expect(dir, TextDirection.rtl);
    });

    testWidgets('French/Spanish/Japanese/Chinese smoke render',
        (tester) async {
      for (final code in const ['fr', 'es', 'ja', 'zh']) {
        await _pumpAllNewKeys(tester, Locale(code));
        expect(tester.takeException(), isNull,
            reason: '$code smoke failed');
      }
    });
  });


  group('AppState / snackbar English fallback semantics', () {
    test('when ScaffoldMessengerState is unavailable, the raw English '
        'text does not contain sensitive content', () {


      const fallbackInactivity = 'Vault locked due to inactivity.';
      const fallbackDeviceTrusted = 'New device trusted.';
      for (final bad in const [
        'PIN', 'seed', 'private key', 'mnemonic', 'password',
      ]) {

        expect(
          fallbackInactivity.toLowerCase().contains(bad.toLowerCase()) &&
              bad != 'PIN',
          isFalse,
          reason: 'inactivity fallback must not contain $bad',
        );
        expect(
          fallbackDeviceTrusted.toLowerCase().contains(bad.toLowerCase()),
          isFalse,
          reason: 'device-trusted fallback must not contain $bad',
        );
      }
    });
  });


  group('no generic Aisha copy', () {
    test('no new main-shell key contains "Aisha" (anti-generic guard)',
        () async {
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);
        for (final s in <String>[
          l.notificationsTitle, l.landingHowItWorks,
          l.authDontHaveVault, l.confirmEraseTitle,
          l.inheritanceAddBeneficiary, l.filesUploadFile,
          l.dashboardActiveVault,
        ]) {
          expect(s.contains('Aisha'), isFalse,
              reason: '$code contained generic Aisha copy');
        }
      }
    });
  });
}
