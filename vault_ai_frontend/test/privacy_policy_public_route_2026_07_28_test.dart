import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/privacy_policy_page.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('Google Play privacy policy', () {
    test('public route is registered outside the auth landing route', () {
      final main = _read('lib/main.dart');

      expect(main, contains("import 'privacy_policy_page.dart';"));
      expect(main, contains('kVaultAiPrivacyRoute: (_) => const PrivacyPolicyPage()'));
      expect(main, contains("key: const Key('settings_privacy_policy_tile')"));
      expect(main, contains('Navigator.pushNamed('));
    });

    test('static public policy covers required Google Play topics', () {
      final html = _read('web/privacy/index.html');

      for (final required in [
        'SVaultAI',
        'SVaultAI',
        'Effective date: July 28, 2026',
        'vaultai@svaultai.com',
        'Account information',
        'Device and usage information',
        'Vault content',
        'Inheritance information',
        'Wallet information',
        'Camera, microphone, and uploads',
        'Private keys and plaintext vault credentials are not intentionally collected',
        'Third-Party Processors',
        'Retention and Deletion',
        'Delete vault',
        'No system is perfectly secure',
        'Children',
        'Policy Updates',
      ]) {
        expect(html, contains(required), reason: required);
      }

      expect(html.toLowerCase(), isNot(contains('zero data collection')));
      expect(html.toLowerCase(), isNot(contains('100% secure')));
    });

    test('nginx serves /privacy as static html without Flutter execution', () {
      final nginx = _read('../deploy/nginx/app.svaultai.com.conf');

      expect(nginx, contains('location = /privacy'));
      expect(nginx, contains('try_files /privacy/index.html =404'));
    });

    testWidgets('Flutter privacy page renders without an AppState provider',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: PrivacyPolicyPage(),
        ),
      );
      await tester.pump();

      expect(find.text('SVaultAI Privacy Policy'), findsWidgets);
      expect(find.text('Effective date: July 28, 2026'), findsOneWidget);
      expect(find.textContaining('vaultai@svaultai.com'), findsWidgets);
    });
  });
}
