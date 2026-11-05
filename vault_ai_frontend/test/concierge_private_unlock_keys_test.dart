import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show VaultCryptoContext, conciergeKeysAllowBinding;

void main() {
  final mvk = SecretKey(List<int>.filled(32, 4));
  final oldContext = VaultCryptoContext(
    vaultId: 'synthetic-vault',
    vaultName: 'Synthetic vault',
    key: SecretKey(List<int>.filled(32, 9)),
    pin: '123456',
    saltBase64: 'synthetic',
    iterations: 1,
    generation: 1,
    source: 'synthetic-legacy',
  );

  test('Concierge accepts MVK-only private unlock and rejects stale key state',
      () {
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: null,
        mvk: mvk,
        mvkVaultId: 'synthetic-vault',
        privateOnly: true,
      ),
      isTrue,
    );
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: oldContext,
        mvk: mvk,
        mvkVaultId: 'synthetic-vault',
        privateOnly: true,
      ),
      isFalse,
    );
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: null,
        mvk: mvk,
        mvkVaultId: 'another-vault',
        privateOnly: true,
      ),
      isFalse,
    );
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: null,
        mvk: null,
        mvkVaultId: 'synthetic-vault',
        privateOnly: true,
      ),
      isFalse,
    );
  });

  test('ordinary Concierge still requires its original matching context', () {
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: oldContext,
        mvk: mvk,
        mvkVaultId: 'synthetic-vault',
        privateOnly: false,
      ),
      isTrue,
    );
    expect(
      conciergeKeysAllowBinding(
        vaultId: 'synthetic-vault',
        keyContext: null,
        mvk: mvk,
        mvkVaultId: 'synthetic-vault',
        privateOnly: false,
      ),
      isFalse,
    );
  });
}
