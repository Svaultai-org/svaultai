

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';


String _readLib(String relativePath) {
  return File(
    '${Directory.current.path}/lib/$relativePath',
  ).readAsStringSync().replaceAll('\r\n', '\n');
}


Widget _wrap(Widget child) {
  return MaterialApp(home: Scaffold(body: child));
}


void main() {
  
  
  group('Loading-state constants', () {
    test('kTierLoadingLabel resolves to "loading"', () {
      expect(kTierLoadingLabel, 'loading');
    });

    test('loading status + body are operator-pinned', () {
      expect(kCryptoVaultLoadingStatus, 'Checking access…');
      expect(kCryptoVaultLoadingBody,
          'Loading your Crypto Vault access.');
    });
  });

  
  group('Loading tier renders neutral card', () {
    testWidgets('tier=loading shows "Checking access…" status',
        (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      
      
      expect(find.byKey(const Key('crypto_vault_loading_card')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_vault_locked_card')),
          findsNothing);
      expect(find.byKey(const Key('crypto_vault_active_card')),
          findsNothing);
      
      expect(find.byKey(const Key('crypto_vault_loading_icon')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_vault_lock_icon')),
          findsNothing);
      expect(find.byKey(const Key('crypto_vault_active_icon')),
          findsNothing);
      
      expect(find.text('Checking access…'), findsOneWidget);
      expect(find.text('Loading your Crypto Vault access.'),
          findsOneWidget);
    });

    testWidgets('tier=loading hides the upgrade-required button',
        (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      
      expect(
        find.byKey(const Key('crypto_vault_upgrade_required_button')),
        findsNothing,
      );
      expect(find.text('Upgrade required'), findsNothing);
      
      expect(find.byKey(const Key('crypto_vault_open_button')),
          findsNothing);
      expect(find.text('Open Crypto Vault'), findsNothing);
    });

    testWidgets('tier=loading shows disabled "Checking…" button',
        (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      final btn = find.byKey(const Key('crypto_vault_loading_button'));
      expect(btn, findsOneWidget);
      
      final widget = tester.widget<ElevatedButton>(btn);
      expect(widget.onPressed, isNull,
          reason: 'loading button must be disabled — no navigation '
              'while billing is still loading.');
    });

    testWidgets('tier=loading carries none of the forbidden upgrade '
        'or active wordings', (tester) async {
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      expect(find.text('Available with upgrade'), findsNothing);
      expect(find.text('Upgrade required'), findsNothing);
      expect(find.text('Active'), findsNothing);
      expect(find.text('Open Crypto Vault'), findsNothing);
    });
  });

  
  group('Loading → upgraded transition', () {
    testWidgets(
        'rebuilding from loading to upgraded skips "Upgrade required"',
        (tester) async {
      
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      expect(find.text('Checking access…'), findsOneWidget);
      expect(find.text('Upgrade required'), findsNothing);
      
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierUpgradedLabel),
      ));
      expect(find.text('Active'), findsOneWidget);
      expect(find.text('Open Crypto Vault'), findsOneWidget);
      
      expect(find.text('Upgrade required'), findsNothing);
      expect(find.text('Available with upgrade'), findsNothing);
    });
  });

  
  group('main.dart Settings call site loading gate', () {
    test('Settings card site reads !app.isBillingLoaded first', () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains(
          'tier: !app.isBillingLoaded\n'
          '                    ? kTierLoadingLabel',
        ),
        reason: 'Settings call site MUST gate the tier resolution on '
            '!app.isBillingLoaded so an upgraded user never sees the '
            'upgrade flicker.',
      );
    });
  });

  
  group('Crypto Vault PAGE non-blocking access gate', () {
    test(
      '_buildCryptoVaultSection does NOT full-page-block on billing '
      'loading/error — it renders a non-blocking status banner instead',
      () {
        final src = _readLib('main.dart');


        expect(
          src.contains('if (!app.isBillingLoaded) {'),
          isFalse,
          reason: '_buildCryptoVaultSection must NOT gate the whole '
              'crypto vault behind !app.isBillingLoaded — a slow or '
              'errored billing check must not block the Crypto Vault '
              'shell.',
        );

        expect(
          src.contains("Key('crypto_vault_page_card_loading')"),
          isFalse,
          reason: 'The full-page "loading card" gate must be gone — '
              'the crypto vault engine (or a known-not-upgraded locked '
              'card) must render even before billing has loaded.',
        );
        expect(
          src.contains("Key('crypto_vault_page_card_error')"),
          isFalse,
          reason: 'The full-page "error card" gate must be gone.',
        );


        expect(
          src.contains('_CryptoVaultBillingStatusBanner'),
          isTrue,
          reason: 'A compact non-blocking billing status banner must '
              'render above the crypto vault content when billing is '
              'loading or errored.',
        );

        expect(
          src.contains('billingLoaded'),
          isTrue,
          reason: 'The new code must inspect billingLoaded to decide '
              'the confirmed-not-upgraded gate.',
        );

        expect(
          src.contains('isKnownNotUpgraded'),
          isTrue,
          reason: 'The new code must only lock the vault when we '
              'KNOW the user is not upgraded (billing loaded AND no '
              'purchased storage) — never on billing timeout.',
        );
      },
    );
  });

  
  group('Mobile layout', () {
    testWidgets('loading card renders without overflow at 360 px',
        (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_wrap(
        const CryptoVaultLockedCard(tier: kTierLoadingLabel),
      ));
      await tester.pump();
      
      
      expect(find.byKey(const Key('crypto_vault_loading_card')),
          findsOneWidget);
      expect(find.text('Checking access…'), findsOneWidget);
    });
  });

  
  group('Regression — null tier still defaults to free', () {
    testWidgets('null tier renders the locked card (NOT loading)',
        (tester) async {
      
      
      await tester.pumpWidget(_wrap(const CryptoVaultLockedCard()));
      expect(find.byKey(const Key('crypto_vault_locked_card')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_vault_loading_card')),
          findsNothing);
      // 2026-07-12: status label + button label both say
      // "Upgrade required" on the default locked card.
      expect(find.text('Upgrade required'), findsNWidgets(2));
    });
  });
}
