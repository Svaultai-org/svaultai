import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/recovery_kit_settings_page.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart'
    as zk_mvk_store;

String _readMain() => File('lib/main.dart').readAsStringSync();

Widget _wrap(Widget child) {
  return MaterialApp(
    home: ChangeNotifierProvider<AppState>(
      create: (_) => AppState(),
      child: child,
    ),
  );
}

void main() {
  setUp(() {
    zk_mvk_store.ZkActiveMvk.clear();
  });

  group('RecoveryKitSettingsPage', () {
    testWidgets('renders explanation + enable button (disabled) '
        'when the current vault is legacy (no ZK MVK active)',
        (tester) async {
      zk_mvk_store.ZkActiveMvk.clear();
      await tester.pumpWidget(
        _wrap(const RecoveryKitSettingsPage()),
      );
      expect(find.text('Recovery Kit'), findsWidgets);
      expect(
        find.byKey(const Key('recovery_kit_enable_button')),
        findsOneWidget,
      );
      // Button is disabled when no ZK MVK is active.
      final btn = tester.widget<FilledButton>(
        find.byKey(const Key('recovery_kit_enable_button')),
      );
      expect(btn.onPressed, isNull,
          reason: 'the Enable button must be disabled for legacy '
                  '(non-ZK) vaults');
    });

    testWidgets('the Enable button is ENABLED when a ZK MVK is '
        'active', (tester) async {
      zk_mvk_store.ZkActiveMvk.set(
        mvk: SecretKey(List<int>.generate(32, (i) => i)),
        vaultId: 'v1',
        vaultHandle: 'VLT-TEST-ENAB',
      );
      await tester.pumpWidget(
        _wrap(const RecoveryKitSettingsPage()),
      );
      final btn = tester.widget<FilledButton>(
        find.byKey(const Key('recovery_kit_enable_button')),
      );
      expect(btn.onPressed, isNotNull,
          reason: 'the Enable button must be pressable once the '
                  'vault is unlocked in ZK mode');
    });
  });

  group('Route wiring + Settings tile', () {
    test('main.dart registers /recovery-kit and the settings tile '
        'navigates to it', () {
      final src = _readMain();
      expect(
        src,
        contains("'/recovery-kit': (_) => const RecoveryKitSettingsPage()"),
        reason: 'the /recovery-kit route must be registered',
      );
      expect(
        src,
        contains("Key('settings_recovery_kit_tile')"),
        reason: 'the settings section must expose a keyed tile',
      );
      final tileIdx =
          src.indexOf("Key('settings_recovery_kit_tile')");
      final windowEnd =
          (tileIdx + 800).clamp(0, src.length);
      final window = src.substring(tileIdx, windowEnd);
      expect(
        window,
        contains("pushNamed('/recovery-kit')"),
        reason: 'the tile must navigate via pushNamed to the '
                'recovery-kit route',
      );
    });
  });
}
