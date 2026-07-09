

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


Future<void> _pump(
  WidgetTester tester, {
  required List<VaultLoginItem> items,
  String vaultLabel = 'My Vault',
}) async {
  await tester.binding.setSurfaceSize(const Size(1400, 1200));
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(
        body: LoginsPage(
          isLoading: false,
          hasLoaded: true,
          logins: items,
          vaultLabel: vaultLabel,
          onRefresh: () async {},
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


VaultLoginItem _item(String type, String service) =>
    VaultLoginItem(service: service, itemType: type);


List<VaultLoginItem> _mixedFixture() {
  return [
    _item('login',                       'Revolut Bank'),
    _item('login',                       'Union Bank'),
    _item('credential',                  'GitHub'),
    _item('imei',                        'IPhone 15 IMEI'),
    _item('serial_number',               'MacBook Serial'),
    _item('backup_code',                 'Google Backup'),
    _item('recovery_code',               'BitLocker'),
    _item('private_note',                'Bag Combo'),
    _item('account_note',                'Bank Account Note'),
    _item('crypto_wallet_address',       'USDT TRC20 Wallet'),
    _item('crypto_seed_phrase',          'Bitcoin Seed'),
    _item('license_key',                 'Norton Key'),
  ];
}


void main() {
  group('Search bar', () {
    testWidgets('renders with operator-pinned hint copy',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      expect(
        find.byKey(const Key('logins_page_search_bar')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('logins_page_search_field')),
        findsOneWidget,
      );
      expect(find.text(kLoginsSearchHint), findsOneWidget);
    });

    testWidgets('typing filters cards by title substring',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      
      expect(find.text('Revolut Bank'), findsOneWidget);
      expect(find.text('Union Bank'),    findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('logins_page_search_field')),
        'revolut',
      );
      await tester.pumpAndSettle();
      
      expect(find.text('Revolut Bank'), findsOneWidget);
      expect(find.text('Union Bank'),    findsNothing);
      expect(find.text('GitHub'),        findsNothing);
    });

    testWidgets(
      'typing a per-type label substring surfaces matching cards',
      (tester) async {
        await _pump(tester, items: _mixedFixture());
        
        
        await tester.enterText(
          find.byKey(const Key('logins_page_search_field')),
          'imei',
        );
        await tester.pumpAndSettle();
        expect(find.text('IPhone 15 IMEI'), findsOneWidget);
        expect(find.text('Revolut Bank'),    findsNothing);
      },
    );

    testWidgets('clear button blanks the query', (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.enterText(
        find.byKey(const Key('logins_page_search_field')),
        'revolut',
      );
      await tester.pumpAndSettle();
      expect(find.text('Union Bank'), findsNothing);
      
      await tester.tap(
        find.byKey(const Key('logins_page_search_clear')),
      );
      await tester.pumpAndSettle();
      expect(find.text('Union Bank'), findsOneWidget);
    });
  });


  group('Category chip strip', () {
    testWidgets('renders all seven closed-set chips', (tester) async {
      await _pump(tester, items: _mixedFixture());
      expect(
        find.byKey(const Key('logins_page_category_chip_strip')),
        findsOneWidget,
      );
      for (final c in kSecureItemCategoryChips) {
        expect(
          find.byKey(Key('logins_page_chip_${c.id}')),
          findsOneWidget,
          reason: 'chip ${c.id} must render',
        );
      }
    });

    testWidgets('default chip is "All" and shows every row',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      
      expect(find.text('Revolut Bank'),       findsOneWidget);
      expect(find.text('IPhone 15 IMEI'),     findsOneWidget);
      expect(find.text('USDT TRC20 Wallet'),  findsOneWidget);
      expect(find.text('Norton Key'),         findsOneWidget);
    });

    testWidgets('"Logins" chip shows only login / credential rows',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipLogins.id}')),
      );
      await tester.pumpAndSettle();
      expect(find.text('Revolut Bank'), findsOneWidget);
      expect(find.text('Union Bank'),    findsOneWidget);
      expect(find.text('GitHub'),        findsOneWidget);
      
      expect(find.text('IPhone 15 IMEI'),    findsNothing);
      expect(find.text('USDT TRC20 Wallet'), findsNothing);
      expect(find.text('Bag Combo'),         findsNothing);
    });

    testWidgets('"Notes" chip shows only private / account notes',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipNotes.id}')),
      );
      await tester.pumpAndSettle();
      expect(find.text('Bag Combo'),          findsOneWidget);
      expect(find.text('Bank Account Note'),  findsOneWidget);
      
      expect(find.text('Revolut Bank'),       findsNothing);
      expect(find.text('IPhone 15 IMEI'),     findsNothing);
    });

    testWidgets('"Codes" chip shows backup + recovery codes',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipCodes.id}')),
      );
      await tester.pumpAndSettle();
      expect(find.text('Google Backup'), findsOneWidget);
      expect(find.text('BitLocker'),      findsOneWidget);
      expect(find.text('Revolut Bank'),   findsNothing);
    });

    testWidgets(
      '"Device details" chip shows phone IMEI + serial rows',
      (tester) async {
        await _pump(tester, items: _mixedFixture());
        await tester.tap(
          find.byKey(Key('logins_page_chip_${kCategoryChipDevice.id}')),
        );
        await tester.pumpAndSettle();
        expect(find.text('IPhone 15 IMEI'), findsOneWidget);
        expect(find.text('MacBook Serial'),  findsOneWidget);
        expect(find.text('Revolut Bank'),    findsNothing);
      },
    );

    testWidgets('"Crypto" chip shows crypto-vault rows', (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipCrypto.id}')),
      );
      await tester.pumpAndSettle();
      expect(find.text('USDT TRC20 Wallet'), findsOneWidget);
      expect(find.text('Bitcoin Seed'),       findsOneWidget);
      expect(find.text('Revolut Bank'),       findsNothing);
    });

    testWidgets('"Other" chip shows license-key + un-classified rows',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipOther.id}')),
      );
      await tester.pumpAndSettle();
      expect(find.text('Norton Key'),    findsOneWidget);
      expect(find.text('Revolut Bank'),  findsNothing);
      expect(find.text('IPhone 15 IMEI'), findsNothing);
    });

    testWidgets(
      'chip + query compose: "Crypto" + "USDT" only shows USDT',
      (tester) async {
        await _pump(tester, items: _mixedFixture());
        await tester.tap(
          find.byKey(Key('logins_page_chip_${kCategoryChipCrypto.id}')),
        );
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const Key('logins_page_search_field')),
          'usdt',
        );
        await tester.pumpAndSettle();
        expect(find.text('USDT TRC20 Wallet'), findsOneWidget);
        expect(find.text('Bitcoin Seed'),       findsNothing);
      },
    );
  });


  group('Filter-empty placeholder', () {
    testWidgets('renders when no row matches', (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.enterText(
        find.byKey(const Key('logins_page_search_field')),
        'nothing-matches-this',
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('logins_page_filter_empty_state')),
        findsOneWidget,
      );
      expect(find.text('No matching saved items'), findsOneWidget);
      
      
      expect(find.text(kLoginsEmptyTitle), findsNothing);
    });

    testWidgets('chip + query empty state names BOTH scopes',
        (tester) async {
      await _pump(tester, items: _mixedFixture());
      await tester.tap(
        find.byKey(Key('logins_page_chip_${kCategoryChipCodes.id}')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('logins_page_search_field')),
        'revolut',
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('logins_page_filter_empty_state')),
        findsOneWidget,
      );
      
      expect(
        find.textContaining('"revolut"'),
        findsOneWidget,
      );
      expect(
        find.textContaining(kCategoryChipCodes.label),
        findsAtLeastNWidgets(1),
      );
    });
  });


  group('Closed-set chip resolver', () {
    test('login + credential → logins bucket', () {
      expect(secureItemChipIdFor('login'),      kCategoryChipLogins.id);
      expect(secureItemChipIdFor('credential'), kCategoryChipLogins.id);
    });

    test('private + account + document notes → notes bucket', () {
      expect(secureItemChipIdFor('private_note'),  kCategoryChipNotes.id);
      expect(secureItemChipIdFor('account_note'),  kCategoryChipNotes.id);
      expect(secureItemChipIdFor('document_note'), kCategoryChipNotes.id);
    });

    test('backup + recovery codes → codes bucket', () {
      expect(secureItemChipIdFor('backup_code'),   kCategoryChipCodes.id);
      expect(secureItemChipIdFor('recovery_code'), kCategoryChipCodes.id);
      expect(
        secureItemChipIdFor('recovery_phrase'),
        kCategoryChipCodes.id,
      );
    });

    test('imei + serial + device → device bucket', () {
      expect(secureItemChipIdFor('imei'),          kCategoryChipDevice.id);
      expect(secureItemChipIdFor('serial_number'), kCategoryChipDevice.id);
      expect(secureItemChipIdFor('device'),        kCategoryChipDevice.id);
      expect(secureItemChipIdFor('device_info'),   kCategoryChipDevice.id);
    });

    test('crypto_* item_types → crypto bucket', () {
      for (final t in const [
        'crypto_wallet_address', 'crypto_seed_phrase',
        'crypto_private_key',    'crypto_recovery_phrase',
        'crypto_note',           'crypto_transaction_note',
        'crypto_exchange_note',  'crypto_hardware_wallet_note',
      ]) {
        expect(
          secureItemChipIdFor(t), kCategoryChipCrypto.id,
          reason: '$t must land in the crypto chip bucket',
        );
      }
    });

    test('license / product / activation keys + bank + card → other', () {
      for (final t in const [
        'license_key', 'product_key', 'activation_key',
        'private_key', 'bank', 'card',
        'other', 'other_secret',
      ]) {
        expect(
          secureItemChipIdFor(t), kCategoryChipOther.id,
          reason: '$t must land in the other chip bucket',
        );
      }
    });

    test('unknown item_type defaults to "other" (safe default)', () {
      expect(secureItemChipIdFor('voodoo'), kCategoryChipOther.id);
    });

    test('All chip matches every row', () {
      final login = _item('login', 'Netflix');
      final imei  = _item('imei',   'iPhone');
      expect(secureItemMatchesChip(login, kCategoryChipAll), isTrue);
      expect(secureItemMatchesChip(imei,  kCategoryChipAll), isTrue);
    });
  });


  group('Query matcher', () {
    test('empty query matches every row', () {
      final item = _item('login', 'Netflix');
      expect(secureItemMatchesQuery(item, ''), isTrue);
      expect(secureItemMatchesQuery(item, '   '), isTrue);
    });

    test('case-insensitive substring match on title', () {
      final item = _item('login', 'Revolut Bank');
      expect(secureItemMatchesQuery(item, 'revolut'), isTrue);
      expect(secureItemMatchesQuery(item, 'BANK'),    isTrue);
      expect(secureItemMatchesQuery(item, 'union'),   isFalse);
    });

    test('matches per-type label so "imei" finds Phone IMEI rows', () {
      final item = _item('imei', 'iPhone 15');
      expect(secureItemMatchesQuery(item, 'imei'), isTrue);
    });
  });
}
