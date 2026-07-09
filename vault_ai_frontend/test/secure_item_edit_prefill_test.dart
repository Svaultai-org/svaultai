

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';


Future<void> _pump(WidgetTester tester, Widget body) async {
  await tester.binding.setSurfaceSize(const Size(900, 800));
  await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,home: Scaffold(body: body)));
  await tester.pumpAndSettle();
}





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('SecureItemEditDialog — initialFields prefill', () {
    testWidgets('login dialog prefills username + password', (tester) async {
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Instagram',
          itemType: 'login',
          initialFields: const {
            'username': 'snoworchard686',
            'password': 'YOWlu)c*XlqDjw6z%w6V',
          },
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async => true,
        ),
      );
      
      final username = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_username')),
      );
      expect(username.controller?.text, 'snoworchard686');
      
      final pw = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_password')),
      );
      expect(pw.controller?.text, 'YOWlu)c*XlqDjw6z%w6V');
      expect(pw.obscureText, isTrue);
    });

    testWidgets('IMEI dialog prefills imei_1', (tester) async {
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
          initialFields: const {'imei_1': '352099001761481'},
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async => true,
        ),
      );
      final imei = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_imei_1')),
      );
      expect(imei.controller?.text, '352099001761481');
    });

    testWidgets('private note dialog prefills private_value',
        (tester) async {
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Bag combo',
          itemType: 'private_note',
          initialFields: const {
            'private_value': 'blue tiger sleeps under the willow',
          },
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async => true,
        ),
      );
      final note = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_private_value')),
      );
      expect(note.controller?.text,
          'blue tiger sleeps under the willow');
    });

    testWidgets('license_key dialog prefills license_key',
        (tester) async {
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Norton Key',
          itemType: 'license_key',
          initialFields: const {'license_key': 'NRT-AAAA-BBBB-CCCC'},
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async => true,
        ),
      );
      final key = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_license_key')),
      );
      expect(key.controller?.text, 'NRT-AAAA-BBBB-CCCC');
    });

    testWidgets('extra initialFields keys are silently ignored',
        (tester) async {
      
      
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
          initialFields: const {
            'imei_1':   '352099001761481',
            'username': 'should-be-ignored',
            'password': 'should-be-ignored',
            'category': 'imei',
            'title':    'iPhone 15 IMEI',
          },
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async => true,
        ),
      );
      final imei = tester.widget<TextField>(
        find.byKey(const Key('secure_item_edit_imei_1')),
      );
      expect(imei.controller?.text, '352099001761481');
      
      
      expect(
        find.byKey(const Key('secure_item_edit_username')),
        findsNothing,
      );
    });

    testWidgets(
      'no initialFields → all per-type controllers start empty '
      '(legacy behavior preserved)',
      (tester) async {
        await _pump(
          tester,
          SecureItemEditDialog(
            title: 'Instagram',
            itemType: 'login',
            onSave: ({
              required String oldTitle,
              required String itemType,
              required String newTitle,
              required Map<String, String> fields,
            }) async => true,
          ),
        );
        final username = tester.widget<TextField>(
          find.byKey(const Key('secure_item_edit_username')),
        );
        expect(username.controller?.text, '');
      },
    );
  });


  group('SecureItemEditDialog — save round-trips prefilled values',
      () {
    testWidgets(
      'unchanged prefilled login Save sends the original values',
      (tester) async {
        Map<String, String>? saved;
        await _pump(
          tester,
          SecureItemEditDialog(
            title: 'Instagram',
            itemType: 'login',
            initialFields: const {
              'username': 'snoworchard686',
              'password': 'YOWlu)c*XlqDjw6z%w6V',
            },
            onSave: ({
              required String oldTitle,
              required String itemType,
              required String newTitle,
              required Map<String, String> fields,
            }) async {
              saved = fields;
              return true;
            },
          ),
        );
        
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        
        
        expect(saved, isNotNull);
        expect(saved!['username'], 'snoworchard686');
        expect(saved!['password'], 'YOWlu)c*XlqDjw6z%w6V');
      },
    );
  });


  group('Source-level guards — main.dart fetches before opening',
      () {
    String _read(String relativePath) {
      return File(
        Directory.current.path + '/' + relativePath,
      ).readAsStringSync();
    }

    String _stripDartComments(String src) {
      src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
      src = src.replaceAll(RegExp(r'//[^\n]*'), '');
      return src;
    }

    test('api_client.dart declares getVaultSecureItem', () {
      final src = _read('lib/api_client.dart');
      final exec = _stripDartComments(src);
      expect(
        exec,
        contains('Future<Map<String, dynamic>> getVaultSecureItem('),
        reason:
            'api_client.dart must declare the fetch helper so '
            'the Edit dialog can pre-fill from the backend.',
      );
      
      expect(exec, contains('/get-secure-item'));
    });

    test('main.dart calls getVaultSecureItem before showing dialog',
        () {
      final src = _read('lib/main.dart');
      final exec = _stripDartComments(src);
      
      
      expect(exec, contains('client.getVaultSecureItem('));
      
      expect(exec, contains('initialFields:'));
    });

    test('secure_item_detail.dart wires initialFields into controllers',
        () {
      final src = _read('lib/ui/secure_item_detail.dart');
      final exec = _stripDartComments(src);
      expect(exec, contains('initialFields'));
      
      
      expect(
        exec,
        contains("TextEditingController(text: init[f.key] ?? '')"),
      );
    });
  });
}
