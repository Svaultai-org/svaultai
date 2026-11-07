import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  test('strict PIN-free release refuses incomplete wallet access', () async {
    expect(app.kZkPrivateOnlyClientReady, isTrue);
    expect(app.kPrivateWalletFeatureParityReady, isFalse);
    await expectLater(
      app.main(),
      throwsA(isA<StateError>().having(
        (error) => error.message,
        'message',
        contains('PIN-free wallet access'),
      )),
    );
  }, skip: !app.kPrivateOnlyUnlockEnabled || !app.kZkPrivateOnlyClientReady);
}
