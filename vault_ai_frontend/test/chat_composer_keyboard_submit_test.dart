import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('desktop composer sends on Enter and preserves Shift+Enter', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('event.logicalKey == LogicalKeyboardKey.enter'));
    expect(source, contains('!HardwareKeyboard.instance.isShiftPressed'));
    expect(source, contains('if (canSend) _send();'));
    expect(source, contains('return KeyEventResult.handled;'));
    expect(source, contains('return KeyEventResult.ignored;'));
  });

  test('mobile composer exposes software-keyboard Send', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(
      source,
      contains('isMobile ? TextInputAction.send : TextInputAction.newline'),
    );
    expect(
      source,
      contains('onSubmitted: isMobile && canSend ? (_) => _send() : null'),
    );
  });
}
