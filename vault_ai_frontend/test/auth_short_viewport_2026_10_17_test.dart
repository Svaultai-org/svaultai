import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/ui/theme.dart';

class _ReadyLayoutApp extends AppState {
  @override
  bool get hydrated => true;
}

void _viewport(WidgetTester tester, Size size, {double keyboard = 0}) {
  final landscape = size.width > size.height;
  final side = landscape && size.width >= 844 ? 62.0 : 0.0;
  final top = !landscape && size.height > 700 ? 62.0 : 0.0;
  final bottom = size.height > 700
      ? 34.0
      : landscape
          ? 21.0
          : 0.0;
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  tester.view.viewPadding =
      FakeViewPadding(left: side, top: top, right: side, bottom: bottom);
  tester.view.padding = FakeViewPadding(
      left: side, top: top, right: side, bottom: keyboard == 0 ? bottom : 0);
  tester.view.viewInsets = FakeViewPadding(bottom: keyboard);
}

Future<void> _pumpPage(WidgetTester tester, Widget page,
    {required Size size,
    double keyboard = 0,
    double scale = 1,
    _ReadyLayoutApp? app}) async {
  _viewport(tester, size, keyboard: keyboard);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetViewPadding);
  addTearDown(tester.view.resetPadding);
  addTearDown(tester.view.resetViewInsets);
  await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
    value: app ?? _ReadyLayoutApp(),
    child: MaterialApp(
      theme: VaultTheme.dark(),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: page,
      routes: {
        '/signup': (_) => const Scaffold(body: Text('Create route reached')),
        '/login': (_) => const Scaffold(body: Text('Login route reached')),
        '/unlock': (_) => const Scaffold(body: Text('Unlock route reached')),
      },
    ),
  ));
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
}

Future<void> _reachable(WidgetTester tester, Key key,
    {required Size size, double keyboard = 0}) async {
  final control = find.byKey(key);
  expect(control, findsOneWidget);
  await tester.ensureVisible(control);
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
  expect(control.hitTestable(), findsOneWidget,
      reason:
          '$key must be usable after scrolling, not merely present offscreen');
  final rect = tester.getRect(control);
  final padding = tester.view.padding;
  expect(rect.left, greaterThanOrEqualTo(padding.left));
  expect(rect.right, lessThanOrEqualTo(size.width - padding.right));
  expect(rect.top, greaterThanOrEqualTo(padding.top));
  expect(
      rect.bottom,
      lessThanOrEqualTo(size.height -
          (keyboard > padding.bottom ? keyboard : padding.bottom) +
          0.1));
}

bool _savedAutofill(WidgetTester tester) =>
    tester.testTextInput.log.any((call) =>
        call.method == 'TextInput.finishAutofillContext' &&
        call.arguments == true);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
  });
  tearDown(() => NativeSecureStore.useSharedPreferencesForTesting = false);

  final profiles = [
    (
      name: 'reported iPhone landscape',
      size: const Size(956, 440),
      keyboard: 0.0,
      scale: 1.0
    ),
    (
      name: 'small landscape',
      size: const Size(568, 320),
      keyboard: 0.0,
      scale: 1.0
    ),
    (
      name: 'landscape keyboard',
      size: const Size(956, 440),
      keyboard: 216.0,
      scale: 1.3
    ),
    (
      name: 'small portrait keyboard',
      size: const Size(320, 568),
      keyboard: 216.0,
      scale: 1.3
    ),
    (
      name: 'large text portrait keyboard',
      size: const Size(440, 956),
      keyboard: 336.0,
      scale: 2.0
    ),
  ];
  for (final profile in profiles) {
    testWidgets('sign-in controls remain usable: ${profile.name}',
        (tester) async {
      await _pumpPage(tester, const LoginPage(),
          size: profile.size, keyboard: profile.keyboard, scale: profile.scale);
      for (final key in [
        'auth_vault_name_field',
        'auth_pin_field',
        'auth_sign_in_button',
        'login_create_vault_link',
        'login_form_help_and_faq'
      ]) {
        await _reachable(tester, Key(key),
            size: profile.size, keyboard: profile.keyboard);
      }
      expect(_savedAutofill(tester), isFalse);
    });
  }

  testWidgets(
      'rotation retains fictional input, masks PIN and keeps create action usable',
      (tester) async {
    await _pumpPage(tester, const LoginPage(), size: const Size(440, 956));
    final name = find.byKey(const Key('auth_vault_name_field'));
    final pin = find.byKey(const Key('auth_pin_field'));
    await tester.enterText(name, 'Layout demo only');
    await tester.enterText(pin, '001234');
    _viewport(tester, const Size(956, 440), keyboard: 216);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(tester.widget<TextField>(name).controller!.text, 'Layout demo only');
    expect(tester.widget<TextField>(pin).controller!.text, '001234');
    expect(tester.widget<TextField>(pin).obscureText, isTrue);
    await _reachable(tester, const Key('login_create_vault_link'),
        size: const Size(956, 440), keyboard: 216);
    await tester.tap(find.byKey(const Key('login_create_vault_link')));
    await tester.pumpAndSettle();
    expect(find.text('Create route reached'), findsOneWidget);
    expect(tester.takeException(), isNull);
    expect(_savedAutofill(tester), isFalse);
  });

  testWidgets(
      'local validation error remains readable above landscape keyboard',
      (tester) async {
    const size = Size(956, 440);
    await _pumpPage(tester, const LoginPage(),
        size: size, keyboard: 216, scale: 1.3);
    await tester.enterText(
        find.byKey(const Key('auth_vault_name_field')), 'Layout demo only');
    await tester.enterText(find.byKey(const Key('auth_pin_field')), '12');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final error = find.text('PIN must be at least 6 digits.');
    await tester.ensureVisible(error);
    await tester.pumpAndSettle();
    expect(error.hitTestable(), findsOneWidget);
    expect(tester.getRect(error).bottom, lessThanOrEqualTo(size.height - 216));
    expect(tester.takeException(), isNull);
    expect(_savedAutofill(tester), isFalse);
  });

  testWidgets('returning unlock remains usable above landscape keyboard',
      (tester) async {
    const size = Size(956, 440);
    await _pumpPage(tester, const UnlockPage(),
        size: size,
        keyboard: 216,
        scale: 1.3,
        app: _ReadyLayoutApp()..lastVaultName = 'Layout demo only');
    for (final key in [
      'auth_unlock_pin_field',
      'auth_unlock_button',
      'unlock_use_another_vault_button'
    ]) {
      await _reachable(tester, Key(key), size: size, keyboard: 216);
    }
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('auth_unlock_pin_field')))
            .obscureText,
        isTrue);
    expect(_savedAutofill(tester), isFalse);
  });

  testWidgets(
      'PIN gate remains usable above landscape keyboard with synthetic metadata',
      (tester) async {
    const size = Size(956, 440);
    var requests = 0;
    await http.runWithClient(() async {
      await _pumpPage(tester, const PinGatePage(),
          size: size,
          keyboard: 216,
          scale: 1.3,
          app: _ReadyLayoutApp()..sessionToken = 'synthetic-layout-only');
      await _reachable(tester, const Key('pin_gate_pin_field'),
          size: size, keyboard: 216);
      await _reachable(tester, const Key('pin_gate_submit_button'),
          size: size, keyboard: 216);
      expect(
          tester
              .widget<TextField>(find.byKey(const Key('pin_gate_pin_field')))
              .obscureText,
          isTrue);
    },
        () => MockClient((request) async {
              requests++;
              expect(request.method, 'GET');
              expect(request.url.path, '/my-vault');
              return http.Response(
                  '{"has_vault":true,"is_orphaned":false,"must_reset":false}',
                  200);
            }));
    expect(requests, 1);
    expect(_savedAutofill(tester), isFalse);
  });
}
