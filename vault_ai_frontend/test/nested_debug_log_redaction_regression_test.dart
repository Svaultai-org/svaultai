import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('debug logging recursively redacts nested vault identity values', () {
    for (final path in ['lib/main.dart', 'lib/api_client.dart']) {
      final source = File(path).readAsStringSync();
      final helperStart = source.indexOf('String _safeVlogValue(');
      final helperEnd = source.indexOf('\n}\n', helperStart);
      final helper = source.substring(helperStart, helperEnd);

      expect(helper, contains('if (value is Map)'));
      expect(
        helper,
        contains('_safeVlogValue(tag, nestedKey, entry.value)'),
      );
    }
  });
}
