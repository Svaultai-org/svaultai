import 'package:integration_test/integration_test_driver.dart';

Future<void> main() async {
  print('DRIVER_MAIN_STARTED');
  print('DRIVER_CONNECT_ENTERED');
  await integrationDriver();
  print('DRIVER_RESPONSE_RECEIVED');
}
