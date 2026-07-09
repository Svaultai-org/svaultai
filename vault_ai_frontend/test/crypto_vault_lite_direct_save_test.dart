

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


const String _ETH_ADDR =
    '0x0000000000000000000000000000000000000001';
const String _TRC20_ADDR = 'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY';
const String _RECOVERY_PHRASE =
    'abandon abandon abandon abandon abandon abandon '
    'abandon abandon abandon abandon abandon about';


Future<void> _pump(
  WidgetTester tester, {
  void Function(String prompt)? onSendChatPrompt,
  Future<void> Function(CryptoAddWalletDraft draft)?
      onDirectSaveWalletProfile,
  Future<void> Function(CryptoAddSensitiveBackupDraft draft)?
      onDirectSaveSensitiveBackup,
  List<Map<String, dynamic>> savedRecords = const [],
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords: savedRecords,
        onSendChatPrompt: onSendChatPrompt,
        onDirectSaveWalletProfile: onDirectSaveWalletProfile,
        onDirectSaveSensitiveBackup: onDirectSaveSensitiveBackup,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


Future<void> _fillWalletDialog(
  WidgetTester tester, {
  String assetDisplayName = 'Ethereum',
  String labelDisplayName = 'MetaMask',
  String address = _ETH_ADDR,
  String? note,
}) async {
  
  await tester.tap(find.byKey(
    const Key('crypto_lite_add_wallet_asset_dropdown'),
  ));
  await tester.pumpAndSettle();
  await tester.tap(find.text(assetDisplayName).last);
  await tester.pumpAndSettle();
  
  await tester.tap(find.byKey(
    const Key('crypto_lite_add_wallet_label_dropdown'),
  ));
  await tester.pumpAndSettle();
  await tester.tap(find.text(labelDisplayName).last);
  await tester.pumpAndSettle();
  
  await tester.enterText(
    find.byKey(const Key('crypto_lite_add_wallet_address_field')),
    address,
  );
  if (note != null) {
    await tester.enterText(
      find.byKey(const Key('crypto_lite_add_wallet_note_field')),
      note,
    );
  }
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('F1/F2 — Direct callback receives structured draft', () {
    testWidgets(
      'MetaMask + ETH + address → onDirectSaveWalletProfile fires '
      'with structured draft',
      (tester) async {
        final captured = <CryptoAddWalletDraft>[];
        final chatPrompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: chatPrompts.add,
          onDirectSaveWalletProfile: (draft) async {
            captured.add(draft);
          },
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        await _fillWalletDialog(tester, note: 'Daily driver');
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();

        
        expect(captured.length, 1);
        final d = captured.single;
        
        expect(d.asset.id,           'eth');
        expect(d.asset.networkLabel, 'Ethereum');
        expect(d.label.id,           'metamask');
        expect(d.address,            _ETH_ADDR);
        expect(d.note,               'Daily driver');

        
        expect(chatPrompts, isEmpty);
      },
    );

    testWidgets(
      'Trust Wallet + USDT TRC20 + address → structured draft',
      (tester) async {
        final captured = <CryptoAddWalletDraft>[];
        await _pump(
          tester,
          onDirectSaveWalletProfile: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        await _fillWalletDialog(
          tester,
          assetDisplayName: 'USDT TRC20',
          labelDisplayName: 'Trust Wallet',
          address: _TRC20_ADDR,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(captured.length, 1);
        expect(captured.single.asset.id,           'usdt_trc20');
        expect(captured.single.asset.networkLabel, 'Tron TRC20');
        expect(captured.single.label.id,           'trust_wallet');
        expect(captured.single.address,            _TRC20_ADDR);
      },
    );
  });

  
  group('F4 — Dialog closes on success', () {
    testWidgets('dialog closes after onDirectSaveWalletProfile succeeds',
        (tester) async {
      await _pump(
        tester,
        onDirectSaveWalletProfile: (_) async {},
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      await _fillWalletDialog(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_save_button'),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsNothing,
      );
    });
  });

  
  group('F5 — Inline error keeps dialog open', () {
    testWidgets('save error shows visible error message + keeps '
        'dialog open + does not echo address', (tester) async {
      await _pump(
        tester,
        onDirectSaveWalletProfile: (_) async {
          throw Exception('Save crypto wallet failed: 500');
        },
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      await _fillWalletDialog(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_save_button'),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_save_error')),
        findsOneWidget,
      );
      
      for (final t in tester.widgetList<Text>(
        find.descendant(
          of: find.byKey(
            const Key('crypto_lite_add_wallet_save_error'),
          ),
          matching: find.byType(Text),
        ),
      )) {
        expect((t.data ?? '').contains(_ETH_ADDR), isFalse,
            reason: 'save-error envelope must NEVER echo '
                'the public wallet address');
      }
    });
  });

  
  group('F6 — Address format mismatch warns but allows', () {
    testWidgets(
      'ETH dropdown + Tron-shaped address → warning then proceed → '
      'direct callback fires',
      (tester) async {
        final captured = <CryptoAddWalletDraft>[];
        await _pump(
          tester,
          onDirectSaveWalletProfile: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        await _fillWalletDialog(
          tester,
          assetDisplayName: 'Ethereum',
          labelDisplayName: 'MetaMask',
          address: _TRC20_ADDR, 
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key(
            'crypto_lite_add_wallet_format_warning_dialog',
          )),
          findsOneWidget,
        );
        
        await tester.tap(find.byKey(const Key(
          'crypto_lite_add_wallet_format_warning_continue',
        )));
        await tester.pumpAndSettle();
        expect(captured.length, 1);
        expect(captured.single.address, _TRC20_ADDR);
      },
    );
  });

  
  group('F7/F8 — Sensitive backup direct save', () {
    Future<void> fillSensitiveBackup(
      WidgetTester tester, {
      String labelDisplayName = 'Ledger',
      String typeDisplayName  = 'Recovery phrase',
      String secret = _RECOVERY_PHRASE,
    }) async {
      
      await tester.tap(find.byKey(const Key(
        'crypto_lite_add_sensitive_backup_label_dropdown',
      )));
      await tester.pumpAndSettle();
      await tester.tap(find.text(labelDisplayName).last);
      await tester.pumpAndSettle();
      
      await tester.tap(find.byKey(const Key(
        'crypto_lite_add_sensitive_backup_type_dropdown',
      )));
      await tester.pumpAndSettle();
      await tester.tap(find.text(typeDisplayName).last);
      await tester.pumpAndSettle();
      
      await tester.enterText(
        find.byKey(const Key(
          'crypto_lite_add_sensitive_backup_value_field',
        )),
        secret,
      );
    }

    testWidgets(
      'seed-phrase button opens warning, confirm opens structured '
      'sensitive-backup dialog, save fires onDirectSaveSensitiveBackup',
      (tester) async {
        final captured = <CryptoAddSensitiveBackupDraft>[];
        final chatPrompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: chatPrompts.add,
          onDirectSaveSensitiveBackup: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key('crypto_vault_strong_warning_dialog')),
          findsOneWidget,
        );
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key(
            'crypto_lite_add_sensitive_backup_dialog',
          )),
          findsOneWidget,
        );
        
        await fillSensitiveBackup(tester);
        await tester.tap(find.byKey(const Key(
          'crypto_lite_add_sensitive_backup_save_button',
        )));
        await tester.pumpAndSettle();
        
        expect(captured.length, 1);
        final d = captured.single;
        expect(d.warningConfirmed, isTrue);
        expect(d.label.id,         'ledger');
        expect(d.secretType.id,    'recovery_phrase');
        expect(d.secretValue,      _RECOVERY_PHRASE);
        
        
        expect(chatPrompts, isEmpty);
      },
    );

    testWidgets(
      'each secret type discriminator routes to its closed-set id',
      (tester) async {
        for (final pair in const [
          ['Seed phrase',     'seed_phrase'],
          ['Private key',     'private_key'],
          ['Recovery phrase', 'recovery_phrase'],
        ]) {
          final captured = <CryptoAddSensitiveBackupDraft>[];
          await _pump(
            tester,
            onDirectSaveSensitiveBackup: (d) async => captured.add(d),
          );
          await tester.tap(find.byKey(
            const Key('crypto_lite_add_seed_button'),
          ));
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(
            const Key('crypto_vault_strong_warning_continue'),
          ));
          await tester.pumpAndSettle();
          await fillSensitiveBackup(
            tester,
            labelDisplayName: 'Trezor',
            typeDisplayName: pair[0],
            secret: 'x' * 40,
          );
          await tester.tap(find.byKey(const Key(
            'crypto_lite_add_sensitive_backup_save_button',
          )));
          await tester.pumpAndSettle();
          expect(captured.length, 1);
          expect(captured.single.secretType.id, pair[1]);
        }
      },
    );

    testWidgets(
      'sensitive backup dialog does NOT show Show QR affordance',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveSensitiveBackup: (_) async {},
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        
        
        for (final t in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(const Key(
              'crypto_lite_add_sensitive_backup_dialog',
            )),
            matching: find.byType(Text),
          ),
        )) {
          final body = (t.data ?? '').toLowerCase();
          expect(body.contains('show qr'), isFalse,
              reason: 'sensitive backup dialog MUST NOT surface '
                  'a Show QR control — receive-only QR is wallet-'
                  'profile-only');
        }
      },
    );
  });

  
  group('F9 — Required-field validation', () {
    testWidgets(
      'sensitive-backup save with empty fields does not call '
      'onDirectSaveSensitiveBackup',
      (tester) async {
        final captured = <CryptoAddSensitiveBackupDraft>[];
        await _pump(
          tester,
          onDirectSaveSensitiveBackup: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(const Key(
          'crypto_lite_add_sensitive_backup_save_button',
        )));
        await tester.pumpAndSettle();
        
        expect(captured, isEmpty);
        
        expect(
          find.byKey(const Key(
            'crypto_lite_add_sensitive_backup_dialog',
          )),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'wallet save with empty address does not call '
      'onDirectSaveWalletProfile',
      (tester) async {
        final captured = <CryptoAddWalletDraft>[];
        await _pump(
          tester,
          onDirectSaveWalletProfile: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_asset_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Ethereum').last);
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_label_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('MetaMask').last);
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isEmpty);
        
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsOneWidget,
        );
      },
    );
  });

  
  group('F10 — Save in-flight UI', () {
    testWidgets('save button shows spinner while callback pending',
        (tester) async {
      final completer = Completer<void>();
      await _pump(
        tester,
        onDirectSaveWalletProfile: (_) => completer.future,
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      await _fillWalletDialog(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_save_button'),
      ));
      
      await tester.pump();
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      
      completer.complete();
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsNothing,
      );
    });
  });

  
  group('F11 — Backward compat with chat prompt', () {
    testWidgets(
      'no direct callback wired → save routes through onSendChatPrompt',
      (tester) async {
        final chatPrompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: chatPrompts.add,
          
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        await _fillWalletDialog(tester);
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(chatPrompts.length, 1);
        expect(chatPrompts.single, contains('MetaMask'));
        expect(chatPrompts.single, contains('Ethereum'));
        expect(chatPrompts.single, contains(_ETH_ADDR));
      },
    );

    testWidgets(
      'no direct sensitive backup callback wired → warning then '
      'legacy chat-prompt path',
      (tester) async {
        final chatPrompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: chatPrompts.add,
          
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        
        expect(chatPrompts, [kCryptoPromptAddSeed]);
        expect(
          find.byKey(const Key(
            'crypto_lite_add_sensitive_backup_dialog',
          )),
          findsNothing,
        );
      },
    );
  });

  
  group('F12 — Anti-claim guardrails on new dialog', () {
    testWidgets(
      'sensitive-backup dialog contains no send / buy / sell / '
      'swap / generate / sign / broadcast copy',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveSensitiveBackup: (_) async {},
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        for (final t in tester.widgetList<Text>(find.byType(Text))) {
          final body = (t.data ?? '').toLowerCase();
          for (final needle in const [
            'send crypto', 'send btc', 'send eth',
            'buy crypto', 'sell crypto', 'swap crypto',
            'trade crypto', 'create wallet', 'create a wallet',
            'wallet generation', 'generate wallet',
            'broadcast transaction', 'sign transaction',
            'connect metamask',
          ]) {
            expect(body.contains(needle), isFalse,
                reason: 'sensitive backup dialog MUST NOT '
                    'contain "$needle"; found in "$body"');
          }
        }
      },
    );
  });

  
  group('F13 — Mobile layout', () {
    testWidgets(
      'Add Wallet dialog opens at 360 px without overflow',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(360, 800));
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: const [],
              onDirectSaveWalletProfile: (_) async {},
            ),
          ),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsOneWidget,
        );
      },
    );
  });
}
