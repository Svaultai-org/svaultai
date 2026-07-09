

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/main.dart';


const String _sentinelVaultName = 'zzz-private-brain-vault-xyzq-9876';

Future<void> _pumpUnlockShell(
  WidgetTester tester,
  AppState state, {
  Size? viewport,
}) async {
  if (viewport != null) {
    tester.view.physicalSize = viewport;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: state,
      child: MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
        routes: {
          '/login': (_) => const Scaffold(body: Text('LOGIN_PAGE_SENTINEL')),
        },
        home: const UnlockPage(),
      ),
    ),
  );
  
  
  await tester.pump();
}

AppState _stateWithRememberedVault(String? vaultName) {
  
  
  final s = AppState();
  s.lastVaultName = vaultName;
  return s;
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('UnlockPage runtime privacy', () {
    testWidgets('renders the generic "Welcome back" header', (tester) async {
      final state = _stateWithRememberedVault(_sentinelVaultName);
      await _pumpUnlockShell(tester, state);
      expect(find.text('Welcome back'), findsOneWidget);
    });

    testWidgets('never renders vault_name anywhere in the widget tree',
        (tester) async {
      final state = _stateWithRememberedVault(_sentinelVaultName);
      await _pumpUnlockShell(tester, state);

      
      final textWidgets = tester.widgetList<Text>(find.byType(Text));
      for (final t in textWidgets) {
        final data = t.data ?? t.textSpan?.toPlainText() ?? '';
        expect(
          data.contains(_sentinelVaultName),
          isFalse,
          reason: 'UnlockPage must never display vault_name. Leaked '
                  'string: "$data"',
        );
      }
      
      
      expect(find.textContaining('Welcome back to'), findsNothing);
    });

    testWidgets('offers "Use another vault" link', (tester) async {
      final state = _stateWithRememberedVault(_sentinelVaultName);
      await _pumpUnlockShell(tester, state);
      expect(find.text('Use another vault'), findsOneWidget);
    });

    testWidgets('exposes the PIN field but no vault_name field',
        (tester) async {
      
      
      final state = _stateWithRememberedVault(_sentinelVaultName);
      await _pumpUnlockShell(tester, state);
      expect(find.byType(TextField), findsOneWidget);
      
      
      expect(find.text('Enter your 6–64 digit PIN.'), findsOneWidget);
    });

    testWidgets('mobile viewport renders without showing vault_name',
        (tester) async {
      
      
      final state = _stateWithRememberedVault(_sentinelVaultName);
      await _pumpUnlockShell(tester, state, viewport: const Size(400, 1200));
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.textContaining(_sentinelVaultName), findsNothing);
    });

    testWidgets('redirects to /login when no remembered vault',
        (tester) async {
      
      
      final state = _stateWithRememberedVault(null);
      await _pumpUnlockShell(tester, state);
      
      
      await tester.pumpAndSettle();
      expect(find.text('LOGIN_PAGE_SENTINEL'), findsOneWidget);
    });
  });
}
