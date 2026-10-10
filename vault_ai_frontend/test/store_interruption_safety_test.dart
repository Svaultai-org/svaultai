import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('store prompts wait for file view and download completion', () {
    final app = AppState();
    addTearDown(app.dispose);
    expect(app.storeInterruptionAllowed, isTrue);
    expect(app.beginFileView('demo-file'), isTrue);
    expect(app.storeInterruptionAllowed, isFalse);
    app.endFileView('demo-file');
    expect(app.storeInterruptionAllowed, isTrue);
    expect(app.beginFileDownload('demo-file'), isTrue);
    expect(app.storeInterruptionAllowed, isFalse);
    app.endFileDownload('demo-file');
    expect(app.storeInterruptionAllowed, isTrue);
  });

  test('dashboard operations defer store UI without altering inactivity', () {
    final app = AppState();
    addTearDown(app.dispose);
    app.unlocked = true;
    var busy = true;
    bool probe() => busy;
    app.registerStoreInterruptionProbe(probe);
    app.registerStoreInterruptionProbe(probe);
    expect(app.storeInterruptionAllowed, isFalse);
    expect(app.shouldLockOnInactivityExpiry(), isTrue);
    busy = false;
    expect(app.storeInterruptionAllowed, isTrue);
    busy = true;
    app.unregisterStoreInterruptionProbe(probe);
    expect(app.storeInterruptionAllowed, isTrue);
  });

  test('native picker and active uploads defer store UI', () async {
    final app = AppState();
    addTearDown(app.dispose);
    await app.runWithNativePickerKeepAlive(() async {
      expect(app.storeInterruptionAllowed, isFalse);
    });
    expect(app.storeInterruptionAllowed, isTrue);
    bool uploadProbe() => true;
    app.registerKeepAliveProbe(uploadProbe);
    expect(app.storeInterruptionAllowed, isFalse);
    app.unregisterKeepAliveProbe(uploadProbe);
    expect(app.storeInterruptionAllowed, isTrue);
  });

  test('unreadable busy probe defers rather than interrupting', () {
    final app = AppState();
    addTearDown(app.dispose);
    bool probe() => throw StateError('unavailable');
    app.registerStoreInterruptionProbe(probe);
    expect(app.storeInterruptionAllowed, isFalse);
    app.unregisterStoreInterruptionProbe(probe);
    expect(app.storeInterruptionAllowed, isTrue);
  });
}
