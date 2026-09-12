import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('speech permission is requested only after the user taps voice input',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    final dashboardStart = source.indexOf('class _ChatDashboardPageState');
    final initStart = source.indexOf('void initState()', dashboardStart);
    final initEnd = source.indexOf('Future<void> _initSpeech()', initStart);
    final initState = source.substring(initStart, initEnd);
    final toggleStart = source.indexOf('Future<void> _toggleListening()');
    final toggleEnd = source.indexOf('\n  }', toggleStart);
    final toggle = source.substring(toggleStart, toggleEnd);

    expect(initState, isNot(contains('_initSpeech();')));
    expect(toggle, contains('await _initSpeech();'));
  });
}
