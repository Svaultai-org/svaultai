import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/inheritance_pairing_page.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart'
    as zk_mvk_store;

String _readMain() => File('lib/main.dart').readAsStringSync();

Widget _wrap(Widget w) => MaterialApp(
      home: ChangeNotifierProvider<AppState>(
        create: (_) => AppState(),
        child: w,
      ),
    );

void main() {
  setUp(() {
    zk_mvk_store.ZkActiveMvk.clear();
  });

  group('InheritancePairingPage', () {
    testWidgets('renders the explanation card + steps card '
        'unconditionally', (tester) async {
      zk_mvk_store.ZkActiveMvk.clear();
      await tester.pumpWidget(_wrap(const InheritancePairingPage()));
      expect(find.text('Inheritance pairing'), findsWidgets);
      expect(
        find.byKey(const Key('inheritance_open_dashboard_button')),
        findsOneWidget,
      );
      // No ZK self-check card when no MVK is active.
      expect(
        find.byKey(const Key('zk_envelope_selfcheck_card')),
        findsNothing,
      );
    });

    testWidgets('renders the ZK envelope self-check card only when '
        'a ZK MVK is active', (tester) async {
      zk_mvk_store.ZkActiveMvk.set(
        mvk: SecretKey(List<int>.generate(32, (i) => i)),
        vaultId: 'v1',
        vaultHandle: 'VLT-TEST-INH',
      );
      await tester.pumpWidget(_wrap(const InheritancePairingPage()));
      expect(
        find.byKey(const Key('zk_envelope_selfcheck_card')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('zk_envelope_link_id_input')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('zk_envelope_run_selfcheck_button')),
        findsOneWidget,
      );
    });
  });

  group('Route wiring + Settings tile', () {
    test('/inheritance-pairing is registered and the settings tile '
        'navigates to it', () {
      final src = _readMain();
      expect(
        src,
        contains(
          "'/inheritance-pairing': (_) => const InheritancePairingPage()",
        ),
        reason: 'the /inheritance-pairing route must be registered',
      );
      expect(
        src,
        contains("Key('settings_inheritance_pairing_tile')"),
        reason: 'the settings section must expose a keyed tile for '
                'inheritance pairing',
      );
      final tileIdx = src.indexOf(
        "Key('settings_inheritance_pairing_tile')",
      );
      final window = src.substring(
        tileIdx, (tileIdx + 800).clamp(0, src.length),
      );
      expect(
        window,
        contains("pushNamed('/inheritance-pairing')"),
        reason: 'the tile must navigate via pushNamed to the '
                'inheritance-pairing route',
      );
    });
  });
}
