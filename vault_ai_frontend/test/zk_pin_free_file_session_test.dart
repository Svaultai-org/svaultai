import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';

void main() {
  setUp(() {
    SessionTermination.instance.resetForTests();
    ZkPinFreeFileSession.instance.clear();
  });
  tearDown(() {
    ZkPinFreeFileSession.instance.clear();
    SessionTermination.instance.resetForTests();
  });

  test('file offers bind to the exact bearer and expire on replacement', () {
    SessionTermination.instance.bindSession('first-session');
    ZkPinFreeFileSession.instance.bind(
      sessionToken: 'first-session',
      listOffered: true,
      downloadOffered: true,
    );
    expect(ZkPinFreeFileSession.instance.listOfferedForToken('first-session'),
        isTrue);
    expect(
        ZkPinFreeFileSession.instance.downloadOfferedForToken('first-session'),
        isTrue);
    expect(ZkPinFreeFileSession.instance.downloadOfferedForToken('other'),
        isFalse);
    SessionTermination.instance.bindSession('second-session');
    expect(ZkPinFreeFileSession.instance.listOfferedForToken('first-session'),
        isFalse);
    expect(
        ZkPinFreeFileSession.instance.downloadOfferedForToken('second-session'),
        isFalse);
  });
}
