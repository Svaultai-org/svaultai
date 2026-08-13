import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Concierge has no user-facing frontend entry point', () {
    final mainSource = File('lib/main.dart').readAsStringSync();

    expect(mainSource, isNot(contains("ui/dashboards/concierge_page.dart")));
    expect(mainSource, isNot(contains('_DashboardSection.concierge')));
    expect(mainSource, isNot(contains('sidebarConcierge')));
    expect(mainSource, isNot(contains("type == 'travel_readiness'")));
    expect(mainSource, isNot(contains("kind: 'travel_readiness'")));
  });

  test('Concierge implementation remains available for later reintroduction',
      () {
    expect(File('lib/ui/dashboards/concierge_page.dart').existsSync(), isTrue);
  });
}
