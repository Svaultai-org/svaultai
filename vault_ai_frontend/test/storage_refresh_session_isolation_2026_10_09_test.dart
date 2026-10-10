import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/storage_page.dart';

// In-process billing reads only; no store, account or production mutation.
const _oldToken = 'synthetic-old-storage-session';
const _newToken = 'synthetic-new-storage-session';
const _newLimit = 100 * kVaultStorageLimitBytes;

Map<String, dynamic> _billing(int blocks) => {
      'included_bytes': kVaultStorageLimitBytes,
      'effective_limit_bytes': blocks * 50 * kVaultStorageLimitBytes,
      'purchased_bytes': blocks * 50 * kVaultStorageLimitBytes,
      'block_count': blocks,
      'used_bytes': 0,
      'percent_used': 0,
      'source': 'apple',
      'status': 'active',
    };

http.Response _response(int blocks) => http.Response(
      jsonEncode(_billing(blocks)),
      200,
      headers: {'content-type': 'application/json'},
    );

Widget _page(AppState app) => ChangeNotifierProvider<AppState>.value(
      value: app,
      child: const MaterialApp(
        locale: Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: StoragePage(),
      ),
    );

void _installNewSession(AppState app) {
  app.sessionToken = _newToken;
  app.applyBillingPayload(_billing(2));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final error in [false, true]) {
    testWidgets(
      'late old-vault ${error ? 'error' : 'success'} cannot change new-session billing or page',
      (tester) async {
        final app = AppState()..sessionToken = _oldToken;
        final delayed = Completer<http.Response>();
        final requests = <http.Request>[];
        final client = MockClient((request) {
          requests.add(request);
          expect(request.method, 'GET');
          expect(request.url.path, '/billing/me');
          expect(request.headers['Authorization'], 'Bearer $_oldToken');
          return delayed.future;
        });
        await http.runWithClient(() async {
          await tester.pumpWidget(_page(app));
          await tester.pump();
          expect(requests, hasLength(1));
          _installNewSession(app);
          await tester.pump();
          delayed.complete(error
              ? http.Response('{"detail":"synthetic old billing failure"}', 500)
              : _response(1));
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 50));

          expect(app.sessionToken, _newToken);
          expect(app.billingEffectiveLimitBytes, _newLimit);
          expect(app.billingBlockCount, 2);
          expect(app.billingLoadState, BillingLoadState.loaded);
          expect(app.billingLoadError, isNull);
          expect(find.byType(StorageBody), findsNothing);
          expect(find.byType(CircularProgressIndicator), findsOneWidget);
          expect(find.textContaining('Could not load storage:'), findsNothing);
          expect(requests, hasLength(1));
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox.shrink());
        }, () => client);
        app.dispose();
      },
    );
  }

  testWidgets('current-session success still applies authoritative quota',
      (tester) async {
    final app = AppState()..sessionToken = _newToken;
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer $_newToken');
      expect(request.method, 'GET');
      expect(request.url.path, '/billing/me');
      return _response(2);
    });
    await http.runWithClient(() async {
      await tester.pumpWidget(_page(app));
      await tester.pumpAndSettle();
      expect(app.billingEffectiveLimitBytes, _newLimit);
      expect(app.billingBlockCount, 2);
      expect(find.byType(StorageBody), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    }, () => client);
    app.dispose();
  });

  testWidgets('current-session failure still shows a retryable storage error',
      (tester) async {
    final app = AppState()..sessionToken = _newToken;
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer $_newToken');
      expect(request.method, 'GET');
      expect(request.url.path, '/billing/me');
      return http.Response('{"detail":"synthetic current failure"}', 500);
    });
    await http.runWithClient(() async {
      await tester.pumpWidget(_page(app));
      await tester.pumpAndSettle();
      expect(find.textContaining('Could not load storage:'), findsOneWidget);
      expect(find.byType(StorageBody), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(app.sessionToken, _newToken);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    }, () => client);
    app.dispose();
  });
}
