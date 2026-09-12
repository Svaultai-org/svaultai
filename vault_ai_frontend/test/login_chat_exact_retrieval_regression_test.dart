import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('login chat selects a legacy row by response index', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('case VaultLocalContentKind.login:');
    final end = source.indexOf('case VaultLocalContentKind.memory:', start);
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final body = source.substring(start, end);

    expect(body, contains('resolveVaultLocalContentLabelIndex('));
    expect(body, contains('final row = rows[matchIndex];'));
    expect(body, isNot(contains("'\${row['id']}' == match.entry.id")));
  });

  test('login chat fetches the selected record before rendering details', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('case VaultLocalContentKind.login:');
    final end = source.indexOf('case VaultLocalContentKind.memory:', start);
    final body = source.substring(start, end);

    expect(body, contains('await client.getVaultSecureItem('));
    expect(body, contains("final rawFields = detail['fields'];"));
    expect(body, contains("'fields': fields"));
  });
}
