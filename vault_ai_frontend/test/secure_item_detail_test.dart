import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/ui/secure_item_detail.dart';

Future<void> _pump(WidgetTester tester, Widget body) async {
  await tester.binding.setSurfaceSize(const Size(900, 800));
  await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: body)));
  await tester.pumpAndSettle();
}

const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

void main() {
  group('SecureItemDetailSheet — Reveal removed (2026-06-29)', () {
    testWidgets('Reveal button NEVER renders, even on a masked card',
        (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
        ),
      );

      expect(find.text('Reveal'), findsNothing);
      expect(
        find.byKey(const Key('secure_item_detail_reveal')),
        findsNothing,
      );
    });

    testWidgets('revealedValue still renders when attached', (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
          revealedValue: '123456789012345',
        ),
      );
      expect(find.text('123456789012345'), findsOneWidget);

      expect(find.text('Reveal'), findsNothing);
    });

    testWidgets('masked-hint copy no longer says "Tap Reveal"', (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Norton key',
          itemType: 'license_key',
        ),
      );

      expect(find.textContaining('Tap Reveal'), findsNothing);
      expect(find.textContaining('Ask your vault'), findsOneWidget);
    });
  });

  group('SecureItemDetailSheet — Copy username (login-only)', () {
    testWidgets('login card shows Copy username when present', (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Netflix',
          itemType: 'login',
          username: 'alice',
        ),
      );
      expect(find.text('Copy username'), findsOneWidget);
    });

    testWidgets('non-login card NEVER shows Copy username', (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
          username: 'alice',
        ),
      );
      expect(find.text('Copy username'), findsNothing);
    });

    testWidgets('login card without username hides Copy username',
        (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Netflix',
          itemType: 'login',
        ),
      );
      expect(find.text('Copy username'), findsNothing);
    });
  });

  group('SecureItemDetailSheet — Copy value (revealed non-login only)', () {
    testWidgets('revealed non-login shows Copy value', (tester) async {
      String? copied;
      await _pump(
        tester,
        SecureItemDetailSheet(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
          revealedValue: '123456789012345',
          onCopyValue: (v) => copied = v,
        ),
      );
      expect(find.text('Copy value'), findsOneWidget);
      await tester.tap(find.byKey(const Key('secure_item_detail_copy_value')));
      await tester.pumpAndSettle();
      expect(copied, '123456789012345');
    });

    testWidgets('masked non-login (no revealedValue) hides Copy value',
        (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'iPhone 15 IMEI',
          itemType: 'imei',
        ),
      );
      expect(find.text('Copy value'), findsNothing);
    });

    testWidgets('revealed LOGIN does not show Copy value', (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Netflix',
          itemType: 'login',
          revealedValue: 'fishfish123',
        ),
      );
      expect(find.text('Copy value'), findsNothing);
    });
  });

  group('SecureItemDetailSheet — Edit / Delete always present', () {
    testWidgets('Edit + Delete render for every item type', (tester) async {
      for (final type in const [
        'login',
        'imei',
        'private_note',
        'license_key',
        'crypto_wallet_address',
        'backup_code',
      ]) {
        await _pump(
          tester,
          SecureItemDetailSheet(
            title: 'Sample',
            itemType: type,
            onEdit: (_, __) {},
            onDelete: (_, __) {},
          ),
        );
        expect(find.text('Edit'), findsOneWidget,
            reason: 'Edit missing for $type');
        expect(find.text('Delete'), findsOneWidget,
            reason: 'Delete missing for $type');
      }
    });
  });

  group('Per-type edit field map', () {
    test('login uses username + password + URL + note', () {
      final fields = secureItemEditFieldsFor('login');
      expect(
        fields.map((f) => f.key).toList(),
        ['username', 'password', 'url', 'note'],
      );
      expect(
        fields.firstWhere((f) => f.key == 'password').obscureText,
        isTrue,
      );
    });

    test('IMEI uses imei_1 + notes (NOT username/password)', () {
      final fields = secureItemEditFieldsFor('imei');
      final keys = fields.map((f) => f.key).toList();
      expect(keys, contains('imei_1'));
      expect(keys, isNot(contains('username')));
      expect(keys, isNot(contains('password')));
    });

    test('private note uses private_value, multiline', () {
      final fields = secureItemEditFieldsFor('private_note');
      expect(fields.length, 1);
      expect(fields.first.key, 'private_value');
      expect(fields.first.maxLines, greaterThan(1));
    });

    test('license key uses license_key field', () {
      final fields = secureItemEditFieldsFor('license_key');
      expect(fields.map((f) => f.key).toList(), contains('license_key'));
    });

    test('backup_code edits the codes block as multiline', () {
      final fields = secureItemEditFieldsFor('backup_code');
      final codes = fields.firstWhere((f) => f.key == 'backup_codes');
      expect(codes.maxLines, greaterThan(1));
    });

    test('non-login categories NEVER include username/password', () {
      for (final type in const [
        'imei',
        'serial_number',
        'private_note',
        'account_note',
        'license_key',
        'product_key',
        'activation_key',
        'private_key',
        'recovery_phrase',
        'backup_code',
      ]) {
        final fields = secureItemEditFieldsFor(type);
        final keys = fields.map((f) => f.key).toList();
        expect(keys, isNot(contains('username')),
            reason: '$type must not surface username');
        expect(keys, isNot(contains('password')),
            reason: '$type must not surface password');
      }
    });
  });

  group('SecureItemEditDialog — Save round-trips data', () {
    testWidgets('IMEI save passes new title + imei_1', (tester) async {
      String? savedOldTitle, savedNewTitle, savedType;
      Map<String, String>? savedFields;
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'iPhone IMEI',
          itemType: 'imei',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            savedOldTitle = oldTitle;
            savedNewTitle = newTitle;
            savedType = itemType;
            savedFields = fields;
            return true;
          },
        ),
      );

      await tester.enterText(
        find.byKey(const Key('secure_item_edit_title')),
        'iPhone 15 IMEI',
      );

      await tester.enterText(
        find.byKey(const Key('secure_item_edit_imei_1')),
        '987654321098765',
      );
      await tester.tap(find.byKey(const Key('secure_item_edit_save')));
      await tester.pumpAndSettle();
      expect(savedOldTitle, 'iPhone IMEI');
      expect(savedNewTitle, 'iPhone 15 IMEI');
      expect(savedType, 'imei');
      expect(savedFields, {'imei_1': '987654321098765'});
    });

    testWidgets('Private note save passes new title + private_value',
        (tester) async {
      Map<String, String>? savedFields;
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Secret',
          itemType: 'private_note',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            savedFields = fields;
            return true;
          },
        ),
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_private_value')),
        'blue tiger',
      );
      await tester.tap(find.byKey(const Key('secure_item_edit_save')));
      await tester.pumpAndSettle();
      expect(savedFields, {'private_value': 'blue tiger'});
    });

    testWidgets('Login save still works', (tester) async {
      Map<String, String>? savedFields;
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Netflix',
          itemType: 'login',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            savedFields = fields;
            return true;
          },
        ),
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_username')),
        'alice',
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_password')),
        'fishfish',
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_url')),
        'https://netflix.example',
      );
      await tester.tap(find.byKey(const Key('secure_item_edit_save')));
      await tester.pumpAndSettle();
      expect(savedFields, {
        'username': 'alice',
        'password': 'fishfish',
        'url': 'https://netflix.example',
      });
    });

    testWidgets('Login custom fields round-trip with base fields',
        (tester) async {
      Map<String, String>? savedFields;
      await _pump(
        tester,
        SecureItemEditDialog(
          title: 'Server login',
          itemType: 'login',
          onSave: ({
            required String oldTitle,
            required String itemType,
            required String newTitle,
            required Map<String, String> fields,
          }) async {
            savedFields = fields;
            return true;
          },
        ),
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_username')),
        'deploy',
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_password')),
        'server-secret',
      );
      await tester.tap(find.byKey(const Key('secure_item_edit_add_field')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('secure_item_custom_label_0')),
        'Recovery Code',
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_custom_value_0')),
        'RC-123-456',
      );
      final customValue = tester.widget<TextField>(
        find.byKey(const Key('secure_item_custom_value_0')),
      );
      expect(customValue.obscureText, isTrue);
      await tester.tap(find.byKey(const Key('secure_item_edit_save')));
      await tester.pumpAndSettle();
      expect(savedFields, {
        'username': 'deploy',
        'password': 'server-secret',
        'Recovery Code': 'RC-123-456',
      });
    });
  });

  group('Source-level guards', () {
    test('isSecureItemLoginLike is closed-set', () {
      expect(isSecureItemLoginLike('login'), isTrue);
      expect(isSecureItemLoginLike('credential'), isTrue);
      expect(isSecureItemLoginLike('imei'), isFalse);
      expect(isSecureItemLoginLike('private_note'), isFalse);
      expect(isSecureItemLoginLike('license_key'), isFalse);
      expect(isSecureItemLoginLike('crypto_seed_phrase'), isFalse);
    });

    test('per-type label is closed-set', () {
      expect(
        kSecureItemTypeLabelsForDetail['imei'],
        'Phone IMEI',
      );
      expect(
        kSecureItemTypeLabelsForDetail['license_key'],
        'License key',
      );
      expect(
        kSecureItemTypeLabelsForDetail['private_note'],
        'Private note',
      );
    });
  });
}
