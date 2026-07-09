

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';

const _usdtFull = 'TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY';
const _ethFull  = '0x1234567890abcdef1234567890abcdef12345678';

List<Map<String, dynamic>> _seedRecords() => [
      {
        'item_id':        'r1',
        'type':           'crypto_wallet_address',
        'title':          'USDT TRC20 wallet',
        'category_label': 'Crypto wallet',
        'icon':           'wallet',
        'preview': {
          'wallet_address_mask': 'TQx2P5…1RnY',
          'network':              'USDT TRC20',
        },
      },
      {
        'item_id':        'r2',
        'type':           'crypto_wallet_address',
        'title':          'ETH wallet',
        'category_label': 'Crypto wallet',
        'icon':           'wallet',
        'preview': {
          'wallet_address_mask': '0x1234…5678',
          'network':              'ETH',
        },
      },
      {
        'item_id':        'r3',
        'type':           'crypto_seed_phrase',
        'title':          'Bitcoin seed phrase',
        'category_label': 'Seed phrase',
        'icon':           'seed',
        'preview': {
          'seed_phrase_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r4',
        'type':           'crypto_note',
        'title':          'Avg buy notes',
        'category_label': 'Crypto note',
        'icon':           'note',
        'preview': {
          'crypto_note_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r5',
        'type':           'crypto_transaction_note',
        'title':          'ETH invoice 17',
        'category_label': 'Transaction note',
        'icon':           'note',
        'preview': {
          'transaction_note_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r6',
        'type':           'crypto_exchange_note',
        'title':          'Binance sub-account',
        'category_label': 'Exchange note',
        'icon':           'note',
        'preview': {
          'exchange_note_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r7',
        'type':           'crypto_hardware_wallet_note',
        'title':          'Ledger Nano X',
        'category_label': 'Hardware wallet note',
        'icon':           'wallet',
        'preview': {
          'hardware_wallet_note_mask': '•••••• hidden',
        },
      },
    ];

Future<void> _pump(
  WidgetTester tester, {
  List<Map<String, dynamic>>? savedRecords,
  void Function(Map<String, dynamic>)? onView,
  void Function(Map<String, dynamic>)? onEdit,
  void Function(Map<String, dynamic>)? onDelete,
  void Function(Map<String, dynamic>)? onCopyValue,
}) async {
  
  
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(
    MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoVaultLitePage(
          savedRecords: savedRecords ?? _seedRecords(),
          onView: onView,
          onEdit: onEdit,
          onDelete: onDelete,
          onCopyValue: onCopyValue,
        ),
      ),
    ),
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
  group('Search bar', () {
    testWidgets('renders only when records exist', (tester) async {
      await _pump(tester, savedRecords: const <Map<String, dynamic>>[]);
      expect(
        find.byKey(const Key('crypto_lite_search_field')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_lite_chip_strip')),
        findsNothing,
      );
    });

    testWidgets('substring matches title', (tester) async {
      await _pump(tester);
      
      expect(find.text('USDT TRC20 wallet'),    findsOneWidget);
      expect(find.text('ETH wallet'),           findsOneWidget);
      expect(find.text('Bitcoin seed phrase'),  findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('crypto_lite_search_field')),
        'usdt',
      );
      await tester.pumpAndSettle();
      expect(find.text('USDT TRC20 wallet'),    findsOneWidget);
      expect(find.text('ETH wallet'),           findsNothing);
      expect(find.text('Bitcoin seed phrase'),  findsNothing);
    });

    testWidgets('substring matches network label', (tester) async {
      await _pump(tester);
      await tester.enterText(
        find.byKey(const Key('crypto_lite_search_field')),
        'eth',
      );
      await tester.pumpAndSettle();
      
      expect(find.text('ETH wallet'),           findsOneWidget);
      expect(find.text('USDT TRC20 wallet'),    findsNothing);
    });

    testWidgets('clear button restores the full list', (tester) async {
      await _pump(tester);
      await tester.enterText(
        find.byKey(const Key('crypto_lite_search_field')),
        'usdt',
      );
      await tester.pumpAndSettle();
      expect(find.text('ETH wallet'), findsNothing);
      
      expect(
        find.byKey(const Key('crypto_lite_search_clear')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('crypto_lite_search_clear')));
      await tester.pumpAndSettle();
      expect(find.text('ETH wallet'), findsOneWidget);
    });

    testWidgets('no-match shows the filter empty state', (tester) async {
      await _pump(tester);
      await tester.enterText(
        find.byKey(const Key('crypto_lite_search_field')),
        'definitely-not-a-real-record',
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_filter_empty_state')),
        findsOneWidget,
      );
    });
  });

  group('Filter chips', () {
    testWidgets('renders the closed-set chip strip in order',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_lite_chip_strip')),
        findsOneWidget,
      );
      for (final id in const [
        'all', 'wallets', 'seed_keys',
        'notes', 'transactions', 'exchange_hardware',
      ]) {
        expect(
          find.byKey(Key('crypto_lite_chip_$id')),
          findsOneWidget,
          reason: 'chip $id must render',
        );
      }
      
      expect(find.text('All'),                findsOneWidget);
      expect(find.text('Wallets'),            findsOneWidget);
      expect(find.text('Seed/Keys'),          findsOneWidget);
      expect(find.text('Notes'),              findsOneWidget);
      expect(find.text('Transactions'),       findsOneWidget);
      expect(find.text('Exchange/Hardware'),  findsOneWidget);
    });

    testWidgets('Wallets chip narrows to wallet-address rows',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_wallets')));
      await tester.pumpAndSettle();
      expect(find.text('USDT TRC20 wallet'),    findsOneWidget);
      expect(find.text('ETH wallet'),           findsOneWidget);
      expect(find.text('Bitcoin seed phrase'),  findsNothing);
      expect(find.text('Avg buy notes'),        findsNothing);
      expect(find.text('Binance sub-account'),  findsNothing);
    });

    testWidgets('Seed/Keys chip narrows to seed + key rows',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_seed_keys')));
      await tester.pumpAndSettle();
      expect(find.text('Bitcoin seed phrase'),  findsOneWidget);
      expect(find.text('USDT TRC20 wallet'),    findsNothing);
      expect(find.text('Avg buy notes'),        findsNothing);
    });

    testWidgets('Notes chip narrows to crypto note rows',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_notes')));
      await tester.pumpAndSettle();
      expect(find.text('Avg buy notes'),        findsOneWidget);
      expect(find.text('USDT TRC20 wallet'),    findsNothing);
      expect(find.text('Bitcoin seed phrase'),  findsNothing);
    });

    testWidgets('Transactions chip narrows to transaction note rows',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_transactions')));
      await tester.pumpAndSettle();
      expect(find.text('ETH invoice 17'),       findsOneWidget);
      expect(find.text('USDT TRC20 wallet'),    findsNothing);
    });

    testWidgets('Exchange/Hardware chip narrows to exchange + hardware rows',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_chip_exchange_hardware'),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Binance sub-account'),  findsOneWidget);
      expect(find.text('Ledger Nano X'),        findsOneWidget);
      expect(find.text('USDT TRC20 wallet'),    findsNothing);
    });

    testWidgets('All chip restores every record', (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_wallets')));
      await tester.pumpAndSettle();
      expect(find.text('Bitcoin seed phrase'), findsNothing);
      await tester.tap(find.byKey(const Key('crypto_lite_chip_all')));
      await tester.pumpAndSettle();
      expect(find.text('Bitcoin seed phrase'), findsOneWidget);
    });
  });

  group('Search + chip compose', () {
    testWidgets('search applies WITHIN the active chip bucket',
        (tester) async {
      await _pump(tester);
      
      await tester.tap(find.byKey(const Key('crypto_lite_chip_wallets')));
      await tester.pumpAndSettle();
      expect(find.text('ETH wallet'),        findsOneWidget);
      expect(find.text('USDT TRC20 wallet'), findsOneWidget);
      
      await tester.enterText(
        find.byKey(const Key('crypto_lite_search_field')),
        'usdt',
      );
      await tester.pumpAndSettle();
      expect(find.text('USDT TRC20 wallet'), findsOneWidget);
      expect(find.text('ETH wallet'),        findsNothing);
    });
  });

  group('Card actions — View / Edit / Delete / Copy', () {
    testWidgets('action buttons render per card when callbacks supplied',
        (tester) async {
      await _pump(
        tester,
        onView:      (_) {},
        onEdit:      (_) {},
        onDelete:    (_) {},
        onCopyValue: (_) {},
      );
      for (final id in const ['r1', 'r2', 'r3']) {
        expect(
          find.byKey(Key('crypto_card_view_$id')),
          findsOneWidget,
        );
        expect(
          find.byKey(Key('crypto_card_edit_$id')),
          findsOneWidget,
        );
        expect(
          find.byKey(Key('crypto_card_delete_$id')),
          findsOneWidget,
        );
        expect(
          find.byKey(Key('crypto_card_copy_$id')),
          findsOneWidget,
        );
      }
    });

    testWidgets('action buttons HIDDEN when no callbacks supplied',
        (tester) async {
      await _pump(tester);
      
      for (final id in const ['r1', 'r2']) {
        expect(find.byKey(Key('crypto_card_view_$id')),   findsNothing);
        expect(find.byKey(Key('crypto_card_edit_$id')),   findsNothing);
        expect(find.byKey(Key('crypto_card_delete_$id')), findsNothing);
        expect(find.byKey(Key('crypto_card_copy_$id')),   findsNothing);
      }
    });

    testWidgets('View tap fires onView with the record',
        (tester) async {
      Map<String, dynamic>? viewed;
      await _pump(
        tester,
        onView: (r) => viewed = r,
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_r1')));
      await tester.pumpAndSettle();
      expect(viewed, isNotNull);
      expect(viewed!['title'],   'USDT TRC20 wallet');
      expect(viewed!['type'],    'crypto_wallet_address');
      expect(viewed!['item_id'], 'r1');
    });

    testWidgets('Edit tap fires onEdit with the record',
        (tester) async {
      Map<String, dynamic>? edited;
      await _pump(
        tester,
        onEdit: (r) => edited = r,
      );
      await tester.tap(find.byKey(const Key('crypto_card_edit_r1')));
      await tester.pumpAndSettle();
      expect(edited, isNotNull);
      expect(edited!['item_id'], 'r1');
    });

    testWidgets('Delete tap fires onDelete with the record',
        (tester) async {
      Map<String, dynamic>? deleted;
      await _pump(
        tester,
        onDelete: (r) => deleted = r,
      );
      await tester.tap(find.byKey(const Key('crypto_card_delete_r3')));
      await tester.pumpAndSettle();
      expect(deleted, isNotNull);
      expect(deleted!['item_id'], 'r3');
      expect(deleted!['type'],    'crypto_seed_phrase');
    });

    testWidgets('Copy tap fires onCopyValue with the record',
        (tester) async {
      Map<String, dynamic>? copied;
      await _pump(
        tester,
        onCopyValue: (r) => copied = r,
      );
      await tester.tap(find.byKey(const Key('crypto_card_copy_r1')));
      await tester.pumpAndSettle();
      expect(copied, isNotNull);
      expect(copied!['item_id'], 'r1');
    });

    testWidgets('full wallet address never renders on the card',
        (tester) async {
      await _pump(
        tester,
        onView:      (_) {},
        onCopyValue: (_) {},
      );
      
      
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = t.data ?? '';
        expect(
          body.contains(_usdtFull), isFalse,
          reason: 'full USDT wallet address must NEVER render',
        );
        expect(
          body.contains(_ethFull), isFalse,
          reason: 'full ETH wallet address must NEVER render',
        );
      }
    });
  });

  group('Filter resolver — pure function contract', () {
    test('cryptoChipIdForType maps each closed-set crypto type',
        () {
      expect(cryptoChipIdForType('crypto_wallet_address'),
          kCryptoChipWallets.id);
      expect(cryptoChipIdForType('crypto_seed_phrase'),
          kCryptoChipSeedKeys.id);
      expect(cryptoChipIdForType('crypto_private_key'),
          kCryptoChipSeedKeys.id);
      expect(cryptoChipIdForType('crypto_recovery_phrase'),
          kCryptoChipSeedKeys.id);
      expect(cryptoChipIdForType('crypto_note'),
          kCryptoChipNotes.id);
      expect(cryptoChipIdForType('crypto_transaction_note'),
          kCryptoChipTransactions.id);
      expect(cryptoChipIdForType('crypto_exchange_note'),
          kCryptoChipExchangeHardware.id);
      expect(cryptoChipIdForType('crypto_hardware_wallet_note'),
          kCryptoChipExchangeHardware.id);
    });

    test('cryptoRecordMatchesChip All matches every record', () {
      for (final r in _seedRecords()) {
        expect(
          cryptoRecordMatchesChip(r, kCryptoChipAll), isTrue,
        );
      }
    });

    test('cryptoRecordMatchesChip narrows to one bucket', () {
      final walletRow = _seedRecords()[0];
      expect(
        cryptoRecordMatchesChip(walletRow, kCryptoChipWallets), isTrue,
      );
      expect(
        cryptoRecordMatchesChip(walletRow, kCryptoChipSeedKeys), isFalse,
      );
    });

    test('cryptoRecordMatchesQuery substring case-insensitive', () {
      final walletRow = _seedRecords()[0];
      expect(cryptoRecordMatchesQuery(walletRow, ''),       isTrue);
      expect(cryptoRecordMatchesQuery(walletRow, 'USDT'),   isTrue);
      expect(cryptoRecordMatchesQuery(walletRow, 'usdt'),   isTrue);
      expect(cryptoRecordMatchesQuery(walletRow, 'wallet'), isTrue);
      expect(cryptoRecordMatchesQuery(walletRow, 'binance'), isFalse);
    });
  });
}
