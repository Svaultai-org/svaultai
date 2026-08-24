import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('desktop composer sends on Enter and Ctrl+Enter', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(
        source,
        contains(
            'HardwareKeyboard.instance.addHandler(_onComposerHardwareKey)'));
    expect(source, contains('_composerFocusNode.hasFocus'));
    expect(source, contains('event.logicalKey != LogicalKeyboardKey.enter'));
    expect(source, contains('unawaited(_submitComposer())'));
    expect(source, contains('return true'));
    expect(source, contains("input.text.endsWith('\\n')"));
    expect(source, contains('withoutSubmitNewline'));
  });

  test('Shift+Enter and Alt+Enter remain newline actions', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('keyboard.isShiftPressed'));
    expect(source, contains('keyboard.isAltPressed'));
    expect(source, contains('TextInputAction.newline'));
  });

  test('submission shares one guarded lifecycle', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('bool _composerSubmitStarting = false;'));
    expect(
      source,
      contains(RegExp(
        r'_composerSubmitStarting\s*\|\|\s*sending\s*\|\|\s*_composerIsComposing',
      )),
    );
    expect(
        source, contains('input.text.trim().isEmpty && attachments.isEmpty'));
    expect(source, contains('(canSend ? _submitComposer : null)'));
    expect(source,
        contains('onSubmitted: canSend ? (_) => _submitComposer() : null'));
  });

  test('text send appends the user bubble before local routing', () async {
    final source = await File('lib/main.dart').readAsString();
    final bubble = source.indexOf('USER_BUBBLE_APPENDED_AT=');
    final routing = source.indexOf('ROUTING_STARTED_AT=');
    final arbitration = source.indexOf(
      'await _tryLocalPrivateDomainArbitration(text, app)',
    );
    expect(bubble, greaterThan(0));
    expect(routing, greaterThan(bubble));
    expect(arbitration, greaterThan(routing));
  });

  test('mobile composer exposes software-keyboard Send', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(
      source,
      contains('isMobile ? TextInputAction.send : TextInputAction.newline'),
    );
    expect(
      source,
      contains('onSubmitted: canSend ? (_) => _submitComposer() : null'),
    );
  });
}
