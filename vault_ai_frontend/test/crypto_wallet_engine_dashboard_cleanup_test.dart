

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_security_page.dart';

Future<void> _pumpDashboard(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    const MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,home: Scaffold(body: CryptoWalletEnginePage())),
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpSecurity(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    const MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,home: CryptoWalletEngineSecurityPage()),
  );
  await tester.pumpAndSettle();
}



const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('crypto wallet engine dashboard cleanup', () {
    testWidgets('CL1: Portfolio renders before any legacy banner key',
        (tester) async {
      await _pumpDashboard(tester);
      final portfolio = find.byKey(
        const Key('crypto_wallet_engine_portfolio_summary'),
      );
      expect(portfolio, findsOneWidget);
      
      final heading = find.byKey(
        const Key('crypto_wallet_engine_heading'),
      );
      expect(heading, findsOneWidget);
      final headingY = tester.getTopLeft(heading).dy;
      final portfolioY = tester.getTopLeft(portfolio).dy;
      expect(portfolioY, greaterThan(headingY));
      
      
      final actions = find.byKey(
        const Key('crypto_wallet_engine_primary_actions'),
      );
      final assets = find.byKey(
        const Key('crypto_wallet_engine_asset_grid'),
      );
      expect(actions, findsOneWidget);
      expect(assets, findsOneWidget);
      expect(tester.getTopLeft(actions).dy, greaterThan(portfolioY));
      expect(tester.getTopLeft(assets).dy,
          greaterThan(tester.getTopLeft(actions).dy));
    });

    testWidgets('CL2: compact network + non-custodial chips render',
        (tester) async {
      await _pumpDashboard(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_chip_testnet')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_chip_non_custodial')),
        findsOneWidget,
      );
    });

    testWidgets('CL3: giant testnet warning panel is gone',
        (tester) async {
      await _pumpDashboard(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_testnet_warning')),
        findsNothing,
      );
    });

    testWidgets(
        'CL4: mainnet "coming soon" banner is gone on the testnet build',
        (tester) async {
      await _pumpDashboard(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_mainnet_coming_soon')),
        findsNothing,
      );
    });

    testWidgets('CL5: legacy attestation banner is gone', (tester) async {
      await _pumpDashboard(tester);
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_non_custodial_attestation'),
        ),
        findsNothing,
      );
    });

    testWidgets('CL6: legacy Backup + Notes cards are gone',
        (tester) async {
      await _pumpDashboard(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_backup_section')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_notes_section')),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_backup_open_btn')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_notes_open_btn')),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_security_section')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_security_open_btn')),
        findsOneWidget,
      );
    });

    testWidgets(
        'CL7: dashboard text never carries any legacy Lite copy phrase',
        (tester) async {
      await _pumpDashboard(tester);
      const banned = <String>[
        'Crypto Vault Lite',
        'Add wallet address',
        'Add seed phrase / private key',
        'Add crypto note',
        'Add transaction note',
        'Saved wallets',
        'Balance lookup not connected',
        'Send features are not enabled yet',
        'Receive QR only shows saved addresses',
        'Trust Wallet',
        'Bitcoin',
        'BNB Smart Chain',
      ];
      for (final phrase in banned) {
        expect(
          find.textContaining(phrase),
          findsNothing,
          reason: 'Legacy Lite copy "$phrase" must not appear anywhere '
              'on the live Crypto Wallet dashboard.',
        );
      }
    });

    testWidgets(
        'CL8: Security primary action opens the dark wallet-style page',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      final btn = find.byKey(
        const Key('crypto_wallet_engine_primary_backup_btn'),
      );
      expect(btn, findsOneWidget);
      await tester.ensureVisible(btn);
      await tester.pumpAndSettle();
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_security_page')),
        findsOneWidget,
      );
    });

    // 2026-07-12: CL9 removed. The onOpenLite parameter was fully
    // deleted from CryptoWalletEnginePage on the same day Crypto
    // Vault Lite was retired — there is no longer a hook to invoke.
    // CL13 below still guards against re-introducing it in source.
  });

  group('crypto wallet engine security page', () {
    testWidgets('CL10: security page renders the wallet-style sections',
        (tester) async {
      await _pumpSecurity(tester);
      for (final keyName in const [
        'crypto_wallet_engine_security_page',
        'crypto_wallet_engine_security_page_title',
        'crypto_wallet_engine_security_hero',
        'crypto_wallet_engine_security_status_card',
        'crypto_wallet_engine_security_backup_card',
        'crypto_wallet_engine_security_recovery_card',
        'crypto_wallet_engine_security_device_card',
        'crypto_wallet_engine_security_reminder_card',
      ]) {
        expect(
          find.byKey(Key(keyName)),
          findsOneWidget,
          reason: 'Security page section "$keyName" must render.',
        );
      }
    });

    testWidgets('CL11: security page contains no legacy Lite copy',
        (tester) async {
      await _pumpSecurity(tester);
      const banned = <String>[
        'Crypto Vault Lite',
        'Add wallet address',
        'Add seed phrase / private key',
        'Add crypto note',
        'Add transaction note',
        'Saved wallets',
        'Balance lookup not connected',
        'Trust Wallet',
        'Bitcoin',
        'BNB Smart Chain',
      ];
      for (final phrase in banned) {
        expect(
          find.textContaining(phrase),
          findsNothing,
          reason: 'Legacy Lite copy "$phrase" must not appear on the '
              'new Security page.',
        );
      }
    });
  });

  group('crypto wallet engine source guards', () {
    test('CL12: main.dart no longer constructs CryptoVaultLitePage', () {
      final src = File('lib/main.dart').readAsStringSync();
      expect(
        src.contains('CryptoVaultLitePage('),
        isFalse,
        reason: 'main.dart must NOT construct CryptoVaultLitePage — '
            'the legacy saved-record UI is retired from the live '
            'product.',
      );
    });

    test('CL13: engine page carries no onOpenLite parameter at all',
        () {
      // 2026-07-12: strengthened — onOpenLite is fully removed from
      // the engine page's public API. Not just "never invoked" — the
      // symbol must not exist as a parameter or field either.
      final src = File(
        'lib/ui/crypto_wallet_engine_page.dart',
      ).readAsStringSync();
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      expect(
        scrubbed.contains('onOpenLite'),
        isFalse,
        reason: 'onOpenLite has been fully removed alongside the '
            'retirement of CryptoVaultLitePage.',
      );
    });
  });
}
