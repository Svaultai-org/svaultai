import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';

class _PreparedMemoryClient extends VaultAIClient {
  _PreparedMemoryClient() : super(baseUrl: 'https://synthetic.invalid');

  final rows = <Map<String, dynamic>>[{
    'id': 'memory-migrated-42',
    'legacy_memory_id': 42,
    'source_snapshot': List<String>.filled(43, 'S').join(),
    'title': 'Synthetic prepared memory',
    'value': 'Synthetic secret value',
    'memory_type': 'note',
    'updated_at': '2026-11-09T00:00:00Z',
  }];

  @override
  Future<Map<String, dynamic>> listZkMemories({
    required String authToken,
    int limit = 200,
  }) async => {'items': rows, 'counts': {'note': rows.length}};

  @override
  Future<void> upsertZkMemory({
    required String authToken,
    required Map<String, dynamic> data,
    String? memoryId,
  }) async => throw StateError('native V2 edit must not handle prepared source');

  @override
  Future<void> deleteZkMemory({
    required String authToken,
    required String memoryId,
  }) async => throw StateError('native V2 delete must not handle prepared source');
}

void main() {
  testWidgets('prepared Memory edit and delete use owner callbacks',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(900, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final client = _PreparedMemoryClient();
    var edited = 0;
    var deleted = 0;
    await tester.pumpWidget(MaterialApp(
      locale: const Locale('en'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: MemoryPage(
        client: client,
        authToken: 'synthetic-token',
        vaultName: 'synthetic-vault',
        isMobile: false,
        pinProvider: () async => 'synthetic-only',
        editPreparedLegacyMemory: (current, updated) async {
          expect(current['legacy_memory_id'], 42);
          expect(updated['value'], 'Synthetic edited value');
          edited++;
          client.rows[0] = {...current, ...updated};
        },
        deletePreparedLegacyMemory: (current) async {
          expect(current['legacy_memory_id'], 42);
          deleted++;
          client.rows.clear();
        },
      )),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Edit'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('memory_dialog_value')), 'Synthetic edited value',
    );
    await tester.tap(find.byKey(const Key('memory_dialog_save')));
    await tester.pumpAndSettle();
    expect(edited, 1);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byTooltip('Delete'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pumpAndSettle();
    expect(deleted, 1);
    expect(client.rows, isEmpty);
    expect(tester.takeException(), isNull);
  });
}
