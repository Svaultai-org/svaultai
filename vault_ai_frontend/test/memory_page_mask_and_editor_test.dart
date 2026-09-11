import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';

const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

class _MemoryFakeClient extends VaultAIClient {
  _MemoryFakeClient() : super(baseUrl: 'http://localhost.invalid');

  @override
  Future<Map<String, dynamic>> listZkMemories({
    required String authToken,
    int limit = 200,
  }) async {
    return {
      'items': [
        {
          'id': '1',
          'title': 'OpenAI API key',
          'value': 'sk-memory-marker-123',
          'body': 'Project access',
          'memory_type': 'note',
          'category': 'project',
          'tags': ['api'],
          'custom_fields': [
            {'label': 'Server IP', 'value': '10.50.60.70'},
          ],
          'updated_at': '2026-07-27T10:00:00Z',
        },
      ],
      'counts': {'note': 1},
    };
  }
}

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(900, 800),
}) async {
  await tester.binding.setSurfaceSize(size);
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(body: child),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('MemoryPage saved row does not overflow on narrow iPhones',
      (tester) async {
    await _pump(
      tester,
      MemoryPage(
        client: _MemoryFakeClient(),
        authToken: 'tok',
        vaultName: 'vault',
        isMobile: true,
        pinProvider: () async => '1234',
      ),
      size: const Size(402, 874),
    );

    expect(find.text('OpenAI API key'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byKey(const Key('memory_row_reveal_1')));
    await tester.pumpAndSettle();

    expect(find.textContaining('sk-memory-marker-123'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('MemoryPage masks row values until row-scoped reveal',
      (tester) async {
    await _pump(
      tester,
      MemoryPage(
        client: _MemoryFakeClient(),
        authToken: 'tok',
        vaultName: 'vault',
        isMobile: false,
        pinProvider: () async => '1234',
      ),
    );

    expect(find.text('OpenAI API key'), findsOneWidget);
    expect(find.text('Memory value hidden'), findsOneWidget);
    expect(find.textContaining('sk-memory-marker-123'), findsNothing);
    expect(find.textContaining('10.50.60.70'), findsNothing);

    await tester.tap(find.byKey(const Key('memory_row_reveal_1')));
    await tester.pumpAndSettle();

    expect(find.textContaining('sk-memory-marker-123'), findsWidgets);
    expect(find.textContaining('Server IP: 10.50.60.70'), findsOneWidget);

    await tester.tap(find.byKey(const Key('memory_row_hide_1')));
    await tester.pumpAndSettle();

    expect(find.text('Memory value hidden'), findsOneWidget);
    expect(find.textContaining('sk-memory-marker-123'), findsNothing);
    expect(find.textContaining('10.50.60.70'), findsNothing);
  });

  testWidgets('Memory editor returns generic fields, tags, and custom fields',
      (tester) async {
    Map<String, dynamic>? saved;
    await _pump(
      tester,
      Builder(
        builder: (ctx) => ElevatedButton(
          onPressed: () async {
            saved = await showMemoryEditorDialog(ctx);
          },
          child: const Text('open'),
        ),
      ),
    );

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('memory_dialog_title')),
      'Home Wi-Fi',
    );
    await tester.enterText(
      find.byKey(const Key('memory_dialog_value')),
      'Main router details',
    );
    await tester.enterText(
      find.byKey(const Key('memory_dialog_tags')),
      'wifi, home',
    );
    await tester.tap(find.byKey(const Key('memory_dialog_add_field')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('memory_dialog_custom_label_0')),
      'Password',
    );
    await tester.enterText(
      find.byKey(const Key('memory_dialog_custom_value_0')),
      'wifi-secret',
    );
    final customValue = tester.widget<TextField>(
      find.byKey(const Key('memory_dialog_custom_value_0')),
    );
    expect(customValue.obscureText, isTrue);

    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();

    expect(saved, isNotNull);
    expect(saved!['title'], 'Home Wi-Fi');
    expect(saved!['value'], 'Main router details');
    expect(saved!['tags'], ['wifi', 'home']);
    expect(saved!['custom_fields'], [
      {'label': 'Password', 'value': 'wifi-secret'},
    ]);
  });
}
