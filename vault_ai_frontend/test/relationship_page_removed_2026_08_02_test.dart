import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  test('relationship dashboard page and hooks stay removed', () {
    expect(
      File('lib/ui/dashboards/relationships_page.dart').existsSync(),
      isFalse,
    );
    expect(
      File('test/relationships_page_responsive_2026_07_12_test.dart')
          .existsSync(),
      isFalse,
    );

    final main = _read('lib/main.dart');
    final api = _read('lib/api_client.dart');
    final generatedL10n = _read('lib/l10n/app_localizations.dart');

    for (final token in <String>[
      'RelationshipsPage',
      '_DashboardSection.relationships',
      'sidebarRelationships',
      'unlockToSeeRelationships',
      'relationshipsTitle',
      'getRelationshipList',
      '/relationships/list',
    ]) {
      expect(main, isNot(contains(token)));
      expect(api, isNot(contains(token)));
      expect(generatedL10n, isNot(contains(token)));
    }

    expect(main, contains('_DashboardSection.inheritance'));
    expect(api, contains('listInheritances'));
    expect(api, contains('saveInheritanceCredentials'));
  });
}
