import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/concierge_exposure.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_exposure_panel.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_private_dialog.dart';

import 'concierge_exposure_2026_10_09_test.dart' show Harness;

class HealthClient extends VaultAIClient {
  final bool fail;
  HealthClient({this.fail = false}) : super(baseUrl: 'https://example.invalid');
  @override
  Future<Map<String, dynamic>> getSecurityCenterSummary(
      {required String authToken}) async {
    if (fail) throw Exception('fixture outage');
    return {
      'score': 50,
      'score_band': 'moderate',
      'recommendations': [],
      'inheritance': {}
    };
  }

  @override
  Future<Map<String, dynamic>> getActiveExpiryAlerts(
      {required String authToken,
      required String vaultName,
      String? expiryFilter,
      int limit = 100}) async {
    if (fail) throw Exception('fixture outage');
    return {'alerts': [], 'counts': {}, 'engine': 'on'};
  }
}

Widget app(Widget child) => MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: Scaffold(body: SingleChildScrollView(child: child)));

void main() {
  testWidgets(
      'real panel exposes honest opt-in, missing provider and unsupported file coverage on phone',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final h = Harness();
    h.provider.caps = const ConciergeProviderCapabilities();
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: h.bindings)));
    await tester.pumpAndSettle();
    expect(find.text('Login exposure checks'), findsOneWidget);
    expect(find.text('Email status: Provider not configured'), findsOneWidget);
    expect(
        find.textContaining('Files and full dark-web scanning: not supported.'),
        findsOneWidget);
    final button = tester
        .widget<FilledButton>(find.widgetWithText(FilledButton, 'Check now'));
    expect(button.onPressed, null);
    expect(h.passwords.calls, 0);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'consent dialog separates prefix checks, selected email and background full-email disclosure',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final h = Harness();
    final bindings = h.bindings;
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Manage checks'));
    await tester.pumpAndSettle();
    expect(find.text('Choose your privacy checks'), findsOneWidget);
    expect(
        find.textContaining('Your password and full hash stay on this device.'),
        findsOneWidget);
    expect(
        find.textContaining(
            'Separate permission: selected full email addresses'),
        findsOneWidget);
    await tester.tap(find.text('Allow password exposure checks'));
    await tester.pump();
    await tester.ensureVisible(find.text('Save choices'));
    await tester.tap(find.text('Save choices'));
    await tester.pumpAndSettle();
    expect(h.state?['consent']['enabled'], true);
    expect(h.state?['consent']['background_emails'], false);
    expect(h.provider.creates, 0);
    await tester.tap(find.text('Check now'));
    await tester.pumpAndSettle();
    expect(find.text('Password status: Checked against known data'),
        findsOneWidget);
    expect(h.provider.emails, 0);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'one affected login alert and update confirmation never claims external password changed',
      (tester) async {
    final h = Harness();
    h.passwords.count = 8;
    h.provider.caps = const ConciergeProviderCapabilities();
    h.records = const [
      ConciergeLoginRecord(
          id: '1', title: 'Example', password: 'r47xQm92TvcLp1zK')
    ];
    var edits = 0;
    final original = h.bindings;
    final bindings = ConciergeExposureBindings(
        captureAccess: original.captureAccess,
        loadLogins: original.loadLogins,
        readEncryptedState: original.readEncryptedState,
        writeEncryptedState: original.writeEncryptedState,
        provider: h.provider,
        passwordChecker: h.passwords,
        onUpdateLogin: (id, title, type) {
          expect(id, '1');
          expect(title, 'Example');
          edits++;
        });
    h.state = {
      'schema': 1,
      'consent': const ConciergeConsent(enabled: true).toJson()
    };
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Check now'));
    await tester.pumpAndSettle();
    expect(find.text('Example'), findsOneWidget);
    expect(find.textContaining('appears 8 times'), findsOneWidget);
    await tester.ensureVisible(find.text('Review and update saved login'));
    await tester.tap(find.text('Review and update saved login'));
    await tester.pumpAndSettle();
    expect(find.textContaining('does not change the password on that service'),
        findsOneWidget);
    await tester.tap(find.text('Update vault copy'));
    await tester.pumpAndSettle();
    expect(edits, 1);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('vault-health outage does not render legacy All clear',
      (tester) async {
    await tester.pumpWidget(app(ConciergePage(
        client: HealthClient(fail: true),
        authToken: 'fixture',
        vaultName: 'Fixture',
        isMobile: true)));
    await tester.pumpAndSettle();
    expect(find.text('All clear.'), findsNothing);
    expect(find.textContaining('unavailable'), findsOneWidget);
    expect(tester.takeException(), null);
  });

  testWidgets(
      'existing travel/security sections remain alongside new checks when health load fails',
      (tester) async {
    final h = Harness();
    await tester.pumpWidget(app(ConciergePage(
        client: HealthClient(fail: true),
        authToken: 'fixture',
        vaultName: 'Fixture',
        isMobile: true,
        exposureBindings: h.bindings)));
    await tester.pumpAndSettle();
    expect(find.text('Login exposure checks'), findsOneWidget);
    expect(find.text('Travel readiness'), findsOneWidget);
    expect(find.text('All clear.'), findsNothing);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'lock removes private exposure panel and titles before any future result',
      (tester) async {
    final h = Harness();
    final bindings = h.bindings;
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pumpAndSettle();
    h.unlocked = false;
    h.epoch++;
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pump();
    expect(find.byKey(const Key('concierge_exposure_panel')), findsNothing);
    expect(find.text('Example'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'locking an open consent dialog removes selected emails and cannot enable checks',
      (tester) async {
    final h = Harness();
    final bindings = h.bindings;
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Manage checks'));
    await tester.pumpAndSettle();
    expect(find.text('owner@example.test'), findsOneWidget);
    h.unlocked = false;
    h.epoch++;
    await tester.pumpWidget(app(ConciergeExposurePanel(bindings: bindings)));
    await tester.pumpAndSettle();
    expect(find.text('owner@example.test'), findsNothing);
    expect(find.text('Choose your privacy checks'), findsNothing);
    expect(h.writes, 0);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'shared private editor dialog observes lease changes and removes only its owned route',
      (tester) async {
    final unlocked = ValueNotifier(true);
    addTearDown(unlocked.dispose);
    bool? result;
    var completed = false;
    late BuildContext owner;
    await tester
        .pumpWidget(MaterialApp(home: Scaffold(body: Builder(builder: (ctx) {
      owner = ctx;
      return TextButton(
          onPressed: () async {
            result = await showConciergeLeaseDialog<bool>(
                context: ctx,
                sessionChanges: unlocked,
                access: ConciergeAccessLease(isCurrent: () => unlocked.value),
                builder: (_) => const AlertDialog(
                    title: Text('Private fixture editor'),
                    content: TextField(
                        decoration: InputDecoration(
                            labelText: 'Saved password fixture'))));
            completed = true;
          },
          child: const Text('Edit fixture'));
    }))));
    await tester.tap(find.text('Edit fixture'));
    await tester.pumpAndSettle();
    expect(find.text('Saved password fixture'), findsOneWidget);
    Navigator.of(owner).push(MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('Other safe route'))));
    await tester.pumpAndSettle();
    unlocked.value = false;
    await tester.pumpAndSettle();
    expect(find.text('Other safe route'), findsOneWidget);
    expect(
        find.text('Saved password fixture', skipOffstage: false), findsNothing);
    expect(result, null);
    expect(completed, true);
    expect(tester.takeException(), null);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
