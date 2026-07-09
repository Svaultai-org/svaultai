

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


const String _ETH_ADDR_A =
    '0x0000000000000000000000000000000000000001';
const String _ETH_ADDR_B =
    '0x0000000000000000000000000000000000000002';
const String _TRC20_ADDR = 'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY';
const String _RECOVERY_PHRASE =
    'abandon abandon abandon abandon abandon abandon '
    'abandon abandon abandon abandon abandon about';


Map<String, dynamic> _walletRecord({
  String itemId = 'w1',
  String title = 'MetaMask Ethereum wallet',
  String network = 'Ethereum',
}) {
  return <String, dynamic>{
    'item_id':        itemId,
    'type':           'crypto_wallet_address',
    'title':          title,
    'category_label': 'Crypto wallet',
    'preview': {
      'wallet_address_mask': '0x0000…0001',
      'network':             network,
    },
  };
}


Map<String, dynamic> _walletDetail({
  String address = _ETH_ADDR_A,
  String label = 'MetaMask',
  String asset = 'ETH',
  String network = 'Ethereum',
  String? note,
}) {
  return <String, dynamic>{
    'service':   'MetaMask Ethereum wallet',
    'item_type': 'crypto_wallet_address',
    'fields': {
      'wallet_address': address,
      'network':        network,
      'wallet_label':   label,
      'asset':          asset,
      'balance_status': 'lookup_not_connected',
    },
    if (note != null) 'notes': note,
  };
}


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


Map<String, dynamic> _backupDetail({
  String secretType = 'recovery_phrase',
}) {
  return <String, dynamic>{
    'service':   'Ledger BTC recovery',
    'item_type': 'crypto_recovery_phrase',
    'fields': {
      'recovery_phrase': _RECOVERY_PHRASE,
      'network':         'Bitcoin',
      'wallet_label':    'Ledger',
      'asset':           'BTC',
      'secret_type':     secretType,
    },
    'notes': 'cold storage',
  };
}


Future<void> _pump(
  WidgetTester tester, {
  required List<Map<String, dynamic>> savedRecords,
  Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
  )? onLoadDetail,
  Future<void> Function(
    Map<String, dynamic> record,
    CryptoAddWalletDraft edits,
  )? onUpdate,
  Future<void> Function(
    Map<String, dynamic> record,
    CryptoBackupMetadataEdit edits,
  )? onUpdateBackup,
  Future<void> Function(Map<String, dynamic> record)? onDelete,
  void Function(Map<String, dynamic> record)? onShowQR,
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords:                savedRecords,
        onLoadCryptoRecordDetail:    onLoadDetail,
        onUpdateCryptoWalletProfile: onUpdate,
        onUpdateCryptoBackupMetadata: onUpdateBackup,
        onDeleteCryptoRecord:        onDelete,
        onShowQR:                    onShowQR,
        
        
        onDirectSaveWalletProfile:   (_) async {},
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


Future<void> _openWalletDetail(
  WidgetTester tester, {
  required Map<String, dynamic> record,
}) async {
  
  await tester.tap(find.byKey(Key('crypto_card_view_${record["item_id"]}')));
  await tester.pumpAndSettle();
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('D1 — Wallet detail dialog opens', () {
    testWidgets('view tap opens detail dialog', (tester) async {
      await _pump(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(),
      );
      await _openWalletDetail(tester, record: _walletRecord());
      expect(
        find.byKey(const Key('crypto_wallet_detail_dialog')),
        findsOneWidget,
      );
    });
  });

  
  group('D2 — Detail dialog renders structured fields', () {
    testWidgets('renders title + network + address + note',
        (tester) async {
      await _pump(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(
          note: 'Daily driver',
        ),
      );
      await _openWalletDetail(tester, record: _walletRecord());
      expect(
        find.byKey(const Key('crypto_wallet_detail_title_text')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_detail_network_text')),
        findsOneWidget,
      );
      expect(find.text('Ethereum'), findsAtLeastNWidgets(1));
      
      expect(
        find.byKey(const Key('crypto_wallet_detail_address_text')),
        findsOneWidget,
      );
      expect(find.text(_ETH_ADDR_A), findsOneWidget);
      
      expect(
        find.byKey(const Key('crypto_wallet_detail_note_panel')),
        findsOneWidget,
      );
      expect(find.text('Daily driver'), findsOneWidget);
    });
  });

  
  group('D3 — Copy address', () {
    testWidgets(
      'copy writes address to clipboard + shows toast that does '
      'not echo address',
      (tester) async {
        
        String? clipboardSet;
        TestDefaultBinaryMessengerBinding
          .instance
          .defaultBinaryMessenger
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
            .instance
            .defaultBinaryMessenger
            .setMockMethodCallHandler(
              SystemChannels.platform, null);
        });
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_copy_button'),
        ));
        await tester.pump(); 
        
        expect(clipboardSet, _ETH_ADDR_A);
        
        expect(
          find.byKey(const Key('crypto_wallet_detail_copy_toast')),
          findsOneWidget,
        );
        
        expect(find.text(kCryptoCopyAddressDoneToast), findsOneWidget);
        for (final t in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key('crypto_wallet_detail_copy_toast')),
            matching: find.byType(Text),
          ),
        )) {
          expect((t.data ?? '').contains(_ETH_ADDR_A), isFalse,
              reason: 'copy toast must NEVER echo the address');
        }
      },
    );
  });

  
  group('D4 — Show receive QR on wallet detail', () {
    testWidgets('Show receive QR action exists + fires onShowQR',
        (tester) async {
      Map<String, dynamic>? qrFor;
      await _pump(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(),
        onShowQR: (rec) => qrFor = rec,
      );
      await _openWalletDetail(tester, record: _walletRecord());
      expect(
        find.byKey(const Key('crypto_wallet_detail_show_qr_button')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(
        const Key('crypto_wallet_detail_show_qr_button'),
      ));
      await tester.pumpAndSettle();
      expect(qrFor, isNotNull);
      expect(qrFor!['item_id'], 'w1');
    });
  });

  
  group('D5 — Sensitive backup detail hides Show QR', () {
    testWidgets('backup detail has no Show QR button + no QR icon',
        (tester) async {
      await _pump(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_backup_detail_dialog')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_wallet_detail_show_qr_button')),
        findsNothing,
      );
      
      for (final t in tester.widgetList<Text>(
        find.descendant(
          of: find.byKey(const Key('crypto_backup_detail_dialog')),
          matching: find.byType(Text),
        ),
      )) {
        final body = (t.data ?? '').toLowerCase();
        expect(body.contains('show receive qr'), isFalse,
            reason: 'sensitive backup detail must NEVER offer a '
                'Show receive QR control');
        expect(body.contains('show qr'), isFalse,
            reason: 'sensitive backup detail must NEVER offer a '
                'Show QR control');
      }
    });
  });

  
  group('D6 — Edit opens prefilled Add Wallet dialog', () {
    testWidgets(
      'Edit on detail opens add-wallet dialog with prefilled values',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async =>
              _walletDetail(note: 'Daily driver'),
          onUpdate: (rec, edits) async {},
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_edit_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsOneWidget,
        );
        expect(find.text('Edit crypto wallet'), findsOneWidget);
        
        final addressField = tester.widget<TextField>(
          find.byKey(
            const Key('crypto_lite_add_wallet_address_field'),
          ),
        );
        expect(addressField.controller!.text, _ETH_ADDR_A);
        
        final noteField = tester.widget<TextField>(
          find.byKey(const Key('crypto_lite_add_wallet_note_field')),
        );
        expect(noteField.controller!.text, 'Daily driver');
      },
    );
  });

  
  group('D7 — Edit save routes to update callback', () {
    testWidgets(
      'Save on prefilled dialog calls onUpdate with record + draft',
      (tester) async {
        Map<String, dynamic>? capturedRecord;
        CryptoAddWalletDraft? capturedDraft;
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onUpdate: (rec, draft) async {
            capturedRecord = rec;
            capturedDraft  = draft;
          },
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_edit_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.enterText(
          find.byKey(
            const Key('crypto_lite_add_wallet_address_field'),
          ),
          _ETH_ADDR_B,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(capturedRecord, isNotNull);
        expect(capturedRecord!['item_id'], 'w1');
        expect(capturedDraft, isNotNull);
        expect(capturedDraft!.address, _ETH_ADDR_B);
        expect(capturedDraft!.asset.id, 'eth');
        expect(capturedDraft!.label.id, 'metamask');
      },
    );
  });

  
  group('D8 — Delete wallet opens confirm dialog', () {
    testWidgets(
      'Delete on detail opens confirm dialog with the '
      'does-not-affect-blockchain copy',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onDelete: (rec) async {},
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_delete_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(
            const Key('crypto_delete_wallet_confirm_dialog')),
          findsOneWidget,
        );
        
        expect(find.text(kCryptoDeleteWalletTitle), findsOneWidget);
        final body = tester.widget<Text>(find.byKey(
          const Key(
            'crypto_delete_wallet_confirm_dialog_body'),
        ));
        for (final fragment in const [
          'only removes the saved record from VaultAI',
          'does NOT affect the actual blockchain wallet',
        ]) {
          expect(body.data, contains(fragment));
        }
      },
    );
  });

  
  group('D9 — Delete confirm calls onDelete', () {
    testWidgets(
      'Confirming delete calls onDeleteCryptoRecord with the record',
      (tester) async {
        Map<String, dynamic>? captured;
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onDelete: (rec) async {
            captured = rec;
          },
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_delete_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key(
          'crypto_delete_wallet_confirm_dialog_confirm'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isNotNull);
        expect(captured!['item_id'], 'w1');
      },
    );

    testWidgets('Cancel does NOT call onDelete', (tester) async {
      bool called = false;
      await _pump(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(),
        onDelete: (rec) async => called = true,
      );
      await _openWalletDetail(tester, record: _walletRecord());
      await tester.tap(find.byKey(
        const Key('crypto_wallet_detail_delete_button'),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key(
        'crypto_delete_wallet_confirm_dialog_cancel'),
      ));
      await tester.pumpAndSettle();
      expect(called, isFalse);
    });
  });

  
  group('D10 — Sensitive backup detail safety', () {
    testWidgets(
      'backup detail does NOT render secret value and shows '
      'reveal-not-available notice',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
        );
        await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_backup_detail_dialog')),
          findsOneWidget,
        );
        
        for (final t in tester.widgetList<Text>(find.byType(Text))) {
          expect((t.data ?? '').contains(_RECOVERY_PHRASE), isFalse,
              reason: 'backup detail MUST NEVER render the '
                  'cleartext secret value');
        }
        
        expect(
          find.byKey(const Key(
            'crypto_backup_detail_reveal_notice')),
          findsOneWidget,
        );
        expect(find.text(kCryptoBackupRevealNotice), findsOneWidget);
      },
    );
  });

  
  group('D11 — Sensitive backup detail action row', () {
    testWidgets(
      'Edit metadata + Delete present; Show QR absent',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onUpdateBackup: (rec, edits) async {},
          onDelete: (rec) async {},
        );
        await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_backup_detail_edit_button')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
            'crypto_backup_detail_delete_button')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
            'crypto_wallet_detail_show_qr_button')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'Edit metadata opens dialog without secret-value field',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onUpdateBackup: (rec, edits) async {},
        );
        await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_edit_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_backup_edit_metadata_dialog')),
          findsOneWidget,
        );
        
        expect(
          find.byKey(const Key(
            'crypto_lite_add_sensitive_backup_value_field')),
          findsNothing,
        );
      },
    );
  });

  
  group('D12 — Sensitive backup delete confirmation', () {
    testWidgets(
      'Delete on backup detail opens dialog with the '
      'make-sure-you-have-another-backup copy',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_backupRecord()],
          onLoadDetail: (rec) async => _backupDetail(),
          onDelete: (rec) async {},
        );
        await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_delete_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_delete_backup_confirm_dialog')),
          findsOneWidget,
        );
        expect(find.text(kCryptoDeleteBackupTitle), findsOneWidget);
        final body = tester.widget<Text>(find.byKey(
          const Key(
            'crypto_delete_backup_confirm_dialog_body'),
        ));
        for (final fragment in const [
          'does not affect the original wallet',
          'have another backup',
        ]) {
          expect(body.data, contains(fragment));
        }
      },
    );
  });

  
  group('D13 — Anti-claim guard', () {
    testWidgets(
      'wallet detail + delete confirm contain no prohibited copy',
      (tester) async {
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onUpdate: (rec, draft) async {},
          onDelete: (rec) async {},
          onShowQR: (rec) {},
        );
        await _openWalletDetail(tester, record: _walletRecord());
        for (final t in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key('crypto_wallet_detail_dialog')),
            matching: find.byType(Text),
          ),
        )) {
          final body = (t.data ?? '').toLowerCase();
          for (final needle in const [
            'send crypto', 'send btc', 'send eth',
            'buy crypto', 'sell crypto', 'swap crypto',
            'trade crypto', 'create wallet', 'create a wallet',
            'wallet generation', 'broadcast transaction',
            'sign transaction', 'connect metamask',
          ]) {
            expect(body.contains(needle), isFalse,
                reason: 'wallet detail must NOT contain '
                    '"$needle"; found in "$body"');
          }
        }
      },
    );
  });

  
  group('D14 — Mobile layout', () {
    testWidgets('wallet detail dialog renders at 360 px',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: [_walletRecord()],
            onLoadCryptoRecordDetail: (rec) async => _walletDetail(),
            onDirectSaveWalletProfile: (_) async {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_w1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_w1')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_detail_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('delete wallet confirm dialog renders at 360 px',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: [_walletRecord()],
            onLoadCryptoRecordDetail: (rec) async => _walletDetail(),
            onDeleteCryptoRecord: (rec) async {},
            onDirectSaveWalletProfile: (_) async {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_w1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_w1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_wallet_detail_delete_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_delete_wallet_confirm_dialog')),
        findsOneWidget,
      );
    });
  });

  
  group('D15 — Edit warn-but-allow address mismatch', () {
    testWidgets(
      'edit dialog warns on ETH selected + Tron address, allows '
      'override → onUpdate fires',
      (tester) async {
        CryptoAddWalletDraft? captured;
        await _pump(
          tester,
          savedRecords: [_walletRecord()],
          onLoadDetail: (rec) async => _walletDetail(),
          onUpdate: (rec, draft) async => captured = draft,
        );
        await _openWalletDetail(tester, record: _walletRecord());
        await tester.tap(find.byKey(
          const Key('crypto_wallet_detail_edit_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.enterText(
          find.byKey(
            const Key('crypto_lite_add_wallet_address_field'),
          ),
          _TRC20_ADDR,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key(
            'crypto_lite_add_wallet_format_warning_dialog')),
          findsOneWidget,
        );
        
        await tester.tap(find.byKey(const Key(
          'crypto_lite_add_wallet_format_warning_continue'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isNotNull);
        expect(captured!.address, _TRC20_ADDR);
      },
    );
  });
}
