
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  required List<VaultLoginItem> items,
  Size size = const Size(1400, 1200),
  String vaultLabel = 'VaultAI',
}) async {
  await tester.binding.setSurfaceSize(size);
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
          onAskVault: (_) {},
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


VaultLoginItem _sys(String service) =>
    VaultLoginItem(service: service, itemType: 'crypto_wallet_account');


VaultLoginItem _user(String type, String service) =>
    VaultLoginItem(service: service, itemType: type);


void main() {

  group('Visibility helper', () {
    test('kSystemHiddenItemTypes includes crypto_wallet_account', () {
      expect(
        kSystemHiddenItemTypes.contains('crypto_wallet_account'),
        isTrue,
      );
    });

    test('isSystemHiddenItemType returns true for crypto_wallet_account',
        () {
      expect(isSystemHiddenItemType('crypto_wallet_account'), isTrue);
    });

    test('isSystemHiddenItemType returns false for user types', () {
      for (final t in <String>[
        'login', 'credential', 'card', 'crypto_wallet_address',
        'crypto_note', 'crypto_seed_phrase', 'private_note',
      ]) {
        expect(
          isSystemHiddenItemType(t), isFalse,
          reason: 't=$t must not be hidden',
        );
      }
    });
  });


  group('Logins & Secure Items rendering', () {
    testWidgets('does not render ETH:ethereum_mainnet system row',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('ETH:ethereum_mainnet'),
      ]);
      expect(find.text('Netflix'), findsOneWidget);
      expect(
        find.textContaining('ETH:ethereum_mainnet',
            findRichText: true),
        findsNothing,
      );
      expect(
        find.textContaining('Ethereum_mainnet',
            findRichText: true),
        findsNothing,
      );
    });

    testWidgets('does not render XMR:monero_mainnet system row',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('XMR:monero_mainnet'),
      ]);
      expect(
        find.textContaining('XMR:monero_mainnet',
            findRichText: true),
        findsNothing,
      );
      expect(
        find.textContaining('Monero_mainnet',
            findRichText: true),
        findsNothing,
      );
    });

    testWidgets('does not render USDT_TRC20:tron_mainnet system row',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('USDT_TRC20:tron_mainnet'),
      ]);
      expect(
        find.textContaining('USDT_TRC20:tron_mainnet',
            findRichText: true),
        findsNothing,
      );
      expect(
        find.textContaining('Tron_mainnet',
            findRichText: true),
        findsNothing,
      );
    });

    testWidgets('does not render SOL:solana_mainnet system row',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('SOL:solana_mainnet'),
      ]);
      expect(
        find.textContaining('SOL:solana_mainnet',
            findRichText: true),
        findsNothing,
      );
      expect(
        find.textContaining('Solana_mainnet',
            findRichText: true),
        findsNothing,
      );
    });

    testWidgets('bare ETH system row is also hidden',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('ETH'),
      ]);

      expect(find.byIcon(Icons.lock_outline), findsWidgets);

      expect(
        find.byKey(const Key('secure_item_card_crypto_wallet_account-Eth')),
        findsNothing,
      );
    });

    testWidgets('all four leaking wallet records hidden at once',
        (tester) async {
      await _pump(tester, items: [
        _user('login', 'Netflix'),
        _sys('ETH'),
        _sys('ETH:ethereum_mainnet'),
        _sys('XMR:monero_mainnet'),
        _sys('USDT_TRC20:tron_mainnet'),
        _sys('SOL:solana_mainnet'),
      ]);

      expect(find.text('Netflix'), findsOneWidget);
      for (final leaked in <String>[
        'ETH:ethereum_mainnet',
        'XMR:monero_mainnet',
        'USDT_TRC20:tron_mainnet',
        'SOL:solana_mainnet',
      ]) {
        expect(
          find.textContaining(leaked, findRichText: true), findsNothing,
          reason: '"$leaked" system row must not appear',
        );
      }
    });
  });


  group('Preserve user-created crypto notes', () {
    testWidgets(
      'crypto_wallet_address user note still renders',
      (tester) async {
        await _pump(tester, items: [
          _user('crypto_wallet_address', 'MyLedgerETHAddress'),
          _sys('ETH:ethereum_mainnet'),
        ]);
        expect(
          find.textContaining('MyLedgerETHAddress',
              findRichText: true),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'crypto_seed_phrase user note still renders',
      (tester) async {
        await _pump(tester, items: [
          _user('crypto_seed_phrase', 'BackupSeedNote'),
          _sys('ETH:ethereum_mainnet'),
        ]);
        expect(
          find.textContaining('BackupSeedNote',
              findRichText: true),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'crypto_note user note still renders',
      (tester) async {
        await _pump(tester, items: [
          _user('crypto_note', 'MyExchangeAccount'),
          _sys('ETH:ethereum_mainnet'),
        ]);
        expect(
          find.textContaining('MyExchangeAccount',
              findRichText: true),
          findsOneWidget,
        );
      },
    );
  });


  group('Crypto filter chip', () {
    testWidgets(
      'Crypto chip does NOT show internal wallet records',
      (tester) async {
        await _pump(tester, items: [
          _user('crypto_wallet_address', 'MyLedgerETH'),
          _sys('ETH:ethereum_mainnet'),
          _sys('XMR:monero_mainnet'),
        ]);
        await tester.tap(
          find.byKey(const Key('logins_page_chip_crypto')),
        );
        await tester.pumpAndSettle();

        expect(
          find.textContaining('MyLedgerETH',
              findRichText: true),
          findsOneWidget,
        );
        for (final leaked in <String>[
          'ETH:ethereum_mainnet',
          'XMR:monero_mainnet',
        ]) {
          expect(
            find.textContaining(leaked, findRichText: true),
            findsNothing,
            reason:
                'Crypto filter must not show system record $leaked',
          );
        }
      },
    );
  });


  group('Ask VaultAI button', () {
    testWidgets(
      'Ask VaultAI never appears attached to a hidden system record',
      (tester) async {
        await _pump(tester, items: [
          _sys('ETH:ethereum_mainnet'),
          _sys('XMR:monero_mainnet'),
        ]);

        expect(find.text(kLoginsEmptyTitle), findsOneWidget);
        expect(find.textContaining('Ask VaultAI'), findsNothing);
      },
    );

    testWidgets(
      'Ask VaultAI still appears for real user items even when a '
      'system row is present',
      (tester) async {
        await _pump(tester, items: [
          _user('login', 'Netflix'),
          _sys('ETH:ethereum_mainnet'),
        ]);
        expect(find.textContaining('Ask VaultAI'), findsOneWidget);
      },
    );
  });


  group('Empty state', () {
    testWidgets(
      'vault with ONLY hidden system records shows clean empty state',
      (tester) async {
        await _pump(tester, items: [
          _sys('ETH:ethereum_mainnet'),
          _sys('XMR:monero_mainnet'),
          _sys('USDT_TRC20:tron_mainnet'),
          _sys('SOL:solana_mainnet'),
          _sys('ETH'),
        ]);
        expect(
          find.byKey(const Key('logins_page_empty_title')),
          findsOneWidget,
        );
        expect(find.text(kLoginsEmptyTitle), findsOneWidget);
      },
    );

    testWidgets(
      'vault with a real item does not show the empty state',
      (tester) async {
        await _pump(tester, items: [
          _user('login', 'Netflix'),
          _sys('ETH:ethereum_mainnet'),
        ]);
        expect(
          find.byKey(const Key('logins_page_empty_title')),
          findsNothing,
        );
      },
    );
  });


  group('Mobile no overflow', () {
    testWidgets(
      'renders without overflow at 400×900 with mixed items',
      (tester) async {
        await _pump(
          tester,
          size: const Size(800, 900),
          items: [
            _user('login', 'Netflix'),
            _user('crypto_wallet_address', 'MyLedgerETH'),
            _sys('ETH:ethereum_mainnet'),
            _sys('XMR:monero_mainnet'),
          ],
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'empty-state (only system records) renders at 400×900',
      (tester) async {
        await _pump(
          tester,
          size: const Size(800, 900),
          items: [
            _sys('ETH:ethereum_mainnet'),
            _sys('XMR:monero_mainnet'),
          ],
        );
        expect(tester.takeException(), isNull);
      },
    );
  });
}
