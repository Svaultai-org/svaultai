import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/services/content_hash.dart';
import 'package:vault_ai_frontend/ui/chat/duplicate_dialog.dart';
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';
import 'package:vault_ai_frontend/ui/dashboards/concierge_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/expiry_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';
import 'package:vault_ai_frontend/ui/responsive.dart';

import '_helpers/responsive_harness.dart';

class _ViewportClient extends VaultAIClient {
  const _ViewportClient() : super(baseUrl: 'https://viewport.test.invalid');

  @override
  Future<Map<String, dynamic>> getMemoryTimeline(
          {required String authToken,
          required String vaultName,
          String? memoryType,
          int limit = 200}) async =>
      <String, dynamic>{'items': <Object>[], 'counts': <String, int>{}};

  @override
  Future<Map<String, dynamic>> getActiveExpiryAlerts(
          {required String authToken,
          required String vaultName,
          String? expiryFilter,
          int limit = 100}) async =>
      <String, dynamic>{'alerts': <Object>[], 'counts': <String, int>{}};

  @override
  Future<Map<String, dynamic>> getSecurityCenterSummary(
          {required String authToken}) async =>
      <String, dynamic>{};
}

const _fakeClient = _ViewportClient();

final List<DeviceProfile> kFullViewportMatrix = const [
  DeviceProfiles.iphoneSE,
  DeviceProfiles.iphone12,
  DeviceProfiles.iphone14ProMax,
  DeviceProfiles.pixel7,
  DeviceProfiles.ipad,
  DeviceProfiles.desktop,
];

Widget _wrap(Widget child) => Localizations(
      locale: const Locale('en'),
      delegates: AppLocalizations.localizationsDelegates,
      child: child,
    );

Future<void> _openDialog(
  WidgetTester tester,
  Widget dialogChild, {
  required DeviceProfile device,
}) async {
  await tester.binding.setSurfaceSize(device.logicalSize);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Builder(
        builder: (ctx) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => showDialog<void>(
                context: ctx,
                builder: (_) => dialogChild,
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}

void _forEachViewport(
  String description,
  Future<void> Function(WidgetTester t, DeviceProfile d) body, {
  List<DeviceProfile>? devices,
}) {
  final targets = devices ?? kFullViewportMatrix;
  for (final d in targets) {
    testWidgets(
        '$description @ ${d.name} '
        '(${d.width.toInt()}x${d.height.toInt()})', (tester) async {
      await body(tester, d);
      expectNoOverflow(tester, context: d.name);
    });
  }
}

Future<AppState> _hydrated() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  // These are pure viewport checks. Hydration invokes platform-backed secure
  // storage and can leave a plugin future pending in the widget-test runner.
  return AppState();
}

Future<void> _pumpWithProvider(
  WidgetTester t,
  Widget page,
  AppState app,
  DeviceProfile d, {
  double keyboardHeight = 0,
}) async {
  await t.binding.setSurfaceSize(d.logicalSize);
  addTearDown(() async {
    await t.binding.setSurfaceSize(null);
  });
  await t.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        home: MediaQuery(
          data: MediaQueryData(
            size: d.logicalSize,
            devicePixelRatio: d.devicePixelRatio,
            padding: d.safeAreaInsets,
            viewInsets: keyboardHeight > 0
                ? EdgeInsets.only(bottom: keyboardHeight)
                : EdgeInsets.zero,
          ),
          child: page,
        ),
      ),
    ),
  );
  await t.pump(const Duration(milliseconds: 200));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  group('Typography scale — hierarchy invariant across every viewport', () {
    // At every viewport, display must be ≥ headline must be ≥ titleLg,
    // and metric must sit between them.
    for (final d in kFullViewportMatrix) {
      testWidgets('display ≥ headline ≥ titleLg + metric ordering @ ${d.name}',
          (tester) async {
        await pumpAtDevice(
          tester,
          Builder(builder: (ctx) {
            final display = vrDisplay(ctx);
            final headline = vrHeadline(ctx);
            final titleLg = vrTitleLg(ctx);
            final metric = vrMetric(ctx);
            expect(display, greaterThanOrEqualTo(headline),
                reason: 'display should be at least headline @ ${d.name}');
            expect(headline, greaterThanOrEqualTo(titleLg),
                reason: 'headline should be at least titleLg @ ${d.name}');
            expect(metric, greaterThanOrEqualTo(titleLg),
                reason: 'metric should be at least titleLg @ ${d.name}');
            expect(metric, lessThanOrEqualTo(display),
                reason: 'metric should not exceed display @ ${d.name}');
            return const SizedBox.shrink();
          }),
          device: d,
        );
      });
    }
  });

  group('Typography scale — page hero heading (vrHeadline) shrinks on phone',
      () {
    testWidgets('SE 320 → headline < desktop 1440', (tester) async {
      double phoneVal = 0, desktopVal = 0;
      await pumpAtDevice(
        tester,
        Builder(builder: (ctx) {
          phoneVal = vrHeadline(ctx);
          return const SizedBox.shrink();
        }),
        device: DeviceProfiles.iphoneSE,
      );
      await pumpAtDevice(
        tester,
        Builder(builder: (ctx) {
          desktopVal = vrHeadline(ctx);
          return const SizedBox.shrink();
        }),
        device: DeviceProfiles.desktop,
      );
      expect(phoneVal, lessThan(desktopVal),
          reason:
              'headline @ 320 ($phoneVal) should be smaller than @ 1440 ($desktopVal)');
    });
  });

  group('LoginsPage empty state — full viewport matrix', () {
    _forEachViewport('renders without overflow', (t, d) async {
      await pumpAtDevice(
        t,
        _wrap(LoginsPage(
          isLoading: false,
          hasLoaded: true,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        )),
        device: d,
      );
    });
  });

  group('LoginsPage error state — full viewport matrix', () {
    _forEachViewport('renders without overflow', (t, d) async {
      await pumpAtDevice(
        t,
        _wrap(LoginsPage(
          isLoading: false,
          hasLoaded: true,
          error:
              'Could not load your logins. Check your connection and try again with a very long error.',
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        )),
        device: d,
      );
    });
  });

  group('LoginsPage loading state — full viewport matrix', () {
    _forEachViewport('renders without overflow', (t, d) async {
      await pumpAtDevice(
        t,
        _wrap(LoginsPage(
          isLoading: true,
          hasLoaded: false,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        )),
        device: d,
        settle: false,
      );
    });
  });

  group('HelpCenterPage — full viewport matrix + landscape', () {
    _forEachViewport('renders (public)', (t, d) async {
      await pumpAtDevice(
        t,
        _wrap(const HelpCenterPage(mode: HelpCenterMode.public)),
        device: d,
      );
    });
    _forEachViewport(
      'renders (signed-in) landscape',
      (t, d) async {
        await pumpAtDevice(
          t,
          _wrap(const HelpCenterPage(mode: HelpCenterMode.signedIn)),
          device: d,
        );
      },
      devices: DeviceProfiles.allLandscape,
    );
  });

  group('LoginsPage — landscape orientation', () {
    _forEachViewport(
      'renders without overflow',
      (t, d) async {
        await pumpAtDevice(
          t,
          _wrap(LoginsPage(
            isLoading: false,
            hasLoaded: true,
            logins: const [
              VaultLoginItem(service: 'Netflix', itemType: 'login'),
              VaultLoginItem(
                  service: 'American First Credit Union', itemType: 'login'),
            ],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          )),
          device: d,
        );
      },
      devices: DeviceProfiles.allLandscape,
    );
  });

  group('Dialogs — full viewport matrix', () {
    _forEachViewport(
      'DeleteVaultFlow',
      (t, d) async {
        await _openDialog(
          t,
          const DeleteVaultFlow(
            client: VaultAIClient(baseUrl: 'https://example.test'),
            authToken: 'test-token',
          ),
          device: d,
        );
      },
    );
    _forEachViewport('NotEnoughStorageDialog', (t, d) async {
      await _openDialog(
        t,
        const NotEnoughStorageDialog(
          plannedBytes: 5000000000,
          availableBytes: 1000000000,
          folderName: 'A quite long folder name',
        ),
        device: d,
      );
    });
    _forEachViewport('DuplicateUploadDialog', (t, d) async {
      await _openDialog(
        t,
        DuplicateUploadDialog(
          detail: const DuplicateFoundDetail(
            existingFileId: 'x',
            incomingFileName: 'photo.png',
            incomingSize: 123,
            message: 'exists',
            existingFileName: 'photo.png',
            existingSavedName: 'photo.png',
            existingRelativePath: '/Photos/2024',
          ),
        ),
        device: d,
      );
    });
    _forEachViewport('NameConflictDialog', (t, d) async {
      await _openDialog(
        t,
        NameConflictDialog(
          detail: const NameConflictDetail(
            existingFileId: 'x',
            incomingFileName: 'doc.pdf',
            incomingSize: 123,
            message: 'name conflict',
            existingFileName: 'doc.pdf',
            existingSavedName: 'doc.pdf',
            existingRelativePath: '/Documents',
            proposedVersionedName: 'doc_v2.pdf',
          ),
        ),
        device: d,
      );
    });
  });

  group('DeleteVaultFlow — landscape orientation', () {
    _forEachViewport(
      'renders + typing keyboard',
      (t, d) async {
        await _openDialog(
          t,
          const DeleteVaultFlow(
            client: VaultAIClient(baseUrl: 'https://example.test'),
            authToken: 'test-token',
          ),
          device: d,
        );
      },
      devices: DeviceProfiles.allLandscape,
    );
  });

  group('Keyboard-open state — form fields do not push out of viewport', () {
    for (final d in DeviceProfiles.allPhones) {
      testWidgets('DeleteVaultFlow with 336dp keyboard @ ${d.name}',
          (tester) async {
        await tester.binding.setSurfaceSize(d.logicalSize);
        addTearDown(() async {
          await tester.binding.setSurfaceSize(null);
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData.dark(useMaterial3: true),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('en'),
            home: Builder(
              builder: (ctx) => MediaQuery(
                data: MediaQueryData(
                  size: d.logicalSize,
                  devicePixelRatio: d.devicePixelRatio,
                  padding: d.safeAreaInsets,
                  viewInsets: const EdgeInsets.only(bottom: 336),
                ),
                child: Scaffold(
                  body: Center(
                    child: ElevatedButton(
                      onPressed: () => showDialog<void>(
                        context: ctx,
                        builder: (_) => const DeleteVaultFlow(
                          client:
                              VaultAIClient(baseUrl: 'https://example.test'),
                          authToken: 'test-token',
                        ),
                      ),
                      child: const Text('open'),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        expectNoOverflow(tester, context: '${d.name} + keyboard');
      });
    }
  });

  group('Safe-area / notch — top and bottom insets consumed correctly', () {
    for (final d in DeviceProfiles.allPhones) {
      testWidgets('HelpCenterPage respects notch @ ${d.name}', (tester) async {
        await pumpAtDevice(
          tester,
          _wrap(const HelpCenterPage(mode: HelpCenterMode.public)),
          device: d,
        );
        final mq = MediaQuery.of(tester.element(find.byType(Scaffold)));
        expect(mq.padding.top, d.safeAreaInsets.top,
            reason: 'safe-area top not preserved on ${d.name}');
        expect(mq.padding.bottom, d.safeAreaInsets.bottom,
            reason: 'safe-area bottom not preserved on ${d.name}');
      });
    }
  });

  group('Dashboard pages (loading state) — full viewport matrix', () {
    for (final page in [
      (
        'MemoryPage',
        (bool isMobile) => MemoryPage(
              client: _fakeClient,
              authToken: 'tok',
              vaultName: 'V',
              isMobile: isMobile,
            )
      ),
      (
        'ExpiryPage',
        (bool isMobile) => ExpiryPage(
              client: _fakeClient,
              authToken: 'tok',
              vaultName: 'V',
              isMobile: isMobile,
            )
      ),
      (
        'ConciergePage',
        (bool isMobile) => ConciergePage(
              client: _fakeClient,
              authToken: 'tok',
              vaultName: 'V',
              isMobile: isMobile,
            )
      ),
    ]) {
      final label = page.$1;
      final builder = page.$2;
      for (final d in kFullViewportMatrix) {
        testWidgets('$label @ ${d.name}', (tester) async {
          final app = await _hydrated();
          await _pumpWithProvider(tester, builder(d.width < 600), app, d);
          expectNoOverflow(tester, context: '$label @ ${d.name}');
        });
      }
    }
  });
}
