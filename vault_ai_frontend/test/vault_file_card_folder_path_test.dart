

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


Future<void> _pumpCard(
  WidgetTester tester, {
  required ChatMessage msg,
  Size viewport = const Size(900, 600),
}) async {
  tester.view.physicalSize = viewport;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });

  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        backgroundColor: const Color(0xFF0F1115),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: VaultFileCard(msg: msg),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


ChatMessage _vaultFileMsg({
  String fileName = 'statement.pdf',
  String mimeType = 'application/pdf',
  String? relativePath,
  String? assetType = 'file',
}) {
  final payload = <String, dynamic>{};
  if (relativePath != null) payload['relative_path'] = relativePath;
  if (assetType != null) payload['asset_type'] = assetType;
  return ChatMessage(
    'assistant',
    'I found your $fileName.',
    kind: 'vault_file',
    fileId: 'f1',
    fileName: fileName,
    mimeType: mimeType,
    payload: payload.isEmpty ? null : payload,
  );
}


void main() {
  group('VaultFileCard — folder path provenance', () {
    testWidgets('renders the folder path when relative_path is present',
        (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'statement.pdf',
          relativePath: 'Bank/statement.pdf',
        ),
      );
      
      expect(find.text('statement.pdf'), findsOneWidget);
      expect(find.text('Bank/statement.pdf'), findsOneWidget);
      
      expect(find.byIcon(Icons.folder_outlined), findsOneWidget);
    });

    testWidgets('omits the folder line when relative_path is missing',
        (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'loose.pdf',
          relativePath: null,
        ),
      );
      expect(find.text('loose.pdf'), findsOneWidget);
      
      expect(find.byIcon(Icons.folder_outlined), findsNothing);
    });

    testWidgets('omits the folder line for empty relative_path',
        (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'empty.pdf',
          relativePath: '',
        ),
      );
      expect(find.byIcon(Icons.folder_outlined), findsNothing);
    });

    testWidgets('renders a nested folder path on a single line, '
        'ellipsised when overflowing', (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'family.jpg',
          relativePath:
              'My Life Backup/Photos/Family/Christmas 2024/family.jpg',
          mimeType: 'image/jpeg',
          assetType: 'image',
        ),
        viewport: const Size(400, 600),
      );
      
      expect(tester.takeException(), isNull,
          reason: 'nested folder paths must ellipsise rather than overflow');
      
      expect(find.byIcon(Icons.folder_outlined), findsOneWidget);
    });

    testWidgets('mobile viewport with a deep path does not overflow',
        (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'budget.xlsx',
          relativePath:
              'My Life Backup/Finance/2024/Q4/budget.xlsx',
        ),
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('title still shows when only relative_path is supplied '
        'and saved_name is missing', (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileName: 'app.py',
          relativePath: 'Code/app.py',
          assetType: 'file',
        ),
      );
      expect(find.text('app.py'), findsOneWidget);
      expect(find.text('Code/app.py'), findsOneWidget);
    });

    testWidgets('saved_name from payload wins over file_name for the '
        'title; relative_path still renders', (tester) async {
      final msg = ChatMessage(
        'assistant',
        'I found your Bank Statement.',
        kind: 'vault_file',
        fileId: 'f1',
        fileName: 'statement-2024.pdf',
        mimeType: 'application/pdf',
        payload: {
          'saved_name': 'Bank Statement',
          'relative_path': 'Bank/statement-2024.pdf',
        },
      );
      await _pumpCard(tester, msg: msg);
      
      expect(find.text('Bank Statement'), findsOneWidget);
      
      expect(find.text('Bank/statement-2024.pdf'), findsOneWidget);
    });
  });

  group('Source guard: main.dart structured-payload parsing', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('_tryParseAssistantStructuredMessage threads relative_path '
        'into the payload', () {
      final src = readMain();
      
      
      expect(
        src,
        contains("decoded['relative_path']?.toString()"),
        reason: 'parser must read relative_path off the structured '
                'envelope so the card can render it',
      );
      expect(
        src,
        contains("payload['relative_path'] = relativePath"),
        reason: 'parser must thread relative_path into the message '
                'payload — VaultFileCard reads from there',
      );
    });

    test('parser omits payload key when relative_path is empty/null',
        () {
      final src = readMain();
      
      
      expect(
        src,
        contains(
            "if (relativePath != null && relativePath.isNotEmpty)"),
        reason: 'empty / null relative_path must not pollute the '
                'payload — the card would render an empty path row',
      );
    });

    test('parser threads asset_type as well for icon fallback', () {
      final src = readMain();
      expect(
        src,
        contains("decoded['asset_type']?.toString()"),
        reason: 'asset_type is part of the envelope; the card uses '
                'it for the icon when mime is generic',
      );
    });
  });

  group('Source guard: VaultFileCard reads payload[relative_path]', () {
    test('card body reads relative_path from payload', () {
      final file = File('lib/ui/chat/chat_cards.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(
        src,
        contains("p['relative_path']"),
        reason: 'card must read relative_path off the payload map',
      );
      expect(
        src,
        contains('Icons.folder_outlined'),
        reason: 'card must use the folder icon for the path line',
      );
    });
  });
}
