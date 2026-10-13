import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/memory_title_identity.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';

class _MemoryClient extends VaultAIClient {
  _MemoryClient() : super(baseUrl: 'https://synthetic.invalid');

  final rows = <Map<String, dynamic>>[];
  Object? saveFailure;
  int saves = 0;

  @override
  Future<Map<String, dynamic>> listZkMemories({
    required String authToken,
    int limit = 200,
  }) async =>
      {
        'items': rows,
        'counts': {'note': rows.length}
      };

  @override
  Future<void> upsertZkMemory({
    required String authToken,
    required Map<String, dynamic> data,
    String? memoryId,
  }) async {
    saves++;
    if (saveFailure != null) throw saveFailure!;
    rows.add({
      ...data,
      'id': 'synthetic-$saves',
      'updated_at': '2026-10-12T00:00:00Z'
    });
  }
}

Future<void> _open(WidgetTester tester, _MemoryClient client,
    {Size size = const Size(900, 800)}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    locale: const Locale('en'),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
        body: MemoryPage(
      client: client,
      authToken: 'synthetic-only',
      vaultName: 'Synthetic only',
      isMobile: size.width < 600,
    )),
  ));
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(ElevatedButton, 'New memory'));
  await tester.pumpAndSettle();
}

Future<void> _fill(WidgetTester tester, String title) async {
  await tester.enterText(find.byKey(const Key('memory_dialog_title')), title);
  await tester.enterText(
      find.byKey(const Key('memory_dialog_value')), 'Synthetic content only');
}

void main() {
  testWidgets(
      'actual New memory Save writes once then closes with confirmation',
      (tester) async {
    final client = _MemoryClient();
    await _open(tester, client);
    await _fill(tester, 'QA synthetic memory');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.saves, 1);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('Memory saved'), findsOneWidget);
    expect(find.text('QA synthetic memory'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'actual New memory request failure displays safe visible feedback',
      (tester) async {
    final client = _MemoryClient()
      ..saveFailure = StateError('synthetic-secret-not-for-ui');
    await _open(tester, client);
    await _fill(tester, 'QA synthetic failure');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.saves, 1);
    expect(find.text('Could not save memory').hitTestable(), findsOneWidget);
    expect(find.text('Memory saved'), findsNothing);
    expect(find.textContaining('synthetic-secret'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('server duplicate is visible and never claims memory saved',
      (tester) async {
    final client = _MemoryClient()
      ..saveFailure = const MemoryTitleConflictException();
    await _open(tester, client);
    await _fill(tester, 'QA synthetic duplicate');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.saves, 1);
    expect(
        find.text(kMemoryTitleConflictMessage).hitTestable(), findsOneWidget);
    expect(find.text('Memory saved'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('local duplicate warning stays visible on a short phone dialog',
      (tester) async {
    final client = _MemoryClient()
      ..rows.add({
        'id': 'synthetic-existing',
        'title': 'QA duplicate',
        'value': 'Preserved original',
        'memory_type': 'note'
      });
    await _open(tester, client, size: const Size(360, 640));
    await _fill(tester, 'QA duplicate');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.saves, 0);
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(
        find.text(kMemoryTitleConflictMessage).hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty memory validation is visible before any write',
      (tester) async {
    final client = _MemoryClient();
    await _open(tester, client, size: const Size(360, 640));
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), 'QA empty memory');
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(client.saves, 0);
    expect(find.text('Add memory text or a custom field first').hitTestable(),
        findsOneWidget);
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
