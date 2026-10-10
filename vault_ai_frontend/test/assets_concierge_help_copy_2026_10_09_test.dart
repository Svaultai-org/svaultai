import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_content_i18n.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';

String _answer(String id) => faqEntryById(id)!.answer;

void main() {
  test('physical-vault explanation covers the whole supported digital vault',
      () {
    final text = _answer('what-is-vaultai');
    for (final part in [
      'physical',
      'digital form',
      'more than a password manager',
      'files',
      'photos',
      'videos',
      'audio',
      'passwords',
      'memories',
      'Assets',
      'Inheritance',
      'Concierge',
      'Svaultai Chat',
    ]) {
      expect(text, contains(part));
    }
    expect(text, contains('does not turn a physical object or cash'));
    expect(_answer('what-can-i-save'), contains('storage limit'));
  });

  test('top-level Assets name retains existing technical identifiers', () {
    expect(kFaqCategoryCrypto.id, 'crypto');
    expect(kFaqCategoryCrypto.label, 'Assets');
    expect(faqEntryById('what-is-crypto-vault')!.question, 'What is Assets?');
    expect(_answer('what-is-crypto-vault'), contains('Cryptocurrency'));
    expect(_answer('is-crypto-custodial'), contains('non-custodial'));
    expect(_answer('can-vaultai-move-crypto'), contains('local signing'));
    final arb =
        jsonDecode(File('lib/l10n/app_en.arb').readAsStringSync()) as Map;
    expect(arb['helpCategoryCrypto'], 'Assets');
  });

  test(
      'Gold and Silver wording is network-specific, not a purchase or bar title',
      () {
    final supported = _answer('supported-assets');
    for (final asset in ['ETH', 'USDT', 'USDC', 'SOL', 'XMR', 'PAXG', 'KAG']) {
      expect(supported, contains(asset));
    }
    expect(supported, contains('Ethereum mainnet'));
    expect(supported, contains('receive only'));
    final metal = _answer('gold-and-silver-tokens');
    expect(metal, contains('indirect silver exposure'));
    expect(metal, contains('not direct ownership of a silver bar'));
    expect(metal, contains('native Kinesis-token reserves'));
    expect(metal, contains('not interchangeable'));
    expect(metal, contains('Issuer eligibility, sanctions'));
    expect(metal, contains('ETH pays network fees'));
    expect(metal, contains('does not buy, redeem or guarantee'));
  });

  test('seven unsupported categories are Coming soon, not live holdings', () {
    final answer = _answer('assets-coming-soon');
    for (final category in [
      'Real Estate',
      'Diamonds and Gemstones',
      'Artwork',
      'Watches and Collectibles',
      'Vehicles and Equipment',
      'Inventory and Supply Chain Goods',
      'Securities and Equities',
    ]) {
      expect(answer, contains(category));
    }
    expect(answer, contains('do not yet have verified wallet integrations'));
    expect(answer,
        contains('do not show a balance, receive address, send action'));
    expect(answer, contains('does not create ownership'));
  });

  test('Assets help explicitly excludes trading, fiat and cash-out', () {
    final answer = _answer('buy-sell-swap');
    for (final excluded in [
      'buy',
      'sell',
      'swap',
      'trade',
      'banking',
      'fiat',
      'cash-out'
    ]) {
      expect(answer, contains(excluded));
    }
    expect(answer, startsWith('No.'));
    expect(_answer('provider-unavailable'),
        contains('instead of inventing a balance'));
  });

  test(
      'Concierge free password checks distinguish privacy, consent and unavailable tools',
      () {
    final overview = _answer('what-is-concierge');
    expect(overview, contains('exposed, weak or reused passwords'));
    expect(overview, contains('not enabled in this release'));
    expect(
        overview,
        contains(
            'Email breach monitoring, background email checks and stealer-log'));
    expect(overview, contains('not a continuous or comprehensive dark-web'));
    final privacy = _answer('concierge-password-checks');
    expect(privacy, contains('first 5 characters of a password hash'));
    expect(privacy, contains('password and full hash stay on the device'));
    expect(privacy, contains('only while the vault is unlocked'));
    expect(privacy, contains('at most once every 24 hours'));
    expect(privacy, contains('not a guarantee of safety'));
    expect(privacy, contains('turn the checks off'));
  });

  test(
      'Memory and Inheritance explain real access flows without automatic funds transfer',
      () {
    final memory = _answer('what-is-memory');
    for (final action in ['save a memory', 'retrieve it', 'delete it']) {
      expect(memory, contains(action));
    }
    final inheritance = _answer('how-inheritance-works');
    expect(inheritance, contains('chosen beneficiary'));
    expect(inheritance, contains('approve or reject'));
    expect(inheritance, contains('encrypted access credentials'));
    expect(inheritance, contains('countdown'));
    expect(inheritance, contains('does not make a legal will'));
    expect(inheritance, contains('or automatically send cryptocurrency'));
  });

  test('current capability answers override obsolete locale coverage safely',
      () {
    for (final locale in ['en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh', 'pt']) {
      for (final id in kCurrentReleaseCapabilityFaqIds) {
        expect(localizedFaqEntry(id, locale)!.answer, _answer(id));
      }
      expect(localizedFaqEntriesMatchingQuery(locale, 'PAXG'), isNotEmpty);
      expect(localizedFaqEntriesMatchingQuery(locale, 'Concierge'), isNotEmpty);
    }
  });

  testWidgets(
      'public phone Help shows Assets and searchable current Concierge limits',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      locale: const Locale('en'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const Scaffold(body: HelpCenterPage(mode: HelpCenterMode.public)),
    ));
    await tester.pumpAndSettle();
    final category = find.byKey(const Key('help_center_chip_crypto'));
    expect(find.descendant(of: category, matching: find.text('Assets')),
        findsOneWidget);
    final search = find.byKey(const Key('help_center_search_field'));
    await tester.ensureVisible(search);
    await tester.enterText(search, 'Concierge');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('help_center_entry_what-is-concierge')),
        findsOneWidget);
    expect(find.textContaining('not enabled in this release'), findsWidgets);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
