import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('empty Files screen keeps a production refresh recovery action', () {
    final source = File('lib/main.dart').readAsStringSync();
    final filesSection = source.substring(
      source.indexOf('Widget _buildFilesSection(bool isMobile)'),
      source.indexOf(
          'Widget _buildVaultFileCard(',
          source.indexOf(
            'Widget _buildFilesSection(bool isMobile)',
          )),
    );

    expect(filesSection, contains("Key('files_empty_refresh_button')"));
    expect(filesSection, contains('onPressed: _loadVaultFiles'));
  });
}
