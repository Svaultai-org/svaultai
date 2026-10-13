import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/attachment_title_binding.dart';

void main() {
  const title = 'QA-TEST WEB File';
  for (final text in [
    'Save this file in my vault as $title',
    'save this file in my vault as $title',
    'SAVE THIS FILE IN MY VAULT AS $title',
    '  Save   this file in my vault as   $title  ',
    'Save this file in my vault as "$title"',
    'Save this file in my vault as $title.',
  ]) {
    test('reported file save prefix binds only its literal title: $text', () {
      expect(attachmentTitleFromComposerText(text, attachmentCount: 1), title);
    });
  }

  for (final count in [0, 2, 3]) {
    test('reported prefix does not choose a file when count is $count', () {
      expect(
          attachmentTitleFromComposerText(
              'Save this file in my vault as $title',
              attachmentCount: count),
          isNull);
    });
  }

  for (final text in [
    '',
    'Save this file in my vault as $title?',
    'Save this file in my vault as QA-TEST\nWEB File',
    'Save this file in my vault as ${'T' * 121}',
  ]) {
    test('existing empty/question/newline/length bound remains: $text', () {
      expect(attachmentTitleFromComposerText(text, attachmentCount: 1), isNull);
    });
  }

  for (final text in [
    'Create a memory from this file',
    'Please save a memory from this file as Trip details',
    'Save a new memory with title File notes and content: trip details',
    'summarize this file',
    'analyze this file and save the credentials',
    'extract the dates from this file',
  ]) {
    test(
        'memory-from-file and analysis instructions are not file titles: $text',
        () {
      expect(attachmentTitleFromComposerText(text, attachmentCount: 1), isNull);
    });
  }

  test('existing naming/title behavior is unchanged', () {
    for (final text in [
      'Save this file as $title',
      'Name this file as $title',
      title,
    ]) {
      expect(attachmentTitleFromComposerText(text, attachmentCount: 1), title);
    }
    expect(
        attachmentTitleFromComposerText(
            'Save this file in my vault as Memory notes',
            attachmentCount: 1),
        'Memory notes');
  });
}
