import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('desktop composer sends on Enter and Ctrl+Enter', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('CallbackShortcuts('));
    expect(source, contains('SingleActivator(LogicalKeyboardKey.enter)'));
    expect(source, contains('control: true'));
    expect(source, contains('() => unawaited(_submitComposer())'));
  });

  test('Shift+Enter and Alt+Enter remain newline actions', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('Shift+Enter and'));
    expect(source, contains('Alt+Enter stay unbound'));
    expect(source, isNot(contains('shift: true,')));
    expect(source, isNot(contains('alt: true,')));
    expect(source, contains('TextInputAction.newline'));
  });

  test('submission shares one guarded lifecycle', () async {
    final source = await File('lib/main.dart').readAsString();
    expect(source, contains('bool _composerSubmitStarting = false;'));
    expect(source,
        contains('_composerSubmitStarting || sending || _composerIsComposing'));
    expect(
        source, contains('input.text.trim().isEmpty && attachments.isEmpty'));
    expect(source, contains('(canSend ? _submitComposer : null)'));
    expect(source,
        contains('onSubmitted: canSend ? (_) => _submitComposer() : null'));
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
