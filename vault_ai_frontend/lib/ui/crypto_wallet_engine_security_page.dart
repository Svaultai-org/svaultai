

import 'package:flutter/material.dart';

import 'crypto_wallet_engine_design.dart';

const String kCryptoWalletSecurityPageTitle = 'Security';

const String kCryptoWalletSecurityHeading =
    'Your wallet, your keys, your call';
const String kCryptoWalletSecuritySubheading =
    'Wallet backups are encrypted on this device with your PIN. '
    'Svaultai cannot decrypt or move your funds. Reveal flows always '
    'require your PIN.';

const String kCryptoWalletSecurityStatusHeading = 'Security status';
const String kCryptoWalletSecurityStatusBody =
    'Non-custodial: backups stored as ciphertext only. The backend '
    'never holds a plaintext private key, seed phrase, or recovery '
    'phrase. Local signing happens after PIN re-verification.';

const String kCryptoWalletSecurityBackupHeading =
    'Encrypted wallet backups';
const String kCryptoWalletSecurityBackupBody =
    'Each wallet you create is encrypted with your PIN-derived vault '
    'key and stored as ciphertext. Reveal asks for your PIN every '
    'time; the plaintext never reaches the backend or any log line.';

const String kCryptoWalletSecurityRecoveryHeading = 'Recovery guidance';
const String kCryptoWalletSecurityRecoveryBody =
    'Write down your PIN somewhere safe and offline. Losing it means '
    'losing access to the encrypted backups on this device. Svaultai '
    'cannot reset your PIN — there is no custodial recovery path.';

const String kCryptoWalletSecurityDeviceHeading = 'Device + PIN safety';
const String kCryptoWalletSecurityDeviceBody =
    'Only unlock the vault on devices you trust. The PIN derives the '
    'AES-GCM-256 key that protects every wallet backup. A leaked PIN '
    'on a compromised device exposes the backups stored there.';

const String kCryptoWalletSecurityRemindHeading = 'Non-custodial reminder';
const String kCryptoWalletSecurityRemindBody =
    'Svaultai cannot move your funds. Every Send action signs locally '
    'after your PIN confirmation; the backend only broadcasts the '
    'signed transaction. No buy, sell, swap, trade, stake, or bridge '
    'surface exists in this product.';

class CryptoWalletEngineSecurityPage extends StatelessWidget {
  const CryptoWalletEngineSecurityPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: walletDarkPanelTheme(context),
      child: Scaffold(
        key: const Key('crypto_wallet_engine_security_page'),
        backgroundColor: kWalletBgBase,
        appBar: AppBar(
          backgroundColor: kWalletBgBase,
          surfaceTintColor: kWalletBgBase,
          foregroundColor: kWalletTextPrimary,
          elevation: 0,
          title: const Text(
            kCryptoWalletSecurityPageTitle,
            key: Key('crypto_wallet_engine_security_page_title'),
            style: TextStyle(
              color: kWalletTextPrimary,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        body: DecoratedBox(
          decoration: walletPageBackground(),
          child: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(18),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 700),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _buildHero(),
                      const SizedBox(height: 16),
                      _buildStatusCard(),
                      const SizedBox(height: 12),
                      _buildSection(
                        keyName:
                            'crypto_wallet_engine_security_backup_card',
                        icon: Icons.lock_outline,
                        heading: kCryptoWalletSecurityBackupHeading,
                        body: kCryptoWalletSecurityBackupBody,
                      ),
                      const SizedBox(height: 12),
                      _buildSection(
                        keyName:
                            'crypto_wallet_engine_security_recovery_card',
                        icon: Icons.refresh_rounded,
                        heading: kCryptoWalletSecurityRecoveryHeading,
                        body: kCryptoWalletSecurityRecoveryBody,
                      ),
                      const SizedBox(height: 12),
                      _buildSection(
                        keyName:
                            'crypto_wallet_engine_security_device_card',
                        icon: Icons.smartphone_outlined,
                        heading: kCryptoWalletSecurityDeviceHeading,
                        body: kCryptoWalletSecurityDeviceBody,
                      ),
                      const SizedBox(height: 12),
                      _buildSection(
                        keyName:
                            'crypto_wallet_engine_security_reminder_card',
                        icon: Icons.shield_outlined,
                        heading: kCryptoWalletSecurityRemindHeading,
                        body: kCryptoWalletSecurityRemindBody,
                      ),
                      const SizedBox(height: 18),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHero() {
    return Container(
      key: const Key('crypto_wallet_engine_security_hero'),
      padding: const EdgeInsets.all(18),
      decoration: walletDarkCard(accent: kWalletAccentSuccess),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36, height: 36,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      kWalletAccentSuccess,
                      Color(0xFF1F4E2F),
                    ],
                  ),
                ),
                alignment: Alignment.center,
                child: const Icon(
                  Icons.shield_rounded,
                  size: 18, color: Colors.white,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: walletStatusBadge(
                  'Non-custodial',
                  tone: WalletBadgeTone.live,
                  key: const Key(
                    'crypto_wallet_engine_security_hero_badge',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          const Text(
            kCryptoWalletSecurityHeading,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 22,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            kCryptoWalletSecuritySubheading,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard() {
    return Container(
      key: const Key('crypto_wallet_engine_security_status_card'),
      padding: const EdgeInsets.all(16),
      decoration: walletSuccessPanel(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.verified_user_outlined,
                  size: 18, color: kWalletAccentSuccess),
              SizedBox(width: 8),
              Text(
                kCryptoWalletSecurityStatusHeading,
                style: TextStyle(
                  color: kWalletAccentSuccess,
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            kCryptoWalletSecurityStatusBody,
            style: TextStyle(
              color: kWalletAccentSuccess,
              fontSize: 13,
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSection({
    required String keyName,
    required IconData icon,
    required String heading,
    required String body,
  }) {
    return Container(
      key: Key(keyName),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: kWalletTextSecondary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  heading,
                  style: kWalletSectionHeadingStyle,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            body,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }
}
