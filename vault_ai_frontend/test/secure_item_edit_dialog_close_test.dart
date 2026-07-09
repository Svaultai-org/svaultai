

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';


Future<void> _showDialog(
  WidgetTester tester, {
  required String title,
  required String itemType,
  required SecureItemEditSaveHandler onSave,
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 800));
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: Builder(
        builder: (ctx) => Center(
          child: ElevatedButton(
            key: const Key('open_dialog'),
            onPressed: () {
              showSecureItemEditDialog(
                ctx,
                title:    title,
                itemType: itemType,
                onSave:   onSave,
              );
            },
            child: const Text('Open'),
          ),
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('open_dialog')));
  await tester.pumpAndSettle();
}





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('Edit dialog closes on save success', () {
    testWidgets(
      'success path: dialog disappears after the Save tap settles',
      (tester) async {
        int saveCalls = 0;
        await _showDialog(
          tester,
          title: 'iPhone IMEI',
          itemType: 'imei',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            saveCalls += 1;
            return true;
          },
        );
        
        expect(find.byKey(const Key('secure_item_edit_title')),
            findsOneWidget);
        expect(find.byKey(const Key('secure_item_edit_save')),
            findsOneWidget);

        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();

        
        expect(find.byKey(const Key('secure_item_edit_title')),
            findsNothing);
        expect(find.byKey(const Key('secure_item_edit_save')),
            findsNothing);
        expect(saveCalls, 1);
      },
    );

    testWidgets(
      'error path: dialog stays open, Save button is tappable again',
      (tester) async {
        int saveCalls = 0;
        await _showDialog(
          tester,
          title: 'iPhone IMEI',
          itemType: 'imei',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            saveCalls += 1;
            return false; 
          },
        );
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();

        
        expect(find.byKey(const Key('secure_item_edit_title')),
            findsOneWidget);
        expect(find.byKey(const Key('secure_item_edit_save')),
            findsOneWidget);
        
        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(saveCalls, 2);
      },
    );

    testWidgets(
      'thrown exception path: dialog stays open, Save still tappable',
      (tester) async {
        int saveCalls = 0;
        await _showDialog(
          tester,
          title: 'Norton Key',
          itemType: 'license_key',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            saveCalls += 1;
            throw Exception('network down');
          },
        );
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();

        
        expect(find.byKey(const Key('secure_item_edit_title')),
            findsOneWidget);
        expect(find.byKey(const Key('secure_item_edit_save')),
            findsOneWidget);
        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(saveCalls, 2);
      },
    );

    testWidgets(
      'no duplicate save: rapid double tap during in-flight save fires once',
      (tester) async {
        int saveCalls = 0;
        final completer = Completer<bool>();
        await _showDialog(
          tester,
          title: 'Netflix',
          itemType: 'login',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            saveCalls += 1;
            return completer.future;
          },
        );
        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pump();
        
        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pump();
        expect(saveCalls, 1);
        
        completer.complete(true);
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('secure_item_edit_save')),
            findsNothing);
      },
    );
  });


  group('main.dart wiring — refresh runs unawaited', () {
    test('main.dart uses unawaited() to refresh after save success', () {
      
      
      final src = File(
        Directory.current.path + '/lib/main.dart',
      ).readAsStringSync();
      
      
      final exec = src.replaceAll(
        RegExp(r'//[^\n]*'), '',
      );
      expect(
        exec,
        contains('unawaited(_loadVaultLogins())'),
        reason:
            'main.dart must refresh the Logins list AFTER the '
            'dialog returns — operator brief Bug 1: no stuck '
            'modal overlay.',
      );
    });
  });
}
