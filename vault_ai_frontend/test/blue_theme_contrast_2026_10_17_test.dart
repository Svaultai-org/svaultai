import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/ui/theme.dart';
import 'package:vault_ai_frontend/ui/tokens.dart';

double _contrast(Color first, Color second) {
  final a = first.computeLuminance();
  final b = second.computeLuminance();
  return (math.max(a, b) + 0.05) / (math.min(a, b) + 0.05);
}

Color _textColor(WidgetTester tester, String label) =>
    DefaultTextStyle.of(tester.element(find.text(label))).style.color!;

class _ReadyApp extends AppState {
  @override
  bool get hydrated => true;
}

void main() {
  test('blue actions and the complete user bubble gradient keep readable text',
      () {
    for (final background in [VaultColors.accent, VaultColors.accentBright]) {
      expect(_contrast(VaultColors.textOnAccent, background),
          greaterThanOrEqualTo(4.5));
    }
    for (var step = 0; step <= 10; step++) {
      final background = Color.lerp(
          VaultColors.bubbleUserA, VaultColors.bubbleUserB, step / 10)!;
      expect(_contrast(VaultColors.textOnAccent, background),
          greaterThanOrEqualTo(4.5));
      final attachmentBackground =
          Color.alphaBlend(Colors.white.withValues(alpha: 0.10), background);
      final attachmentText = Color.alphaBlend(
          VaultColors.textOnAccent.withValues(alpha: 0.78),
          attachmentBackground);
      expect(_contrast(attachmentText, attachmentBackground),
          greaterThanOrEqualTo(4.5));
    }
  });

  test('small body, secondary and hint text remain readable on dark surfaces',
      () {
    for (final background in [
      VaultColors.canvas,
      VaultColors.surface,
      VaultColors.surfaceElevated,
      VaultColors.surfaceMuted,
      VaultColors.surfaceHover,
    ]) {
      for (final foreground in [
        VaultColors.textPrimary,
        VaultColors.textSecondary,
        VaultColors.textTertiary,
      ]) {
        expect(_contrast(foreground, background), greaterThanOrEqualTo(4.5));
      }
    }
  });

  test('brand accents are blue while warning and destructive colors stay clear',
      () {
    expect(VaultColors.accent, const Color(0xFF77B8FF));
    expect(VaultColors.canvas, const Color(0xFF0F1115));
    expect(VaultColors.textOnAccent, const Color(0xFF091B30));
    for (final color in [
      VaultColors.accent,
      VaultColors.accentBright,
      VaultColors.bubbleUserA,
      VaultColors.bubbleUserB,
      VaultColors.severityOk,
    ]) {
      expect(color.b, greaterThan(color.g));
      expect(color.g, greaterThan(color.r));
    }
    expect(VaultColors.severityWarn, const Color(0xFFFBBF24));
    expect(VaultColors.severityCrit, const Color(0xFFF87171));
    expect(VaultColors.forSeverity('success'), VaultColors.severityOk);
    expect(VaultColors.forSeverity('critical'), VaultColors.severityCrit);
  });

  test('Material containers, focus and progress share the blue palette', () {
    final theme = VaultTheme.dark();
    final scheme = theme.colorScheme;
    expect(scheme.primary, VaultColors.accent);
    expect(scheme.onPrimary, VaultColors.textOnAccent);
    expect(scheme.onSecondary, VaultColors.textOnAccent);
    expect(scheme.primaryContainer, VaultColors.accentContainer);
    expect(scheme.secondaryContainer, VaultColors.accentContainer);
    expect(scheme.tertiaryContainer, VaultColors.accentContainer);
    expect(_contrast(scheme.onPrimaryContainer, scheme.primaryContainer),
        greaterThanOrEqualTo(4.5));
    expect(theme.scaffoldBackgroundColor, VaultColors.canvas);
    expect(theme.cardTheme.color, VaultColors.surface);
    expect(theme.progressIndicatorTheme.color, VaultColors.accent);
    expect(theme.textSelectionTheme.cursorColor, VaultColors.accent);
    expect(theme.primaryColor, VaultColors.accent);
    expect(theme.cupertinoOverrideTheme!.primaryColor, VaultColors.accent);
    expect(theme.cupertinoOverrideTheme!.primaryContrastingColor,
        VaultColors.textOnAccent);
    expect(
      (theme.inputDecorationTheme.focusedBorder! as OutlineInputBorder)
          .borderSide
          .color,
      VaultColors.accent,
    );
  });

  testWidgets('filled and elevated controls render dark text in active states',
      (tester) async {
    final states = WidgetStatesController();
    addTearDown(states.dispose);
    await tester.pumpWidget(MaterialApp(
      theme: VaultTheme.dark(),
      home: Scaffold(
        body: Column(children: [
          FilledButton(
            statesController: states,
            onPressed: () {},
            child: const Text('Filled action'),
          ),
          ElevatedButton(
            statesController: states,
            onPressed: () {},
            child: const Text('Elevated action'),
          ),
        ]),
      ),
    ));
    for (final state in [
      null,
      WidgetState.hovered,
      WidgetState.focused,
      WidgetState.pressed
    ]) {
      if (state != null) states.update(state, true);
      await tester.pumpAndSettle();
      expect(_textColor(tester, 'Filled action'), VaultColors.textOnAccent);
      expect(_textColor(tester, 'Elevated action'), VaultColors.textOnAccent);
      final style = VaultTheme.dark().filledButtonTheme.style!;
      final active = state == null ? <WidgetState>{} : <WidgetState>{state};
      final background = style.backgroundColor!.resolve(active)!;
      final overlay = style.overlayColor?.resolve(active) ?? Colors.transparent;
      expect(
        _contrast(
            VaultColors.textOnAccent, Color.alphaBlend(overlay, background)),
        greaterThanOrEqualTo(4.5),
      );
      if (state != null) states.update(state, false);
    }
  });

  testWidgets('disabled controls remain distinct and cannot activate',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      theme: VaultTheme.dark(),
      home: Scaffold(
          body: Column(children: [
        const FilledButton(onPressed: null, child: Text('Disabled action')),
        FilledButton(
            onPressed: () => calls++, child: const Text('Ready action')),
      ])),
    ));
    expect(_textColor(tester, 'Disabled action'), VaultColors.textSecondary);
    expect(_textColor(tester, 'Ready action'), VaultColors.textOnAccent);
    await tester.tap(find.text('Disabled action'));
    expect(calls, 0);
    await tester.tap(find.text('Ready action'));
    expect(calls, 1);
  });

  for (final size in [const Size(320, 568), const Size(390, 844)]) {
    for (final scale in [1.0, 1.3]) {
      testWidgets('blue signup stays usable at $size with text scale $scale',
          (tester) async {
        SharedPreferences.setMockInitialValues({});
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final app = _ReadyApp();
        addTearDown(app.dispose);
        await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            theme: VaultTheme.dark(),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context)
                  .copyWith(textScaler: TextScaler.linear(scale)),
              child: child!,
            ),
            home: const SignupPage(),
          ),
        ));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        final checkbox = find.byKey(const Key('signup_risk_checkbox'));
        await tester.ensureVisible(checkbox);
        await tester.tap(checkbox);
        await tester.pumpAndSettle();
        expect(tester.widget<Checkbox>(checkbox).value, isTrue);
        final create = find.byKey(const Key('signup_create_vault_button'));
        await tester.ensureVisible(create);
        expect(create.hitTestable(), findsOneWidget);
        expect(_textColor(tester, 'Create vault'), VaultColors.textOnAccent);
        expect(
          tester
              .widget<TextField>(find.byKey(const Key('signup_pin_field')))
              .obscureText,
          isTrue,
        );
        expect(tester.takeException(), isNull);
      },
          variant: TargetPlatformVariant(
              {TargetPlatform.iOS, TargetPlatform.android}));
    }
  }
}
