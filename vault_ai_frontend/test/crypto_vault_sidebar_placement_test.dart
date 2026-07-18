

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/l10n/app_localizations_en.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';


String? _mainSrc;
Future<String> _readMain() async {
  return _mainSrc ??= await File('lib/main.dart').readAsString();
}

String? _cardSrc;
Future<String> _readCard() async {
  return _cardSrc ??=
      await File('lib/ui/crypto_vault_locked_card.dart').readAsString();
}


void main() {
  group('Sidebar / hamburger placement', () {
    test('_DashboardSection enum carries cryptoVault', () async {
      final src = await _readMain();
      expect(
        src,
        contains(RegExp(
          r'enum _DashboardSection\s*\{[^}]*\bcryptoVault\b',
          dotAll: true,
        )),
        reason:
            'cryptoVault must be a real _DashboardSection enum '
            'value so the sidebar / hamburger renders a tile for '
            'it and the body dispatcher can switch on it',
      );
    });

    test('sidebar tile() is wired for _DashboardSection.cryptoVault',
        () async {
      final src = await _readMain();
      expect(
        src,
        contains('tile(_DashboardSection.cryptoVault'),
        reason:
            'the Drawer must expose a tile(...) call for the '
            'Crypto Vault section so the sidebar surface lists it',
      );
    });

    test('sidebar tile uses the operator-pinned localized label',
        () async {
      final src = await _readMain();
      expect(
        src,
        contains('sidebarCryptoVault'),
        reason:
            'the sidebar Crypto Vault label must come from the '
            'localized ``sidebarCryptoVault`` key, NOT a hard-'
            'coded string',
      );
    });

    test('sidebar tile uses a crypto-style icon (wallet / coin / lock)',
        () async {
      final src = await _readMain();
      final m = RegExp(
        r'tile\(_DashboardSection\.cryptoVault\s*,\s*'
        r'Icons\.(\w+)\s*,',
      ).firstMatch(src);
      expect(
        m,
        isNotNull,
        reason: 'sidebar Crypto Vault tile must pass an Icons.* '
                'argument so a visual icon renders next to the '
                'label',
      );
      final iconName = m!.group(1)!;
      const allowedIcons = <String>[
        
        'account_balance_wallet_outlined',
        'account_balance_wallet',
        'wallet',
        
        'paid_outlined',
        'paid',
        'currency_bitcoin',
        
        'lock_outline',
        'lock',
      ];
      expect(
        allowedIcons.contains(iconName),
        isTrue,
        reason:
            'sidebar Crypto Vault tile must use a wallet / coin / '
            'lock style icon. Got: Icons.$iconName',
      );
    });

    test(
      'Crypto Vault tile is placed near the secure-record group '
      '(after Logins or after Memory)',
      () async {
        final src = await _readMain();
        final cryptoIdx  = src.indexOf('tile(_DashboardSection.cryptoVault');
        final loginsIdx  = src.indexOf('tile(_DashboardSection.logins');
        final memoryIdx  = src.indexOf('tile(_DashboardSection.memory');
        expect(cryptoIdx, greaterThan(-1));
        expect(loginsIdx, greaterThan(-1));
        expect(
          cryptoIdx > loginsIdx || cryptoIdx > memoryIdx,
          isTrue,
          reason:
              'Crypto Vault tile must come AFTER Logins or AFTER '
              'Memory in the sidebar per operator placement rule',
        );


        final settingsIdx =
            src.indexOf('tile(_DashboardSection.settings');
        if (settingsIdx > -1) {
          expect(
            cryptoIdx < settingsIdx,
            isTrue,
            reason:
                'Crypto Vault tile must appear above the Settings '
                'tile in the sidebar',
          );
        }
      },
    );
  });


  group('Crypto Vault page render', () {
    test('_buildBody routes _DashboardSection.cryptoVault to a section builder',
        () async {
      final src = await _readMain();
      expect(
        src,
        contains('case _DashboardSection.cryptoVault'),
        reason:
            '_buildBody must include a case for cryptoVault so '
            'tapping the sidebar tile actually renders the '
            'locked page',
      );
      expect(
        src,
        contains('_buildCryptoVaultSection'),
        reason:
            '_buildCryptoVaultSection method must exist to render '
            'the locked Crypto Vault page',
      );
    });

    test('_buildCryptoVaultSection mounts the shared CryptoVaultLockedCard',
        () async {
      final src = await _readMain();
      
      
      final start = src.indexOf(
        'Widget _buildCryptoVaultSection(',
      );
      expect(
        start, isNot(-1),
        reason:
            '_buildCryptoVaultSection method must be defined so '
            'widget tests can pin its content',
      );
      final next = src.indexOf(
        '\n  Widget _build', start + 1,
      );
      final source = (next == -1) ? src.substring(start)
                                  : src.substring(start, next);
      expect(
        source.contains('CryptoVaultLockedCard'),
        isTrue,
        reason:
            'the Crypto Vault page must mount the shared '
            'CryptoVaultLockedCard widget for the free / basic '
            'tier (single source of truth for the locked copy)',
      );
      expect(
        source.contains('sidebarCryptoVault'),
        isTrue,
        reason:
            'the page heading must use the localized '
            'sidebarCryptoVault label so the title stays '
            'localized',
      );
    });

    testWidgets(
      'page key + card key are present so widgets can be located in '
      'integration tests',
      (tester) async {
        
        
        await tester.pumpWidget(
          MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('en'),
            routes: {
              '/storage': (_) => const Scaffold(
                body: Text('storage_route_target'),
              ),
            },
            home: Scaffold(
              body: Builder(
                builder: (context) {
                  return SingleChildScrollView(
                    key: const Key('crypto_vault_page'),
                    child: Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 760),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              AppLocalizations.of(context).sidebarCryptoVault,
                              key: const Key('crypto_vault_page_heading'),
                              style: const TextStyle(
                                fontSize: 28, fontWeight: FontWeight.w800,
                              ),
                            ),
                            const SizedBox(height: 24),
                            const CryptoVaultLockedCard(
                              key: Key('crypto_vault_page_card'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_vault_page')), findsOneWidget,
        );
        expect(
          find.byKey(const Key('crypto_vault_page_heading')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('crypto_vault_page_card')),
          findsOneWidget,
        );
        
        expect(
          find.text('Crypto Vault'),
          findsAtLeastNWidgets(2),
          reason:
              'the page heading + the card title both render '
              '"Crypto Vault"',
        );
        
        
        // 2026-07-12: status label reads "Upgrade required" on
        // the non-upgraded locked card (and matches the button
        // label — two widgets).
        expect(find.text('Upgrade required'), findsNWidgets(2));
        expect(find.text('Available with upgrade'), findsNothing);
        expect(find.text('Coming soon for upgraded users'), findsNothing);
      },
    );
  });


  group('No send / receive / wallet UI on the page', () {
    test('_buildCryptoVaultSection body has no send/receive/wallet strings',
        () async {
      final src = await _readMain();
      final start = src.indexOf(
        'Widget _buildCryptoVaultSection(',
      );
      expect(start, isNot(-1));
      final next = src.indexOf(
        '\n  Widget _build', start + 1,
      );
      final source = (next == -1) ? src.substring(start)
                                  : src.substring(start, next);
      const forbidden = <String>[
        "'Send'",
        "'Receive'",
        "'Send crypto'",
        "'Receive crypto'",
        "'Create wallet'",
        "'New wallet'",
        "'Buy'",
        "'Sell'",
        "'Trade'",
        "'Swap'",
        "'Exchange'",
        'TransactionScreen',
        'SendCryptoScreen',
        'ReceiveCryptoScreen',
        'WalletScreen',
        'BroadcastScreen',
      ];
      for (final needle in forbidden) {
        expect(
          source.contains(needle), isFalse,
          reason:
              '_buildCryptoVaultSection must NEVER mention '
              '"$needle" — this slice is locked / upcoming only',
        );
      }
    });

    test('shared card module still carries no send/receive/wallet UI',
        () async {
      final src = await _readCard();
      for (final needle in const <String>[
        "import 'package:web3",
        "import 'package:bitcoin",
        "import 'package:eth_",
        "import 'package:solana",
        "import 'package:ethers",
        'SendCryptoScreen',
        'ReceiveCryptoScreen',
        'WalletScreen',
        'BroadcastScreen',
        'TransactionScreen',
      ]) {
        expect(
          src.contains(needle), isFalse,
          reason:
              'crypto_vault_locked_card.dart must NEVER carry '
              '"$needle"',
        );
      }
    });
  });


  group('Localization', () {
    test('en locale getter returns Crypto Vault', () {
      final loc = AppLocalizationsEn();
      expect(loc.sidebarCryptoVault, 'Crypto Vault');
    });

    test('every locale .arb file carries a sidebarCryptoVault entry',
        () async {
      final dir = Directory('lib/l10n');
      final arbs = dir
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.arb'));
      for (final f in arbs) {
        final src = await f.readAsString();
        expect(
          src.contains('sidebarCryptoVault'), isTrue,
          reason:
              '${f.path} must declare sidebarCryptoVault so the '
              'flutter_gen pipeline can resolve the localized '
              'string when this locale is active',
        );
      }
    });

    test(
      'every locale .dart file overrides sidebarCryptoVault',
      () async {
        final dir = Directory('lib/l10n');
        final locales = dir
            .listSync()
            .whereType<File>()
            .where((f) =>
                f.path.endsWith('.dart') &&
                f.path.contains('app_localizations_'));
        for (final f in locales) {
          final src = await f.readAsString();
          expect(
            src.contains('sidebarCryptoVault'), isTrue,
            reason:
                '${f.path} must override the abstract '
                'sidebarCryptoVault getter so AppLocalizations '
                'resolves for this locale',
          );
        }
      },
    );
  });


  group('Settings dashboard retains card', () {
    test('Settings dashboard still mounts CryptoVaultLockedCard',
        () async {
      final src = await _readMain();
      expect(
        src,
        contains('CryptoVaultLockedCard'),
        reason:
            'per operator brief the Settings card stays as a '
            'secondary upgrade promotion',
      );
      
      
      final count = 'CryptoVaultLockedCard'.allMatches(src).length;
      expect(
        count,
        greaterThanOrEqualTo(2),
        reason:
            'CryptoVaultLockedCard must mount in main.dart at least '
            'twice: Settings dashboard mount + Crypto Vault page '
            'known-not-upgraded gate. The old billing-loading mount '
            'was removed in the 2026-07-05 non-blocking billing '
            'cleanup, so the free/basic subscription gate no longer '
            'doubles as a loading spinner (got $count occurrences)',
      );
    });
  });


  group('/storage upgrade route', () {
    test('kCryptoUpgradeRoute is /storage', () {
      expect(kCryptoUpgradeRoute, '/storage');
    });

    test('kCryptoUpgradeRouteArgs carries autoOpenPicker:true', () {
      expect(
        kCryptoUpgradeRouteArgs,
        containsPair('autoOpenPicker', true),
      );
    });
  });
}
