
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/device_pending_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/ui/dashboards/concierge_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/expiry_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/memory_page.dart';
import 'package:vault_ai_frontend/ui/dashboards/relationships_page.dart';

import '_helpers/responsive_harness.dart';


const _fakeClient = VaultAIClient(baseUrl: 'https://unreachable.test.invalid');




Future<AppState> _hydratedAppState({
  bool authed = false,
  String? vaultName,
  String? displayUsername,
  bool locked = true,
}) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final app = AppState();
  await app.hydrate().timeout(
        const Duration(seconds: 5),
        onTimeout: () {},
      );
  if (authed) {
    app.sessionToken = 'sess';
    app.vaultId = 'vault-1';
    app.vaultName = vaultName ?? 'MyVault';
    app.displayUsername = displayUsername ?? 'Alice';
    app.authed = true;
    app.unlocked = !locked;
  }
  return app;
}


Future<void> _pumpWithState(
  WidgetTester tester,
  Widget page,
  AppState app,
  DeviceProfile device,
) async {
  await tester.binding.setSurfaceSize(device.logicalSize);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        home: MediaQuery(
          data: MediaQueryData(
            size: device.logicalSize,
            devicePixelRatio: device.devicePixelRatio,
            padding: device.safeAreaInsets,
          ),
          child: page,
        ),
      ),
    ),
  );
  await tester.pump(const Duration(milliseconds: 200));
}


void _forEachPhone(
  String description,
  Future<void> Function(WidgetTester tester, DeviceProfile device) body,
) {
  for (final d in DeviceProfiles.allPhones) {
    testWidgets('$description @ ${d.name}', (tester) async {
      await body(tester, d);
      expectNoOverflow(tester, context: d.name);
    });
  }
}


void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });


  group('DevicePendingPage (default state)', () {
    _forEachPhone('renders without overflow', (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        const DevicePendingPage(status: 'pending'),
        app,
        device,
      );
    });
  });


  group('DevicePendingPage (with long message)', () {
    _forEachPhone('renders long message without overflow',
        (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        const DevicePendingPage(
          status: 'blocked',
          message:
              'Your device is not yet approved. Ask a trusted device on your account '
              'to approve this device from Security Center → Devices. Approval usually '
              'takes less than a minute if the other device is unlocked. If it does not, '
              'please contact support with the device fingerprint shown below.',
          deviceId: 'device-abcdef-0123456789-abcdef-0123456789',
        ),
        app,
        device,
      );
    });
  });


  group('MemoryPage (loading state)', () {
    _forEachPhone('renders without overflow', (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        MemoryPage(
          client: _fakeClient,
          authToken: 'test-token',
          vaultName: 'MyVault',
          isMobile: device.width < 600,
        ),
        app,
        device,
      );
    });
  });


  group('RelationshipsPage (loading state)', () {
    _forEachPhone('renders without overflow', (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        RelationshipsPage(
          client: _fakeClient,
          authToken: 'test-token',
          vaultName: 'MyVault',
          isMobile: device.width < 600,
        ),
        app,
        device,
      );
    });
  });


  group('ExpiryPage (loading state)', () {
    _forEachPhone('renders without overflow', (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        ExpiryPage(
          client: _fakeClient,
          authToken: 'test-token',
          vaultName: 'MyVault',
          isMobile: device.width < 600,
        ),
        app,
        device,
      );
    });
  });


  group('ConciergePage (loading state)', () {
    _forEachPhone('renders without overflow', (tester, device) async {
      final app = await _hydratedAppState();
      await _pumpWithState(
        tester,
        ConciergePage(
          client: _fakeClient,
          authToken: 'test-token',
          vaultName: 'MyVault',
          isMobile: device.width < 600,
        ),
        app,
        device,
      );
    });
  });
}
