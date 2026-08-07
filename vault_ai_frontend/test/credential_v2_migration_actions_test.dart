import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';

void main() {
  test('rollback is offered only for migration lifecycle records', () {
    VaultLoginItem item(String state) => VaultLoginItem(
          service: 'QA',
          cryptoVersion: 'client_mvk_v2',
          migrationState: state,
        );
    expect(isCredentialV2RollbackEligible(item('migration_pending')), isTrue);
    expect(isCredentialV2RollbackEligible(item('v2_verified')), isTrue);
    expect(isCredentialV2RollbackEligible(item('migrated')), isTrue);
    expect(isCredentialV2RollbackEligible(item('rollback_pending')), isTrue);
    expect(isCredentialV2RollbackEligible(item('v2_written')), isFalse);
    expect(isCredentialV2RollbackEligible(item('rolled_back')), isFalse);
  });
  testWidgets('QA migration actions are scoped by crypto version and type',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(2400, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: LoginsPage(
          logins: const [
            VaultLoginItem(
              service: 'Legacy login',
              itemType: 'login',
              cryptoVersion: 'legacy_v1',
            ),
            VaultLoginItem(
              service: 'V2 login',
              itemType: 'login',
              cryptoVersion: 'client_mvk_v2',
              migrationState: 'v2_verified',
            ),
            VaultLoginItem(
              service: 'Legacy note',
              itemType: 'private_note',
              cryptoVersion: 'legacy_v1',
            ),
          ],
          vaultLabel: 'QA',
          isLoading: false,
          hasLoaded: true,
          onRefresh: () async {},
          onMigrateItem: (_) {},
          onRollbackItem: (_) {},
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Migrate to v2 (QA)'), findsOneWidget);
    expect(find.text('Rollback v2 (QA)'), findsOneWidget);
    expect(
      find.byKey(const Key('credential_v2_migrate_login-Legacy login')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('credential_v2_rollback_login-V2 login')),
      findsOneWidget,
    );
    expect(
      find.byKey(
        const Key('credential_v2_migrate_private_note-Legacy note'),
      ),
      findsNothing,
    );
  });
}
