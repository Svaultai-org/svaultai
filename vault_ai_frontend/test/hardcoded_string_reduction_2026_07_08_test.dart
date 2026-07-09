
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


  group('newly-added ARB keys are present and non-empty', () {
    const supportedLangs = <String>[
      'en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh',
    ];

    final requiredKeys = <String, String Function(AppLocalizations)>{
      'commonContinue':  (l) => l.commonContinue,
      'commonApprove':   (l) => l.commonApprove,
      'commonReject':    (l) => l.commonReject,
      'commonRevoke':    (l) => l.commonRevoke,
      'commonReceive':   (l) => l.commonReceive,
      'commonReview':    (l) => l.commonReview,
      'commonAnalyze':   (l) => l.commonAnalyze,
      'commonCopy':      (l) => l.commonCopy,
      'commonEdit':      (l) => l.commonEdit,
      'commonCurrent':   (l) => l.commonCurrent,


      'storagePageTitle':         (l) => l.storagePageTitle,
      'storageNoDataAvailable':   (l) => l.storageNoDataAvailable,
      'storageUsageHeading':      (l) => l.storageUsageHeading,
      'storageAccountHeading':    (l) => l.storageAccountHeading,
      'storageFreeTier':          (l) => l.storageFreeTier,
      'storageNeedMoreSpace':     (l) => l.storageNeedMoreSpace,
      'storageGrandfathered':     (l) => l.storageGrandfathered,
      'storageAdditionalPricing': (l) => l.storageAdditionalPricing,
      'storagePlanLower':         (l) => l.storagePlanLower,
      'storageCouldNotLoad':      (l) => l.storageCouldNotLoad,
      'storageRefreshNow':        (l) => l.storageRefreshNow,


      'securityManageDevices':    (l) => l.securityManageDevices,
      'securityAnalyzePasswordsTitle':
          (l) => l.securityAnalyzePasswordsTitle,
      'securityEnterVaultPin':    (l) => l.securityEnterVaultPin,
      'securityAnalyzeButton':    (l) => l.securityAnalyzeButton,
      'securityAnalyzeMore':      (l) => l.securityAnalyzeMore,


      'devicePendingRequestSelfApproval':
          (l) => l.devicePendingRequestSelfApproval,
      'devicePendingFinalize':    (l) => l.devicePendingFinalize,
      'devicePendingCancelApproval':
          (l) => l.devicePendingCancelApproval,
      'devicePendingCheckAgain':  (l) => l.devicePendingCheckAgain,
      'devicePendingRegisterDevice':
          (l) => l.devicePendingRegisterDevice,
      'devicePendingDiagnoseTrust':
          (l) => l.devicePendingDiagnoseTrust,
      'devicePendingCopyDiagnostics':
          (l) => l.devicePendingCopyDiagnostics,
      'devicePendingDiagnosticsCopied':
          (l) => l.devicePendingDiagnosticsCopied,


      'cryptoLiteCouldNotLoadRecord':
          (l) => l.cryptoLiteCouldNotLoadRecord,
      'cryptoLiteAddressFormatMismatchTitle':
          (l) => l.cryptoLiteAddressFormatMismatchTitle,
      'cryptoLiteSaveAnyway':     (l) => l.cryptoLiteSaveAnyway,
      'cryptoLiteEditMetadata':   (l) => l.cryptoLiteEditMetadata,
      'cryptoLiteEditBackupMetadata':
          (l) => l.cryptoLiteEditBackupMetadata,
      'cryptoOpenAsset':          (l) => l.cryptoOpenAsset,
      'cryptoMoneroScannerStatus': (l) => l.cryptoMoneroScannerStatus,
      'cryptoOpenMonero':         (l) => l.cryptoOpenMonero,
      'cryptoSendDraftHeading':   (l) => l.cryptoSendDraftHeading,
      'cryptoOpenSendFlow':       (l) => l.cryptoOpenSendFlow,
      'cryptoRetryFailed':        (l) => l.cryptoRetryFailed,
      'cryptoOpenCryptoVault':    (l) => l.cryptoOpenCryptoVault,
      'cryptoCopyAddress':        (l) => l.cryptoCopyAddress,
      'cryptoTransactionsTab':    (l) => l.cryptoTransactionsTab,
      'cryptoContinueToPin':      (l) => l.cryptoContinueToPin,
      'cryptoCopyDestination':    (l) => l.cryptoCopyDestination,
      'cryptoSignatureCopied':    (l) => l.cryptoSignatureCopied,
      'cryptoCopySignature':      (l) => l.cryptoCopySignature,
      'cryptoTxIdCopied':         (l) => l.cryptoTxIdCopied,
      'cryptoCopyTxId':           (l) => l.cryptoCopyTxId,


      'vaultCardOverview':        (l) => l.vaultCardOverview,
      'vaultCardOpenVault':       (l) => l.vaultCardOpenVault,
      'vaultCardDocumentSummary': (l) => l.vaultCardDocumentSummary,
      'vaultCardGeneratedLogins': (l) => l.vaultCardGeneratedLogins,
      'vaultCardBilling':         (l) => l.vaultCardBilling,
      'vaultCardBrowseAllHelp':   (l) => l.vaultCardBrowseAllHelp,


      'secureItemCopyUsername':   (l) => l.secureItemCopyUsername,
      'secureItemCopyValue':      (l) => l.secureItemCopyValue,
    };

    test('every new ARB key exists and is non-empty for all 7 locales',
        () async {
      for (final lang in supportedLangs) {
        final l = await _load(lang);
        for (final entry in requiredKeys.entries) {
          final value = entry.value(l);
          expect(value.trim(), isNotEmpty,
              reason: '$lang: ${entry.key} is empty');
        }
      }
    });

    test('non-English translations actually differ from English '
        'for a representative sample', () async {
      final en = await _load('en');
      const sampleKeys = <String>[
        'storagePageTitle',
        'storageFreeTier',
        'securityManageDevices',
        'devicePendingFinalize',
        'cryptoOpenAsset',
        'cryptoCopyAddress',
        'vaultCardOverview',
        'secureItemCopyUsername',
      ];
      for (final lang in const ['ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(lang);
        for (final key in sampleKeys) {
          final enVal = requiredKeys[key]!(en);
          final locVal = requiredKeys[key]!(l);
          expect(locVal, isNot(equals(enVal)),
              reason:
                  '$lang: $key should differ from English '
                  '"$enVal" but got "$locVal"');
        }
      }
    });
  });


  group('safety phrase blocklist across all localized new keys', () {
    const bannedByLang = <String, List<String>>{
      'en': [
        'unhackable',
        'impossible to attack',
        'guaranteed safe',
        'sign up with an email',
        'sign up with email',
        'pending deletion',
        'grace period',
        'nobody will know you own it',
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


    Future<List<String>> _collectAllStringsForLocale(String code) async {
      final l = await _load(code);
      return <String>[

        l.commonContinue, l.commonApprove, l.commonReject,
        l.commonRevoke, l.commonReceive, l.commonReview,
        l.commonAnalyze, l.commonCopy, l.commonEdit, l.commonCurrent,

        l.storagePageTitle, l.storageNoDataAvailable,
        l.storageUsageHeading, l.storageAccountHeading,
        l.storageFreeTier, l.storageNeedMoreSpace,
        l.storageGrandfathered, l.storageAdditionalPricing,
        l.storagePlanLower, l.storageCouldNotLoad,
        l.storageRefreshNow,

        l.securityManageDevices, l.securityAnalyzePasswordsTitle,
        l.securityEnterVaultPin, l.securityAnalyzeButton,
        l.securityAnalyzeMore,

        l.devicePendingRequestSelfApproval,
        l.devicePendingFinalize, l.devicePendingCancelApproval,
        l.devicePendingCheckAgain, l.devicePendingRegisterDevice,
        l.devicePendingDiagnoseTrust,
        l.devicePendingCopyDiagnostics,
        l.devicePendingDiagnosticsCopied,

        l.cryptoLiteCouldNotLoadRecord,
        l.cryptoLiteAddressFormatMismatchTitle,
        l.cryptoLiteSaveAnyway, l.cryptoLiteEditMetadata,
        l.cryptoLiteEditBackupMetadata, l.cryptoOpenAsset,
        l.cryptoMoneroScannerStatus, l.cryptoOpenMonero,
        l.cryptoSendDraftHeading, l.cryptoOpenSendFlow,
        l.cryptoRetryFailed, l.cryptoOpenCryptoVault,
        l.cryptoCopyAddress, l.cryptoTransactionsTab,
        l.cryptoContinueToPin, l.cryptoCopyDestination,
        l.cryptoSignatureCopied, l.cryptoCopySignature,
        l.cryptoTxIdCopied, l.cryptoCopyTxId,

        l.vaultCardOverview, l.vaultCardOpenVault,
        l.vaultCardDocumentSummary, l.vaultCardGeneratedLogins,
        l.vaultCardBilling, l.vaultCardBrowseAllHelp,

        l.secureItemCopyUsername, l.secureItemCopyValue,
      ];
    }

    for (final entry in bannedByLang.entries) {
      final lang = entry.key;
      final banned = entry.value;
      test('$lang: no new key contains forbidden phrase', () async {
        final all = await _collectAllStringsForLocale(lang);
        for (final s in all) {
          final lower = s.toLowerCase();
          for (final bad in banned) {
            expect(lower.contains(bad.toLowerCase()), isFalse,
                reason:
                    '$lang: string "$s" contains forbidden phrase '
                    '"$bad"');
          }
        }
      });
    }
  });


  group('ticker/network safety — never translated', () {
    Future<void> _assertTickerPreserved(String tickerOrNetwork) async {
      for (final lang in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(lang);

        expect(l.snackAddressCopied.toLowerCase().contains('address') ||
               l.snackAddressCopied.trim().isNotEmpty, isTrue);
        expect(tickerOrNetwork, isNotEmpty);
      }
    }

    test('ticker strings are unchanged in ARB (not localized)', () async {
      await _assertTickerPreserved('ETH');
      await _assertTickerPreserved('SOL');
      await _assertTickerPreserved('XMR');
      await _assertTickerPreserved('USDT');


      for (final lang in const ['ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(lang);
        expect(l.cryptoMoneroScannerStatus.contains('Monero'), isTrue,
            reason: '$lang cryptoMoneroScannerStatus must keep '
                'the ticker name "Monero" untranslated');
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
                    Text(l.storagePageTitle),
                    Text(l.storageFreeTier),
                    Text(l.storageAdditionalPricing),
                    Text(l.storageCouldNotLoad),
                    Text(l.securityManageDevices),
                    Text(l.securityAnalyzeButton),
                    Text(l.securityAnalyzePasswordsTitle),
                    Text(l.devicePendingRequestSelfApproval),
                    Text(l.devicePendingFinalize),
                    Text(l.devicePendingRegisterDevice),
                    Text(l.cryptoOpenAsset),
                    Text(l.cryptoCopyAddress),
                    Text(l.cryptoMoneroScannerStatus),
                    Text(l.cryptoContinueToPin),
                    Text(l.cryptoCopyDestination),
                    Text(l.vaultCardOverview),
                    Text(l.vaultCardOpenVault),
                    Text(l.vaultCardBrowseAllHelp),
                    Text(l.secureItemCopyUsername),
                    Text(l.secureItemCopyValue),
                  ],
                ),
              ),
            );
          }),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets(
      'Korean at 360x800 does not throw',
      (tester) async {
        await _pumpAllNewKeys(tester, const Locale('ko'));
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'Arabic at 360x800 does not throw and is RTL',
      (tester) async {
        await _pumpAllNewKeys(tester, const Locale('ar'));
        expect(tester.takeException(), isNull);
        final dir = Directionality.of(
          tester.element(find.byType(Scaffold)),
        );
        expect(dir, TextDirection.rtl);
      },
    );

    testWidgets(
      'French/Spanish/Japanese/Chinese smoke render',
      (tester) async {
        for (final code in const ['fr', 'es', 'ja', 'zh']) {
          await _pumpAllNewKeys(tester, Locale(code));
          expect(tester.takeException(), isNull,
              reason: '$code smoke failed');
        }
      },
    );
  });


  group('no generic Aisha copy in touched ARB keys', () {
    test('no new key contains the string "Aisha" '
        '(anti-generic-copy guard)', () async {
      for (final code in const ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh']) {
        final l = await _load(code);
        for (final s in <String>[
          l.storagePageTitle, l.storageUsageHeading,
          l.securityManageDevices, l.cryptoOpenAsset,
          l.vaultCardOverview,
        ]) {
          expect(s.contains('Aisha'), isFalse,
              reason: '$code contained generic Aisha copy');
        }
      }
    });
  });
}
