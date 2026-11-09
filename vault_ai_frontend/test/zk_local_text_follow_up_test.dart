import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_local_text_follow_up.dart';

void main() {
  test('selected older text follow-up answers locally and clears bytes', () {
    final bytes = Uint8List.fromList(utf8.encode('My private note'));
    final excerpt = localTextFollowUpExcerpt(
      bytes: bytes,
      fileName: 'note.txt',
      mimeType: 'text/plain',
      accessIsCurrent: () => true,
    );
    expect(excerpt, contains('My private note'));
    expect(bytes, everyElement(0));
  });

  test('binary content is not displayed and its bytes are cleared', () {
    final bytes = Uint8List.fromList([1, 2, 3, 4]);
    final excerpt = localTextFollowUpExcerpt(
      bytes: bytes,
      fileName: 'note.txt',
      mimeType: 'application/pdf',
      accessIsCurrent: () => true,
    );
    expect(excerpt, isNull);
    expect(bytes, everyElement(0));
  });

  test('lost vault access clears the buffer before a reply', () {
    final bytes = Uint8List.fromList(utf8.encode('Sensitive text'));
    expect(
      () => localTextFollowUpExcerpt(
        bytes: bytes,
        fileName: 'note.txt',
        mimeType: 'text/plain',
        accessIsCurrent: () => false,
      ),
      throwsStateError,
    );
    expect(bytes, everyElement(0));
  });

  test('oversized text is rejected and cleared', () {
    final bytes = Uint8List(maxLocalTextFollowUpBytes + 1);
    expect(
      () => localTextFollowUpExcerpt(
        bytes: bytes,
        fileName: 'note.txt',
        mimeType: 'text/plain',
        accessIsCurrent: () => true,
      ),
      throwsFormatException,
    );
    expect(bytes, everyElement(0));
  });
}
