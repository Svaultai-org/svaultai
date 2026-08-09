import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  print('ENSURE_INITIALIZED_COMPLETED');
  testWidgets('QA driver handshake smoke', (tester) async {
    print('FIRST_TEST_BODY_ENTERED');
    app.main();
    print('APP_MAIN_CALLED');
    await tester.pumpAndSettle(const Duration(seconds: 3));
    print('FIRST_PUMP_ENTERED');
    expect(find.bySemanticsIdentifier('auth_vault_name_field'), findsOneWidget);
    print('AUTH_LANDING_WIDGET_FOUND');
  });
}
