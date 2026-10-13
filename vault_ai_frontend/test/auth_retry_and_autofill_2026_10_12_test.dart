import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/auth_retry.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

Future<void> pumpAuth(WidgetTester tester, AppState app, Widget page,
    {bool settle = true, List<NavigatorObserver> observers = const []}) async {
  tester.view.physicalSize = const Size(430, 932);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
    value: app,
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: page,
      navigatorObservers: observers,
      routes: {
        '/chat': (_) => const Scaffold(body: Text('Verified destination')),
        '/unlock': (_) => const Scaffold(body: Text('Locked destination')),
        '/pin': (_) => const Scaffold(body: Text('Locked destination')),
      },
    ),
  ));
  if (settle) await tester.pumpAndSettle();
}

bool savedAutofill(WidgetTester tester) =>
    tester.testTextInput.log.any((call) =>
        call.method == 'TextInput.finishAutofillContext' &&
        call.arguments == true);

Future<void> platformAutofill(
    WidgetTester tester, Finder field, String value) async {
  await tester.showKeyboard(field);
  final editable =
      find.descendant(of: field, matching: find.byType(EditableText));
  final state = tester.state<EditableTextState>(editable);
  await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
    SystemChannels.textInput.name,
    SystemChannels.textInput.codec.encodeMethodCall(MethodCall(
      'TextInputClient.updateEditingStateWithTag',
      [
        0,
        {state.autofillId: TextEditingValue(text: value).toJSON()}
      ],
    )),
    (_) {},
  );
  await tester.pump();
}

class ReadyApp extends AppState {
  @override
  bool get hydrated => true;
}

class DelayedReadyApp extends AppState {
  bool ready = false;
  int listenerBalance = 0;
  @override
  void addListener(VoidCallback listener) {
    listenerBalance++;
    super.addListener(listener);
  }

  @override
  void removeListener(VoidCallback listener) {
    listenerBalance--;
    super.removeListener(listener);
  }

  @override
  bool get hydrated => ready;
  void completeHydration() {
    ready = true;
    notifyListeners();
  }
}

class ReplacementObserver extends NavigatorObserver {
  int replacements = 0;
  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    replacements++;
    super.didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }
}

class PinResultApp extends ReadyApp {
  bool accepted = false;
  String? submittedPin;
  @override
  Future<bool> verifyPin(String pin,
      {bool restoreZkSessionKeys = false}) async {
    submittedPin = pin;
    if (!accepted) lockMessage = 'Wrong username or PIN.';
    return accepted;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
  });
  tearDown(() => NativeSecureStore.useSharedPreferencesForTesting = false);

  group('Explicit authentication retry errors', () {
    test('header takes precedence and message contains the exact retry', () {
      final error = AuthRetryException.fromResponse(
          responseBody: '{"detail":{"reset_in_seconds":90}}', retryAfter: '42');
      expect(error.retryAfterSeconds, 42);
      expect(error.message, 'Too many attempts. Try again in 42 seconds.');
    });
    test('structured body works when a browser cannot expose the header', () {
      expect(
          AuthRetryException.fromResponse(
                  responseBody: '{"detail":{"reset_in_seconds":61}}')
              .retryAfterSeconds,
          61);
    });
    test('malformed errors use a bounded non-secret fallback', () {
      final error = AuthRetryException.fromResponse(
          responseBody: 'synthetic-secret-marker', retryAfter: 'not-valid');
      expect(error.retryAfterSeconds, 60);
      expect(error.toString(), isNot(contains('synthetic-secret')));
    });
    test('boolean and fractional delays are not accepted', () {
      for (final value in ['true', '1.5']) {
        expect(
            AuthRetryException.fromResponse(
                    responseBody: '{"detail":{"reset_in_seconds":$value}}')
                .retryAfterSeconds,
            60);
      }
    });
    test('zero and excessive delays are bounded', () {
      expect(
          AuthRetryException.fromResponse(responseBody: '{}', retryAfter: '0')
              .retryAfterSeconds,
          1);
      expect(
          AuthRetryException.fromResponse(
                  responseBody: '{}', retryAfter: '999999')
              .retryAfterSeconds,
          86400);
    });
    test('actual PIN verification displays throttle instead of silent false',
        () async {
      final app = AppState()..lastVaultName = 'QA-only';
      await http.runWithClient(() async {
        expect(await app.verifyPin('000123'), isFalse);
      },
          () => MockClient((request) async {
                expect(request.url.path, '/auth/login');
                return http.Response(
                    '{"detail":{"code":"rate_limited","reset_in_seconds":42}}',
                    429);
              }));
      expect(app.lockMessage, 'Too many attempts. Try again in 42 seconds.');
      expect(app.pinAttempts, 0);
      expect(app.unlocked, isFalse);
    });
    test('actual PIN verification retains existing lock and its clear message',
        () async {
      final app = AppState()..lastVaultName = 'QA-only';
      await http.runWithClient(() async {
        expect(await app.verifyPin('000123'), isFalse);
      },
          () => MockClient((_) async => http.Response(
              '{"detail":{"code":"pin_locked","message":"This vault is temporarily locked. Try again in 59 seconds."}}',
              423)));
      expect(app.lockMessage, contains('59 seconds'));
      expect(app.pinAttempts, 0);
    });
  });

  testWidgets('delayed hydration cannot strand the actual sign-in route blank',
      (tester) async {
    final app = DelayedReadyApp();
    await pumpAuth(tester, app, const LoginPage(), settle: false);
    await tester.pump();
    expect(find.text('Preparing sign-in…'), findsOneWidget);
    expect(find.byKey(const Key('auth_vault_name_field')), findsNothing);
    app.completeHydration();
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('auth_vault_name_field')), findsOneWidget);
    expect(find.text('Preparing sign-in…'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('pending sign-in removes its hydration listener on disposal',
      (tester) async {
    final app = DelayedReadyApp();
    await pumpAuth(tester, app, const LoginPage(), settle: false);
    await tester.pump();
    expect(app.listenerBalance, greaterThan(0));
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(app.listenerBalance, 0);
    app.completeHydration();
    await tester.pump();
    expect(find.byKey(const Key('auth_vault_name_field')), findsNothing);
    expect(savedAutofill(tester), isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'repeated hydration notifications preserve exactly one existing auth redirect',
      (tester) async {
    final observer = ReplacementObserver();
    // A session flag without unlocked keys must retain the existing locked
    // destination, never manufacture an authenticated/unlocked context.
    final app = DelayedReadyApp()..authed = true;
    await pumpAuth(tester, app, const LoginPage(),
        settle: false, observers: [observer]);
    await tester.pump();
    app.completeHydration();
    app.completeHydration();
    app.completeHydration();
    await tester.pumpAndSettle();
    expect(observer.replacements, 1);
    expect(find.text('Locked destination'), findsOneWidget);
    expect(find.text('Verified destination'), findsNothing);
    expect(savedAutofill(tester), isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'actual sign-in fields accept tagged autofill and preserve leading zeroes',
      (tester) async {
    final app = ReadyApp();
    await pumpAuth(tester, app, const LoginPage());
    final name = find.byKey(const Key('auth_vault_name_field'));
    final pin = find.byKey(const Key('auth_pin_field'));
    expect(tester.getSize(name).width, greaterThan(0));
    expect(tester.getSize(pin).height, greaterThan(0));
    expect(
        tester.widget<TextField>(name).autofillHints, [AutofillHints.username]);
    expect(
        tester.widget<TextField>(pin).autofillHints, [AutofillHints.password]);
    expect(find.byType(AutofillGroup), findsOneWidget);
    await platformAutofill(tester, name, 'QA-TEST vault');
    await platformAutofill(tester, pin, '000123');
    expect(tester.widget<TextField>(name).controller!.text, 'QA-TEST vault');
    expect(tester.widget<TextField>(pin).controller!.text, '000123');
    expect(tester.widget<TextField>(pin).obscureText, isTrue);
    expect(savedAutofill(tester), isFalse);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(savedAutofill(tester), isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'sign-in rejects an overlength autofill without truncating it or saving credentials',
      (tester) async {
    final app = ReadyApp();
    await pumpAuth(tester, app, const LoginPage());
    await tester.enterText(
        find.byKey(const Key('auth_vault_name_field')), 'QA-only');
    final pin = find.byKey(const Key('auth_pin_field'));
    final overlength = List.filled(65, '0').join();
    await platformAutofill(tester, pin, overlength);
    expect(tester.widget<TextField>(pin).controller!.text, overlength);
    var requests = 0;
    await http.runWithClient(() async {
      await tester.tap(find.byKey(const Key('auth_sign_in_button')));
      await tester.pumpAndSettle();
    },
        () => MockClient((_) async {
              requests++;
              return http.Response('unexpected', 500);
            }));
    expect(requests, 0);
    expect(find.text('PIN must be 64 digits or fewer.'), findsOneWidget);
    expect(savedAutofill(tester), isFalse);
  });

  testWidgets(
      'sign-in reports invalid characters without altering the supplied PIN',
      (tester) async {
    final app = ReadyApp();
    await pumpAuth(tester, app, const LoginPage());
    await tester.enterText(
        find.byKey(const Key('auth_vault_name_field')), 'QA-only');
    final pin = find.byKey(const Key('auth_pin_field'));
    await platformAutofill(tester, pin, '00a123');
    await tester.tap(find.byKey(const Key('auth_sign_in_button')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(pin).controller!.text, '00a123');
    expect(find.text('PIN can only contain digits.'), findsOneWidget);
    expect(savedAutofill(tester), isFalse);
  });

  testWidgets(
      'signup groups new-name and new-PIN hints, not display-name credentials',
      (tester) async {
    await pumpAuth(tester, ReadyApp(), const SignupPage());
    expect(find.byType(AutofillGroup), findsOneWidget);
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('signup_vault_name_field')))
            .autofillHints,
        [AutofillHints.newUsername]);
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('signup_pin_field')))
            .autofillHints,
        [AutofillHints.newPassword]);
    expect(
        tester
            .widget<TextField>(
                find.byKey(const Key('signup_confirm_pin_field')))
            .autofillHints,
        [AutofillHints.newPassword]);
    expect(
        tester
            .widget<TextField>(
                find.byKey(const Key('signup_display_name_field')))
            .autofillHints,
        isEmpty);
    expect(savedAutofill(tester), isFalse);
  });

  testWidgets('returning unlock accepts a full64-digit tagged PIN and masks it',
      (tester) async {
    final app = ReadyApp()..lastVaultName = 'QA-only';
    await pumpAuth(tester, app, const UnlockPage());
    final pin = find.byKey(const Key('auth_unlock_pin_field'));
    final value = '00${List.filled(62, '1').join()}';
    await platformAutofill(tester, pin, value);
    expect(tester.widget<TextField>(pin).controller!.text, value);
    expect(tester.widget<TextField>(pin).obscureText, isTrue);
    expect(
        tester.widget<TextField>(pin).autofillHints, [AutofillHints.password]);
    expect(find.byType(AutofillGroup), findsOneWidget);
    expect(savedAutofill(tester), isFalse);
  });

  for (final accepted in [false, true]) {
    testWidgets('PIN gate saves autofill only after verified result=$accepted',
        (tester) async {
      final app = PinResultApp()
        ..sessionToken = 'synthetic-only'
        ..lastVaultName = 'QA-only'
        ..accepted = accepted;
      await http.runWithClient(() async {
        await pumpAuth(tester, app, const PinGatePage());
        final pin = find.byKey(const Key('pin_gate_pin_field'));
        await platformAutofill(tester, pin, '000123');
        expect(tester.widget<TextField>(pin).autofillHints,
            [AutofillHints.password]);
        await tester.tap(find.byKey(const Key('pin_gate_submit_button')));
        await tester.pumpAndSettle();
      },
          () => MockClient((request) async {
                expect(request.method, 'GET');
                return http.Response(
                    '{"has_vault":true,"is_orphaned":false,"must_reset":false}',
                    200);
              }));
      expect(app.submittedPin, '000123');
      expect(savedAutofill(tester), accepted);
      if (accepted) {
        expect(find.text('Verified destination'), findsOneWidget);
      } else {
        expect(find.text('Wrong username or PIN.'), findsOneWidget);
      }
      expect(tester.takeException(), isNull);
    });
  }

  test('ZK transport and UI explicitly preserve typed429 without auth fallback',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    final transport = source.substring(
        source.indexOf('Future<Map<String, dynamic>> _zkHttpPost('),
        source.indexOf('Future<Map<String, dynamic>> _zkHttpGet('));
    expect(transport, contains('response.statusCode == 429'));
    expect(transport, contains('AuthRetryException.fromResponse('));
    for (final name in [
      '_LoginPageState',
      '_SignupPageState',
      '_UnlockPageState'
    ]) {
      final start = source.indexOf('class $name');
      final end = source.indexOf('\nclass ', start + 1);
      final body = source.substring(start, end);
      expect(body, contains('on AuthRetryException catch'));
      expect(
          body, contains('TextInput.finishAutofillContext(shouldSave: true)'));
    }
  });
}
