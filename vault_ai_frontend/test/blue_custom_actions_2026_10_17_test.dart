import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_security_page.dart';
import 'package:vault_ai_frontend/ui/theme.dart';
import 'package:vault_ai_frontend/ui/tokens.dart';

double _contrast(Color foreground, Color background) {
  final a = foreground.computeLuminance();
  final b = background.computeLuminance();
  return ((a > b ? a : b) + 0.05) / ((a < b ? a : b) + 0.05);
}

Widget _app(Widget child) => MaterialApp(
      theme: VaultTheme.dark(),
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

void _expectReadableBlue(ButtonStyle style) {
  final background = style.backgroundColor!.resolve({})!;
  final foreground = style.foregroundColor!.resolve({})!;
  expect(background, VaultColors.accent);
  expect(foreground, VaultColors.textOnAccent);
  expect(_contrast(foreground, background), greaterThanOrEqualTo(4.5));
}

void main() {
  testWidgets('wallet security shield stays visible across its blue gradient',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: VaultTheme.dark(),
      home: const CryptoWalletEngineSecurityPage(),
    ));
    expect(tester.takeException(), isNull);
    final hero = find.byKey(const Key('crypto_wallet_engine_security_hero'));
    final badge = tester
        .widgetList<Container>(
            find.descendant(of: hero, matching: find.byType(Container)))
        .singleWhere((container) =>
            container.decoration is BoxDecoration &&
            (container.decoration! as BoxDecoration).shape == BoxShape.circle);
    final gradient =
        (badge.decoration! as BoxDecoration).gradient! as LinearGradient;
    final shield = tester.widget<Icon>(
        find.descendant(of: hero, matching: find.byIcon(Icons.shield_rounded)));
    for (var step = 0; step <= 10; step++) {
      final background =
          Color.lerp(gradient.colors.first, gradient.colors.last, step / 10)!;
      expect(_contrast(shield.color!, background), greaterThanOrEqualTo(3));
    }
  });

  test('wallet primary action uses readable ink on the shared blue', () {
    _expectReadableBlue(walletPrimaryButtonStyle());
  });

  testWidgets('receive copy action stays readable and preserves its callback',
      (tester) async {
    String? copied;
    const demoAddress = 'demo-address-for-ui-check-only';
    await tester.pumpWidget(_app(ReceivePanel(
      title: 'Demo wallet',
      address: demoAddress,
      network: 'ETH',
      onCopy: (address) => copied = address,
    )));
    final finder = find.byKey(const Key('crypto_receive_copy_button'));
    _expectReadableBlue(tester.widget<ElevatedButton>(finder).style!);
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    expect(copied, demoAddress);
    expect(tester.takeException(), isNull);
  });

  for (final upgraded in [false, true]) {
    testWidgets(
        'Assets ${upgraded ? 'open' : 'upgrade'} action retains its flow',
        (tester) async {
      var activated = false;
      await tester.pumpWidget(_app(CryptoVaultLockedCard(
        tier: upgraded ? kTierUpgradedLabel : kTierFreeLabel,
        onUpgradeRequired: () => activated = true,
        onOpenCryptoVault: () => activated = true,
      )));
      final key = upgraded
          ? 'crypto_vault_open_button'
          : 'crypto_vault_upgrade_required_button';
      final finder = find.byKey(Key(key));
      _expectReadableBlue(tester.widget<ElevatedButton>(finder).style!);
      await tester.ensureVisible(finder);
      await tester.tap(finder);
      expect(activated, isTrue);
      expect(tester.takeException(), isNull);
    });
  }
}
