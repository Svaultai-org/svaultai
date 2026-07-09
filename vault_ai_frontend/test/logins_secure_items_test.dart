

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  required List<VaultLoginItem> items,
  String vaultLabel = 'VaultAI',
  bool isLoading = false,
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
          isLoading: isLoading,
          
          
          hasLoaded: !isLoading,
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


void main() {
  group('Heading + subtitle', () {
    testWidgets('heading reads "Logins & Secure Items"',
        (tester) async {
      await _pump(tester, items: [_item('login', 'Netflix')]);
      expect(find.text('Logins & Secure Items'), findsOneWidget);
      expect(
        find.byKey(const Key('logins_page_heading')),
        findsOneWidget,
      );
    });

    testWidgets('subtitle lists the broader text-record scope',
        (tester) async {
      await _pump(tester, items: [_item('login', 'Netflix')]);
      final sub = tester.widget<Text>(
        find.byKey(const Key('logins_page_subtitle')),
      );
      for (final fragment in [
        'passwords',
        'credentials',
        'private notes',
        'codes',
        'device details',
        'encrypted text records',
      ]) {
        expect(sub.data, contains(fragment));
      }
    });
  });


  group('Per-item-type rendering', () {
    testWidgets(
      'each item type renders its operator-pinned label',
      (tester) async {
        await _pump(tester, items: [
          _item('login',                       'Netflix'),
          _item('imei',                        'iPhone 15 IMEI'),
          _item('serial_number',               'Laptop serial'),
          _item('backup_code',                 'Google Backup'),
          _item('recovery_code',               'BitLocker'),
          _item('private_note',                'Bag combo'),
          _item('account_note',                'Bank note'),
          _item('crypto_wallet_address',       'USDT TRC20 wallet'),
          _item('crypto_seed_phrase',          'Bitcoin seed'),
          _item('crypto_private_key',          'ETH private key'),
          _item('crypto_note',                 'BTC bought 50k'),
          _item('crypto_transaction_note',     'Sent 1.5 ETH'),
          _item('crypto_hardware_wallet_note', 'Ledger PIN'),
        ]);
        
        for (final label in [
          'Login',
          'Phone IMEI',
          'Serial number',
          'Backup code',
          'Recovery code',
          'Private note',
          'Account note',
          'Crypto wallet',
          'Seed phrase',
          'Private key',
          'Crypto note',
          'Transaction note',
          'Hardware wallet note',
        ]) {
          expect(
            find.text(label), findsAtLeastNWidgets(1),
            reason: 'label "$label" must render as the chip',
          );
        }
      },
    );

    testWidgets('IMEI card renders the smartphone icon',
        (tester) async {
      await _pump(tester, items: [_item('imei', 'iPhone IMEI')]);
      
      
      expect(
        find.byIcon(Icons.smartphone_outlined),
        findsAtLeastNWidgets(1),
      );
      expect(find.text('Phone IMEI'), findsOneWidget);
    });

    testWidgets('Private note card renders the notes icon',
        (tester) async {
      await _pump(tester, items: [_item('private_note', 'My phrase')]);
      expect(find.byIcon(Icons.notes_outlined), findsAtLeastNWidgets(1));
      expect(find.text('Private note'), findsOneWidget);
    });

    testWidgets('Backup code card renders the backup icon',
        (tester) async {
      await _pump(tester, items: [_item('backup_code', 'Google')]);
      
      expect(find.byIcon(Icons.backup_outlined), findsOneWidget);
      expect(find.text('Backup code'), findsOneWidget);
    });

    testWidgets(
      'Crypto wallet card renders the wallet icon',
      (tester) async {
        await _pump(tester, items: [
          _item('crypto_wallet_address', 'USDT TRC20 wallet'),
        ]);
        
        
        expect(
          find.byIcon(Icons.account_balance_wallet_outlined),
          findsAtLeastNWidgets(1),
        );
        expect(find.text('Crypto wallet'), findsOneWidget);
      },
    );

    testWidgets(
      'unknown item_type falls back to "Saved item" + inventory icon',
      (tester) async {
        await _pump(tester, items: [_item('voodoo', 'Unknown thing')]);
        expect(find.text('Saved item'), findsOneWidget);
        
        
        expect(
          find.byIcon(Icons.inventory_2_outlined),
          findsAtLeastNWidgets(1),
        );
      },
    );
  });


  group('Login vs non-login preview blurb', () {
    testWidgets(
      'login card carries the "Username & password stored" blurb',
      (tester) async {
        await _pump(tester, items: [_item('login', 'Netflix')]);
        expect(
          find.textContaining('Username & password stored'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'non-login card does NOT carry the username/password blurb',
      (tester) async {
        await _pump(tester, items: [
          _item('imei',                  'iPhone IMEI'),
          _item('private_note',          'Bag combo'),
          _item('crypto_wallet_address', 'USDT'),
        ]);
        expect(
          find.textContaining('Username & password'),
          findsNothing,
          reason:
              'non-login cards must NOT carry the '
              'username/password structure hint',
        );
      },
    );

    testWidgets(
      'seed phrase card carries the "anyone controls the wallet" warning',
      (tester) async {
        
        
        await _pump(tester, items: [
          _item('crypto_seed_phrase', 'Bitcoin seed'),
        ]);
        expect(
          find.textContaining('controls the wallet'),
          findsAtLeastNWidgets(1),
        );
      },
    );

    test('previewBlurbForType is closed-set', () {
      
      
      expect(
        previewBlurbForType('login'),
        contains('Username & password'),
      );
      expect(
        previewBlurbForType('credential'),
        contains('Username & password'),
      );
      
      for (final t in const [
        'imei',
        'serial_number',
        'backup_code',
        'private_note',
        'crypto_wallet_address',
        'crypto_seed_phrase',
        'crypto_private_key',
      ]) {
        expect(
          previewBlurbForType(t).contains('Username & password'),
          isFalse,
          reason:
              'non-login type "$t" must NOT carry the '
              'username/password blurb',
        );
      }
    });

    test('isLoginLikeType is closed-set', () {
      expect(isLoginLikeType('login'),                isTrue);
      expect(isLoginLikeType('credential'),           isTrue);
      expect(isLoginLikeType('imei'),                 isFalse);
      expect(isLoginLikeType('private_note'),         isFalse);
      expect(isLoginLikeType('crypto_wallet_address'), isFalse);
      expect(isLoginLikeType('crypto_seed_phrase'),   isFalse);
    });
  });


  group('Empty state', () {
    testWidgets('empty state uses the operator-pinned copy',
        (tester) async {
      await _pump(tester, items: const <VaultLoginItem>[]);
      expect(
        find.byKey(const Key('logins_page_empty_title')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('logins_page_empty_body')),
        findsOneWidget,
      );
      final body = tester.widget<Text>(
        find.byKey(const Key('logins_page_empty_body')),
      );
      for (final fragment in const [
        'private text',
        'logins',
        'IMEIs',
        'backup codes',
        'private notes',
        'crypto wallet addresses',
        'Files',
      ]) {
        expect(body.data, contains(fragment));
      }
    });
  });


  group('Sensitive-value containment', () {
    testWidgets(
      'card body NEVER renders password / IMEI / seed phrase '
      'characters from the row',
      (tester) async {
        
        
        const evilSeed =
            'mountain river apple thunder sapphire orchid '
            'cinnamon valley horizon crystal velvet tiger';
        await _pump(tester, items: [
          _item('crypto_seed_phrase', evilSeed),
        ]);
        
        
        final seedMatches = find.textContaining('Mountain River');
        expect(seedMatches, findsOneWidget,
            reason:
                'service title may carry the words, but no '
                'additional preview / value widget should '
                'reproduce them on the card');
      },
    );
  });


  group('Source-level guards', () {
    test(
      'api_client.dart declares listVaultSecureItems → '
      '/list-secure-items',
      () async {
        final src = await File('lib/api_client.dart').readAsString();
        expect(
          src,
          contains('listVaultSecureItems('),
          reason:
              'api_client.dart must expose listVaultSecureItems '
              'so the Logins page can fetch all encrypted text '
              'records',
        );
        expect(
          src,
          contains('/list-secure-items'),
          reason:
              'listVaultSecureItems must POST '
              '/list-secure-items',
        );
      },
    );

    test(
      'main.dart calls listVaultSecureItems in the Logins '
      'loader (broader scope replaces the legacy login-only '
      'call)',
      () async {
        final src = await File('lib/main.dart').readAsString();
        
        expect(
          src, contains('listVaultSecureItems('),
          reason:
              'main.dart must load secure items via '
              'listVaultSecureItems so the Logins page shows '
              'IMEIs / private notes / crypto wallets / etc.',
        );
      },
    );

    test(
      'main.dart does NOT route uploaded files into the Logins '
      'loader',
      () async {
        final src = await File('lib/main.dart').readAsString();
        final start = src.indexOf('_loadVaultLogins');
        expect(start, isNot(-1));
        
        
        final next = src.indexOf('\n  Future<', start + 1);
        final body = (next == -1)
            ? src.substring(start)
            : src.substring(start, next);
        
        
        for (final needle in const <String>[
          'uploadVaultFile(',
          'downloadVaultFile(',
          'listVaultFiles(',
          'vault_files',
          'file_id',
        ]) {
          expect(
            body.contains(needle), isFalse,
            reason:
                '_loadVaultLogins must NOT touch "$needle" — '
                'uploaded files belong in the Files section',
          );
        }
      },
    );

    test('logins_page.dart carries the operator-pinned constants',
        () async {
      final src = await File('lib/logins_page.dart').readAsString();
      expect(src, contains('kLoginsPageHeading'));
      expect(src, contains('Logins & Secure Items'));
      expect(src, contains('kSecureItemTypeLabels'));
      expect(src, contains('Phone IMEI'));
      expect(src, contains('Crypto wallet'));
      expect(src, contains('Seed phrase'));
    });
  });
}
