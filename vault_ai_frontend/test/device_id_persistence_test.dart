import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/device_id.dart';


void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  
  group('getOrCreateDeviceId', () {
    test('reads an existing key without rewriting it', () async {
      SharedPreferences.setMockInitialValues({
        deviceIdStorageKey: 'pretend-existing-device-id-with-32-chars',
      });
      final id = await getOrCreateDeviceId();
      expect(id, equals('pretend-existing-device-id-with-32-chars'));

      
      final sp = await SharedPreferences.getInstance();
      expect(sp.getString(deviceIdStorageKey),
          equals('pretend-existing-device-id-with-32-chars'));
    });

    test('generates a new id only when the key is truly absent', () async {
      SharedPreferences.setMockInitialValues({});
      
      
      final id1 = await getOrCreateDeviceId();
      final id2 = await getOrCreateDeviceId();
      expect(id1, equals(id2));
      expect(id1, isNotEmpty);
      
      
      expect(id1.length, greaterThanOrEqualTo(40));
    });
  });

  group('storage-key persistence contract', () {
    
    
    test(
      'only device_id.dart and this test reference the storage key',
      () {
        final libDir = Directory('lib');
        if (!libDir.existsSync()) {
          
          
          return;
        }
        const allowList = {
          'lib/device_id.dart',
          
          
        };
        final offenders = <String>[];
        for (final ent in libDir.listSync(recursive: true)) {
          if (ent is! File) continue;
          if (!ent.path.endsWith('.dart')) continue;
          
          
          final relative = ent.path
              .replaceAll('\\', '/')
              .replaceAll(RegExp(r'^\./'), '');
          if (allowList.contains(relative)) continue;
          final body = ent.readAsStringSync();
          if (body.contains('vaultai_device_id_v1')) {
            offenders.add(relative);
          }
        }
        expect(
          offenders,
          isEmpty,
          reason:
              'These files reference the device-id storage key outside '
              'the owner module. Adding such a reference risks deleting '
              'or rebinding the key on a code path the user did not '
              'intend (sign-out, cache-clear, recovery-wipe). If the '
              'reference is legitimate, add the file to the allow-list '
              'above with a comment justifying why. Offenders: '
              '$offenders',
        );
      },
    );
  });
}
