import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/saved_item_mutation_feedback.dart';

void main() {
  test('exact structured409 code gives safe update instruction', () {
    expect(() => throwIfSavedItemUpdateRequired(409,
        '{"detail":{"code":"update_app_required","message":"untrusted server text"}}'),
        throwsA(isA<SavedItemUpdateRequiredException>().having(
            (error) => error.toString(), 'message', savedItemUpdateRequiredMessage)));
    expect(savedItemUpdateRequiredMessage, contains('Update SVaultAI'));
    expect(savedItemUpdateRequiredMessage, contains('saved data is still available'));
  });

  for (final body in [
    '{"detail":{"code":"duplicate_saved_item"}}',
    '{"detail":{"code":"ambiguous_saved_item"}}',
    '{"detail":{"code":"update_app_required_other"}}',
    '{"detail":{"code":"UPDATE_APP_REQUIRED"}}',
    '{"detail":"update_app_required"}',
    '{"message":"update_app_required"}',
    'not-json',
  ]) {
    test('only exact backend code, not misleading text or other conflict, requires update: $body', () {
      expect(() => throwIfSavedItemUpdateRequired(409, body), returnsNormally);
    });
  }

  test('different status with same text is not misclassified as update requirement', () {
    expect(() => throwIfSavedItemUpdateRequired(400,
        '{"detail":{"code":"update_app_required"}}'), returnsNormally);
  });

  test('normal dashboard, generated-login and Concierge UI catches show dedicated message', () {
    final source = File('lib/main.dart').readAsStringSync();
    final editor = File('lib/ui/secure_item_detail.dart').readAsStringSync();
    expect(editor, contains('error is SavedItemUpdateRequiredException'));
    final editorCallback = source.substring(
        source.indexOf('Future<void> _openSecureItemEditDialog('),
        source.indexOf('bool _isCryptoItemType('));
    expect(editorCallback, contains('if (app.handleApiException(e)) return false;'));
    expect(editorCallback, contains('rethrow;'));
    expect(source, contains('on SavedItemUpdateRequiredException catch (e)'));
    expect(source, contains('_showSnack(e.toString())'));
    final repository = File('lib/services/concierge_exposure.dart').readAsStringSync();
    expect(repository, contains('on SavedItemUpdateRequiredException'));
    expect(repository, contains('throwIfSavedItemUpdateRequired(response.statusCode, response.body)'));
  });
}
