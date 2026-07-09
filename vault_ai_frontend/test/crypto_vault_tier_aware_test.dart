

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';


String _readLib(String relativePath) {
  
  
  return File(
    '${Directory.current.path}/lib/$relativePath',
  ).readAsStringSync().replaceAll('\r\n', '\n');
}


String _stripDartComments(String src) {
  src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
  src = src.replaceAll(RegExp(r'//[^\n]*'), '');
  return src;
}


Widget _wrap(Widget child) {
  return MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(body: child),
  );
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('Operator-pinned constants', () {
    test('Active status + Open Crypto Vault button label are present',
        () {
      expect(kCryptoVaultActiveStatus, 'Active');
      expect(kCryptoVaultOpenCryptoVaultLabel, 'Open Crypto Vault');
      expect(kActionOpenCryptoVault, 'crypto_vault_open');
    });

    test('Legacy "Available with upgrade" + "Upgrade required" '
        'still exist for the free / basic branch', () {
      expect(kCryptoVaultDefaultStatus, 'Available with upgrade');
      expect(kCryptoVaultUpgradeRequiredLabel, 'Upgrade required');
    });

    test('Tier labels mirror the backend constants', () {
      expect(kTierFreeLabel,     'free');
      expect(kTierBasicLabel,    'basic');
      expect(kTierUpgradedLabel, 'upgraded');
    });
  });

  
  group('Free / basic tier renders locked card', () {
    testWidgets('default tier (null) renders locked card',
        (tester) async {
      await tester.pumpWidget(_wrap(const CryptoVaultLockedCard()));
      
      expect(find.byKey(const Key('crypto_vault_locked_card')),
          findsOneWidget);
      
      expect(find.byKey(const Key('crypto_vault_lock_icon')),
          findsOneWidget);
      
      expect(find.text('Available with upgrade'), findsOneWidget);
      
      expect(
        find.byKey(const Key('crypto_vault_upgrade_required_button')),
        findsOneWidget,
      );
      expect(find.text('Upgrade required'), findsOneWidget);
      
      expect(find.text('Active'), findsNothing);
      expect(find.text('Open Crypto Vault'), findsNothing);
    });

    testWidgets('tier=free renders locked card', (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierFreeLabel),
      ));
      expect(find.text('Available with upgrade'), findsOneWidget);
      expect(find.text('Upgrade required'), findsOneWidget);
    });

    testWidgets('tier=basic renders locked card', (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierBasicLabel),
      ));
      expect(find.text('Available with upgrade'), findsOneWidget);
      expect(find.text('Upgrade required'), findsOneWidget);
    });
  });

  
  group('Upgraded tier renders active card', () {
    testWidgets('tier=upgraded shows "Active" status', (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierUpgradedLabel),
      ));
      
      expect(find.byKey(const Key('crypto_vault_active_card')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_vault_locked_card')),
          findsNothing);
      
      expect(find.byKey(const Key('crypto_vault_active_icon')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_vault_lock_icon')),
          findsNothing);
      
      expect(find.text('Active'), findsOneWidget);
      
      expect(find.byKey(const Key('crypto_vault_open_button')),
          findsOneWidget);
      expect(find.text('Open Crypto Vault'), findsOneWidget);
      
      expect(find.text('Available with upgrade'), findsNothing);
      expect(find.text('Upgrade required'), findsNothing);
      expect(
        find.byKey(const Key('crypto_vault_upgrade_required_button')),
        findsNothing,
      );
    });

    testWidgets('upgraded tier from envelope still flips card',
        (tester) async {
      
      
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(
          envelope: <String, dynamic>{
            'tier':   'upgraded',
            'title':  'Crypto Vault',
            'status': 'Active',
          },
        ),
      ));
      expect(find.text('Active'), findsOneWidget);
      expect(find.text('Open Crypto Vault'), findsOneWidget);
    });
  });

  
  group('onOpenCryptoVault wiring', () {
    testWidgets('tapping Open Crypto Vault calls the callback',
        (tester) async {
      var fired = false;
      await tester.pumpWidget(_wrap(
        CryptoVaultLockedCard(
          tier: kTierUpgradedLabel,
          onOpenCryptoVault: () => fired = true,
        ),
      ));
      await tester.tap(
        find.byKey(const Key('crypto_vault_open_button')),
      );
      await tester.pump();
      expect(
        fired, isTrue,
        reason: 'tapping Open Crypto Vault must invoke '
            'onOpenCryptoVault, not navigate to /storage',
      );
    });

    testWidgets('upgraded user never triggers the upgrade route',
        (tester) async {
      
      
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierUpgradedLabel),
      ));
      expect(
        find.byKey(const Key('crypto_vault_upgrade_required_button')),
        findsNothing,
      );
    });
  });

  
  group('main.dart Settings call site', () {
    test('passes tier derived from billingBlockCount + billingPurchasedBytes',
        () {
      final mainSrc = _readLib('main.dart');
      
      
      expect(
        mainSrc,
        contains(
          '(app.billingBlockCount > 0\n'
          '                            && app.billingPurchasedBytes > 0)\n'
          '                        ? kTierUpgradedLabel\n'
          '                        : kTierFreeLabel',
        ),
        reason: 'Settings call site must pass the resolved tier '
            'derived from AppState.billingBlockCount + '
            'billingPurchasedBytes inside the isBillingLoaded gate.',
      );
      expect(
        mainSrc,
        contains(
          'onOpenCryptoVault: () {\n'
          '                  setState(() =>\n'
          '                      selectedSection = _DashboardSection.cryptoVault);\n'
          '                },',
        ),
        reason: 'Settings call site must wire onOpenCryptoVault to a '
            'sidebar section switch — never to the /storage route.',
      );
    });

    test('Settings card site no longer hardcodes const card', () {
      final mainSrc = _readLib('main.dart');
      
      final executable = _stripDartComments(mainSrc);
      
      
      final pattern = RegExp(
        r'CryptoVaultLockedCard\(\s*[^)]{0,400}\btier:',
        multiLine: true,
      );
      expect(
        pattern.hasMatch(executable),
        isTrue,
        reason: 'Settings card site must instantiate '
            'CryptoVaultLockedCard with a tier argument; no match '
            'for /CryptoVaultLockedCard\\(\\s*[^)]{0,400}\\btier:/ '
            'found in lib/main.dart.',
      );
    });
  });

  
  group('Crypto Vault PAGE branching (regression)', () {
    test(
        'main.dart known-not-upgraded branch shows locked card; '
        'engine is mounted otherwise (2026-07-05 non-blocking billing '
        'cleanup)',
        () {


      final mainSrc = _readLib('main.dart');



      expect(
        mainSrc,
        contains('isKnownNotUpgraded'),
        reason: 'Crypto Vault PAGE must keep a KNOWN-not-upgraded '
            'gate so confirmed-free users still see the locked card '
            '— but must NOT gate on billing loading/error anymore.',
      );

      expect(
        mainSrc,
        contains('billingBlockCount > 0 && app.billingPurchasedBytes > 0'),
        reason: 'The subscription enforcement math (block count / '
            'purchased bytes > 0) must still be checked — this is '
            'the real subscription gate that survived the cleanup.',
      );

      expect(
        mainSrc,
        isNot(contains('return CryptoVaultLitePage(')),
        reason:
            'Crypto Vault PAGE upgraded branch must NOT instantiate '
            'CryptoVaultLitePage anymore — the dashboard ships the '
            'wallet engine page instead.',
      );
      expect(
        mainSrc,
        contains('CryptoWalletEnginePage('),
        reason:
            'Crypto Vault PAGE engine branch must instantiate '
            'CryptoWalletEnginePage so upgraded users see the live '
            'non-custodial wallet dashboard.',
      );


      expect(
        mainSrc,
        isNot(contains('if (isUpgraded) {')),
        reason: 'The old billing-blocking isUpgraded early-return has '
            'been removed — engine now renders even during billing '
            'loading/error so slow billing does not block the vault.',
      );
    });
  });
}
