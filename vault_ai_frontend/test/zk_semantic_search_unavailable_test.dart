import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show
    ZkSemanticSearchUnavailableBanner;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart'
    as zk_mvk_store;

String _readMain() => File('lib/main.dart').readAsStringSync();
String _readSecurity() =>
    File('lib/security_center_page.dart').readAsStringSync();

Widget _wrap(Widget w) => MaterialApp(home: Scaffold(body: w));

void main() {
  setUp(() {
    // Reset the process-global ZK MVK holder between tests.
    zk_mvk_store.ZkActiveMvk.clear();
  });

  group('ZkSemanticSearchUnavailableBanner widget contract', () {
    testWidgets('renders NOTHING when no ZK MVK is active — legacy '
        'vaults still see the existing search UI unadorned',
        (tester) async {
      zk_mvk_store.ZkActiveMvk.clear();
      await tester.pumpWidget(
        _wrap(const ZkSemanticSearchUnavailableBanner()),
      );
      expect(
        find.byKey(const Key('zk_semantic_search_unavailable_banner')),
        findsNothing,
      );
    });

    testWidgets('renders the banner when a ZK MVK is set — the copy '
        'explains unavailability without implying success',
        (tester) async {
      zk_mvk_store.ZkActiveMvk.set(
        mvk: SecretKey(List<int>.generate(32, (i) => i)),
        vaultId: 'test-vault',
        vaultHandle: 'VLT-TEST-BANNER',
      );
      await tester.pumpWidget(
        _wrap(const ZkSemanticSearchUnavailableBanner()),
      );
      expect(
        find.byKey(const Key('zk_semantic_search_unavailable_banner')),
        findsOneWidget,
      );
      expect(
        find.textContaining('Semantic content search is unavailable'),
        findsOneWidget,
        reason: 'The banner must state unavailability explicitly',
      );
      expect(
        find.textContaining('Filename search still works'),
        findsOneWidget,
        reason: 'The banner must reassure the user that filename '
                'search still functions',
      );
    });
  });

  group('Vault dashboard mounts the banner above the FolderBrowser',
      () {
    test('main.dart places const ZkSemanticSearchUnavailableBanner() '
        'immediately before FolderBrowser', () {
      final src = _readMain();
      // Scan for the widget CONSTRUCTION site (const ... Banner())
      // — not the class declaration — that must sit above the
      // FolderBrowser mount.
      final construction = src.indexOf(
        'const ZkSemanticSearchUnavailableBanner()',
      );
      expect(construction, greaterThan(-1),
          reason: 'the banner widget must be constructed and '
                  'mounted somewhere in main.dart');
      final browser = src.indexOf('FolderBrowser(', construction);
      expect(browser, greaterThan(construction),
          reason: 'the banner must sit ABOVE the FolderBrowser '
                  'search field so users see the "unavailable" '
                  'notice before typing');
      expect(browser - construction, lessThan(600),
          reason: 'the banner must be close to the FolderBrowser '
                  'mount, not scattered elsewhere in the widget '
                  'tree');
    });
  });

  group('Security Center reflects ZK semantic-search unavailability',
      () {
    test('security_center_page.dart shows "Unavailable (private '
        'vault)" instead of Enabled/Disabled when ZK is active', () {
      final src = _readSecurity();
      expect(
        src,
        contains("'Unavailable (private vault)'"),
        reason: 'Security Center must render the explicit '
                'unavailability label for ZK vaults, not just '
                '"Disabled"',
      );
      expect(
        src,
        contains('zk_mvk_store.ZkActiveMvk.current() != null'),
        reason: 'the branch must gate on ZkActiveMvk',
      );
      expect(
        src,
        contains(
          "Key('zk_semantic_search_unavailable_note')",
        ),
        reason: 'a keyed follow-up note must explain WHY it is '
                'unavailable',
      );
    });
  });
}
