

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


const String _RECOVERY_PHRASE =
    'abandon abandon abandon abandon abandon abandon '
    'abandon abandon abandon abandon abandon about';
const String _SEED_PHRASE =
    'witch collapse practice feed shame open despair '
    'creek road again ice least';
const String _PRIVATE_KEY =
    'L1aW4aubDFB7yfras2S1mN3bqg9nwySY8nkoLmJebSLD5BWv3ENZ';
const String _ETH_ADDR =
    '0x0000000000000000000000000000000000000001';


Map<String, dynamic> _backupRecord({
  String itemId = 's1',
  String type   = 'crypto_recovery_phrase',
  String title  = 'Ledger BTC recovery',
}) {
  return <String, dynamic>{
    'item_id':        itemId,
    'type':           type,
    'title':          title,
    'category_label': 'Recovery phrase',
    'preview': {
      'recovery_phrase_mask': '•••••• hidden',
      'network':              'Bitcoin',
    },
  };
}


Map<String, dynamic> _backupDetail() {
  return <String, dynamic>{
    'service':   'Ledger BTC recovery',
    'item_type': 'crypto_recovery_phrase',
    'fields': {
      'recovery_phrase': _RECOVERY_PHRASE,
      'network':         'Bitcoin',
      'wallet_label':    'Ledger',
      'asset':           'BTC',
      'secret_type':     'recovery_phrase',
    },
    'notes': 'cold storage',
  };
}


Map<String, dynamic> _walletRecord() {
  return <String, dynamic>{
    'item_id':        'w1',
    'type':           'crypto_wallet_address',
    'title':          'MetaMask Ethereum wallet',
    'category_label': 'Crypto wallet',
    'preview': {
      'wallet_address_mask': '0x0000…0001',
      'network':             'Ethereum',
    },
  };
}


Map<String, dynamic> _walletDetail() {
  return <String, dynamic>{
    'service':   'MetaMask Ethereum wallet',
    'item_type': 'crypto_wallet_address',
    'fields': {
      'wallet_address': _ETH_ADDR,
      'network':        'Ethereum',
      'wallet_label':   'MetaMask',
      'asset':          'ETH',
      'balance_status': 'lookup_not_connected',
    },
  };
}


Future<void> _pump(
  WidgetTester tester, {
  required List<Map<String, dynamic>> savedRecords,
  Future<Map<String, dynamic>> Function(Map<String, dynamic> record)?
      onLoadDetail,
  Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
    String pin,
  )? onReveal,
  void Function(Map<String, dynamic> record)? onShowQR,
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords:                  savedRecords,
        onLoadCryptoRecordDetail:      onLoadDetail,
        onRevealCryptoSensitiveBackup: onReveal,
        onShowQR:                      onShowQR,
        
        onDirectSaveWalletProfile:     (_) async {},
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


Future<void> _openBackupDetail(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
  await tester.pumpAndSettle();
}


Future<void> _walkRevealFlow(
  WidgetTester tester, {
  required String pin,
}) async {
  
  await tester.tap(find.byKey(
    const Key('crypto_backup_detail_reveal_button'),
  ));
  await tester.pumpAndSettle();
  
  await tester.tap(find.byKey(
    const Key('crypto_backup_reveal_warning_continue'),
  ));
  await tester.pumpAndSettle();
  
  await tester.enterText(
    find.byKey(const Key('crypto_backup_reveal_pin_field')),
    pin,
  );
  await tester.tap(find.byKey(
    const Key('crypto_backup_reveal_pin_submit_button'),
  ));
  await tester.pumpAndSettle();
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('V1 — Detail initially hides secret', () {
    testWidgets('detail dialog does not render the secret on open',
        (tester) async {
      await _pump(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
      );
      await _openBackupDetail(tester);
      
      expect(
        find.byKey(const Key('crypto_backup_revealed_panel')),
        findsNothing,
      );
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        expect((t.data ?? '').contains(_RECOVERY_PHRASE), isFalse,
            reason: 'detail dialog must NEVER render the secret '
                'before reveal');
      }
    });
  });

  
  group('V2 — Reveal button visibility', () {
    testWidgets(
      'reveal button renders when onReveal is wired; legacy '
      'notice gone',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_button')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_cta')),
          findsOneWidget,
        );
        
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_notice')),
          findsNothing,
        );
        
        expect(
          find.text(kCryptoBackupRevealPanelTitle),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoBackupRevealPanelBody),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'legacy notice persists when onReveal is null',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          
        );
        await _openBackupDetail(tester);
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_notice')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_button')),
          findsNothing,
        );
      },
    );
  });

  
  group('V3/V4 — Strong warning', () {
    testWidgets(
      'reveal opens warning dialog with both pinned fragments',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_reveal_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_backup_reveal_warning_dialog')),
          findsOneWidget,
        );
        
        expect(
          find.text(kCryptoRevealWarningBodyA),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoRevealWarningBodyB),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Cancel from warning does NOT open PIN dialog',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_reveal_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key(
          'crypto_backup_reveal_warning_cancel'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_backup_reveal_pin_dialog')),
          findsNothing,
        );
      },
    );
  });

  
  group('V5 — PIN dialog opens', () {
    testWidgets(
      'continue from warning opens PIN dialog with PIN field',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_reveal_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_backup_reveal_warning_continue'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(
            const Key('crypto_backup_reveal_pin_dialog')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('crypto_backup_reveal_pin_field')),
          findsOneWidget,
        );
      },
    );
  });

  
  group('V6 — Wrong PIN safe error', () {
    testWidgets(
      'reveal callback throws → safe error rendered, no secret '
      'on screen, PIN field cleared',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async {
            throw Exception('Reveal sensitive backup failed: 401');
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: 'wrong');
        
        expect(
          find.byKey(
            const Key('crypto_backup_reveal_pin_error_text')),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoRevealPinFailedMessage),
          findsOneWidget,
        );
        
        final pinField = tester.widget<TextField>(find.byKey(
          const Key('crypto_backup_reveal_pin_field')),
        );
        expect(pinField.controller!.text, '');
        
        expect(
          find.byKey(const Key('crypto_backup_revealed_panel')),
          findsNothing,
        );
        
        for (final t in tester.widgetList<Text>(find.byType(Text))) {
          expect(
            (t.data ?? '').contains(_RECOVERY_PHRASE), isFalse,
            reason: 'wrong-PIN error must NEVER expose the secret',
          );
        }
      },
    );
  });

  
  group('V7 — Reveal success', () {
    testWidgets(
      'successful reveal displays secret in protected panel',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        expect(
          find.byKey(const Key('crypto_backup_revealed_panel')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
            'crypto_backup_revealed_panel_secret_text')),
          findsOneWidget,
        );
        expect(find.text(_RECOVERY_PHRASE), findsOneWidget);
        
        expect(
          find.byKey(const Key(
            'crypto_backup_revealed_panel_warning_text')),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'seed_phrase secretType renders "Seed phrase" in header',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'seed_phrase',
            'secretValue': _SEED_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        final header = tester.widget<Text>(find.byKey(
          const Key('crypto_backup_revealed_panel_header_text')),
        );
        expect(header.data, contains('Seed phrase'));
      },
    );

    testWidgets(
      'private_key secretType renders "Private key" in header',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'private_key',
            'secretValue': _PRIVATE_KEY,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        final header = tester.widget<Text>(find.byKey(
          const Key('crypto_backup_revealed_panel_header_text')),
        );
        expect(header.data, contains('Private key'));
      },
    );
  });

  
  group('V8 — Hide button', () {
    testWidgets('Hide removes secret from widget tree',
        (tester) async {
      await _pump(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
        onReveal: (rec, pin) async => {
          'secretType':  'recovery_phrase',
          'secretValue': _RECOVERY_PHRASE,
        },
      );
      await _openBackupDetail(tester);
      await _walkRevealFlow(tester, pin: '1234');
      
      expect(find.text(_RECOVERY_PHRASE), findsOneWidget);
      await tester.tap(find.byKey(
        const Key('crypto_backup_revealed_panel_hide_button'),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('crypto_backup_revealed_panel')),
        findsNothing,
      );
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        expect((t.data ?? '').contains(_RECOVERY_PHRASE), isFalse,
            reason: 'after Hide, no Text widget may contain '
                'the secret');
      }
    });
  });

  
  group('V9 — Close dialog wipes secret', () {
    testWidgets('Close button removes secret from widget tree',
        (tester) async {
      await _pump(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
        onReveal: (rec, pin) async => {
          'secretType':  'recovery_phrase',
          'secretValue': _RECOVERY_PHRASE,
        },
      );
      await _openBackupDetail(tester);
      await _walkRevealFlow(tester, pin: '1234');
      await tester.tap(find.byKey(
        const Key('crypto_backup_detail_close_button'),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('crypto_backup_detail_dialog')),
        findsNothing,
      );
      
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        expect((t.data ?? '').contains(_RECOVERY_PHRASE), isFalse);
      }
    });
  });

  
  group('V10 — Copy 2nd confirmation', () {
    testWidgets(
      'tapping Copy secret opens 2nd confirmation dialog before '
      'clipboard write',
      (tester) async {
        String? clipboardSet;
        TestDefaultBinaryMessengerBinding
          .instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform,
            (call) async {
          if (call.method == 'Clipboard.setData') {
            final args = call.arguments as Map?;
            clipboardSet = args?['text'] as String?;
          }
          return null;
        });
        addTearDown(() {
          TestDefaultBinaryMessengerBinding
            .instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              SystemChannels.platform, null);
        });
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        await tester.tap(find.byKey(
          const Key('crypto_backup_revealed_panel_copy_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key(
            'crypto_backup_copy_secret_confirm_dialog')),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoCopySecretConfirmTitle),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoCopySecretConfirmBody),
          findsOneWidget,
        );
        
        expect(clipboardSet, isNull);
        
        await tester.tap(find.byKey(const Key(
          'crypto_backup_copy_secret_confirm_cancel'),
        ));
        await tester.pumpAndSettle();
        expect(clipboardSet, isNull);
      },
    );
  });

  
  group('V11 — Copy toast safety', () {
    testWidgets(
      'confirmed copy writes secret to clipboard + toast does '
      'NOT echo secret',
      (tester) async {
        String? clipboardSet;
        TestDefaultBinaryMessengerBinding
          .instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform,
            (call) async {
          if (call.method == 'Clipboard.setData') {
            final args = call.arguments as Map?;
            clipboardSet = args?['text'] as String?;
          }
          return null;
        });
        addTearDown(() {
          TestDefaultBinaryMessengerBinding
            .instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              SystemChannels.platform, null);
        });
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        await tester.tap(find.byKey(
          const Key('crypto_backup_revealed_panel_copy_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key(
          'crypto_backup_copy_secret_confirm_copy'),
        ));
        await tester.pump();
        
        expect(clipboardSet, _RECOVERY_PHRASE);
        
        expect(
          find.byKey(const Key('crypto_backup_copy_secret_toast')),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoCopySecretDoneToast),
          findsOneWidget,
        );
        for (final t in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key('crypto_backup_copy_secret_toast')),
            matching: find.byType(Text),
          ),
        )) {
          expect((t.data ?? '').contains(_RECOVERY_PHRASE), isFalse,
              reason: 'copy toast must NEVER echo the secret');
        }
      },
    );
  });

  
  group('V12 — Anti-claim guard on reveal flow', () {
    testWidgets(
      'reveal panel contains no Show QR / send / import / connect / '
      'buy / sell / swap / create-wallet / sign / broadcast copy',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
        );
        await _openBackupDetail(tester);
        await _walkRevealFlow(tester, pin: '1234');
        for (final t in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key('crypto_backup_revealed_panel')),
            matching: find.byType(Text),
          ),
        )) {
          final body = (t.data ?? '').toLowerCase();
          for (final needle in const [
            'show qr', 'send crypto', 'send btc', 'send eth',
            'buy crypto', 'sell crypto', 'swap crypto',
            'trade crypto', 'create wallet', 'create a wallet',
            'wallet generation', 'broadcast transaction',
            'sign transaction', 'connect metamask',
            'import wallet', 'import key',
          ]) {
            expect(body.contains(needle), isFalse,
                reason: 'revealed panel must NOT contain '
                    '"$needle"; found in "$body"');
          }
        }
      },
    );
  });

  
  group('V13 — Mobile reveal flow', () {
    testWidgets('reveal panel renders at 360 px without overflow',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: [_backupRecord()],
            onLoadCryptoRecordDetail: (rec) async => _backupDetail(),
            onRevealCryptoSensitiveBackup: (rec, pin) async => {
              'secretType':  'recovery_phrase',
              'secretValue': _RECOVERY_PHRASE,
            },
            onDirectSaveWalletProfile: (_) async {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_s1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
      await tester.pumpAndSettle();
      await _walkRevealFlow(tester, pin: '1234');
      expect(
        find.byKey(const Key('crypto_backup_revealed_panel')),
        findsOneWidget,
      );
    });
  });

  
  group('V14 — Wallet profile detail unchanged', () {
    testWidgets(
      'wallet detail still has Show QR + Copy address; no reveal '
      'flow appears on a wallet card',
      (tester) async {
        bool qrCalled = false;
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onReveal: (rec, pin) async => {
            'secretType':  'recovery_phrase',
            'secretValue': _RECOVERY_PHRASE,
          },
          onShowQR: (_) => qrCalled = true,
        );
        await tester.tap(find.byKey(const Key('crypto_card_view_w1')));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_wallet_detail_dialog')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_wallet_detail_show_qr_button')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_wallet_detail_copy_button')),
          findsOneWidget,
        );
        
        expect(
          find.byKey(
            const Key('crypto_backup_detail_reveal_button')),
          findsNothing,
        );
        
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_show_qr_button')),
        );
        await tester.pumpAndSettle();
        expect(qrCalled, isTrue);
      },
    );
  });
}
