import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/ui/theme.dart';
import 'package:vault_ai_frontend/ui/tokens.dart';

class _ReadyLandingApp extends AppState {
  @override
  bool get hydrated => true;
}

void main() {
  testWidgets('native legacy landing uses readable blue and shared card roles',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final app = _ReadyLandingApp();
    addTearDown(app.dispose);
    await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: VaultTheme.dark(),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const LandingPage(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final lock = find.byIcon(Icons.lock_outline);
    expect(lock, findsOneWidget);
    expect(tester.widget<Icon>(lock).color, VaultColors.accent);
    final card = tester
        .widgetList<Container>(
            find.ancestor(of: lock, matching: find.byType(Container)))
        .singleWhere((container) =>
            container.decoration is BoxDecoration &&
            (container.decoration! as BoxDecoration).color ==
                VaultColors.surface);
    final decoration = card.decoration! as BoxDecoration;
    expect((decoration.border! as Border).top.color, VaultColors.borderSubtle);
    final instructions = find.textContaining('1. Pick a vault name and a PIN');
    expect(tester.widget<Text>(instructions).style!.color,
        VaultColors.textSecondary);
    expect(find.textContaining('4. Ask your vault anything'), findsOneWidget);
    await tester.ensureVisible(lock);
    expect(lock.hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant({TargetPlatform.iOS}));
}
