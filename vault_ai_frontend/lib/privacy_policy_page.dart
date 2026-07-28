import 'package:flutter/material.dart';

const String kVaultAiPrivacyRoute = '/privacy';
const String kVaultAiPrivacyUrl = 'https://app.svaultai.com/privacy';
const String kVaultAiPrivacyContactEmail = 'vaultai@svaultai.com';
const String kVaultAiPrivacyEffectiveDate = 'July 28, 2026';

class PrivacyPolicyPage extends StatelessWidget {
  const PrivacyPolicyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;
    final isNarrow = width < 720;

    return Scaffold(
      backgroundColor: const Color(0xFF0F1115),
      appBar: AppBar(
        backgroundColor: const Color(0xFF141414),
        title: const Text('VaultAI Privacy Policy'),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: EdgeInsets.symmetric(
            horizontal: isNarrow ? 18 : 32,
            vertical: isNarrow ? 20 : 36,
          ),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 920),
              child: const _PrivacyPolicyContent(),
            ),
          ),
        ),
      ),
    );
  }
}

class _PrivacyPolicyContent extends StatelessWidget {
  const _PrivacyPolicyContent();

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'VaultAI Privacy Policy',
          style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800),
        ),
        SizedBox(height: 8),
        Text(
          'Effective date: $kVaultAiPrivacyEffectiveDate',
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 15),
        ),
        SizedBox(height: 20),
        _PolicyParagraph(
          'VaultAI, operated by SVaultAI, provides encrypted vault, AI '
          'assistant, inheritance, and wallet tools. This policy explains '
          'what information we collect, how we use it, and the choices you '
          'have. Contact us at $kVaultAiPrivacyContactEmail.',
        ),
        _PolicySection(
          title: 'Information We Collect',
          paragraphs: [
            'Account information: vault name or account identifiers, '
                'authentication state, subscription status, support requests, '
                'and settings you choose.',
            'Device and usage information: device identifiers used for trusted '
                'device controls, session tokens, IP address, user-agent, app '
                'release diagnostics, security events, rate-limit signals, and '
                'basic operational logs.',
            'Vault content: files, images, documents, notes, logins, memories, '
                'metadata, extracted text, OCR results, indexes, embeddings, '
                'and evidence used to provide search and AI answers when you '
                'upload content or authorize vault access.',
            'Inheritance information: beneficiary labels, pairing state, public '
                'keys, encrypted inheritance credential packages, access '
                'release state, re-encryption state, and related audit data.',
            'Wallet information: wallet addresses, balances, transaction '
                'requests, transaction hashes, network identifiers, gas or fee '
                'estimates, and broadcast status. Public blockchain activity '
                'is visible on the relevant network and cannot be deleted by '
                'VaultAI.',
            'Camera, microphone, and uploads: camera or QR input, selected '
                'files, photos, audio, video, and speech input are processed '
                'only when you choose to use those features or grant the '
                'related permission.',
          ],
        ),
        _PolicySection(
          title: 'Encrypted Vault Data and Keys',
          paragraphs: [
            'VaultAI is designed to protect vault content with encryption and '
                'PIN-based access controls. The backend may store encrypted '
                'vault files, encrypted records, encrypted key material, '
                'metadata needed to operate the service, and authorized search '
                'or AI indexes.',
            'Private keys and plaintext vault credentials are not intentionally '
                'collected by the backend as account data. We do not intend to '
                'log passwords, tokens, private keys, PINs, raw vault keys, or '
                'plaintext credentials. Some content you choose to upload or '
                'ask VaultAI to analyze may be processed transiently or stored '
                'in encrypted/indexed form so the service can answer your '
                'vault questions.',
          ],
        ),
        _PolicySection(
          title: 'How We Use Information',
          paragraphs: [
            'We use information to authenticate you, unlock authorized vault '
                'features, store and retrieve your vault items, answer vault '
                'questions, process uploads, provide inheritance workflows, '
                'show wallet information, estimate and submit transactions you '
                'approve, prevent abuse, troubleshoot errors, improve safety, '
                'and meet legal or platform requirements.',
            'We do not sell your personal information. We do not use your '
                'private vault content for advertising.',
          ],
        ),
        _PolicySection(
          title: 'Third-Party Processors',
          paragraphs: [
            'We may use service providers for cloud hosting, databases, object '
                'storage, payment processing, analytics or crash diagnostics, '
                'email or support tooling, AI/ML processing, OCR or media '
                'processing, app distribution, and blockchain RPC or network '
                'services. These providers process information only as needed '
                'to operate VaultAI, comply with law, or provide requested '
                'features.',
            'Payment information is handled by payment processors such as '
                'Stripe or mobile app store billing providers. VaultAI does '
                'not intentionally store full payment card numbers.',
          ],
        ),
        _PolicySection(
          title: 'Retention and Deletion',
          paragraphs: [
            'We keep account, vault, billing, security, and operational data '
                'for as long as needed to provide the service, maintain '
                'security, resolve disputes, comply with law, and support '
                'backup and recovery processes.',
            'To delete your vault and associated account data, open VaultAI, go '
                'to Settings, choose Delete vault, and complete the required '
                'PIN, trusted-device, and confirmation steps. You may also '
                'request help by emailing $kVaultAiPrivacyContactEmail from an '
                'address associated with your account. Some logs, backups, '
                'billing records, legal records, and public blockchain records '
                'may remain for a limited period or as required by law.',
          ],
        ),
        _PolicySection(
          title: 'Security',
          paragraphs: [
            'We use technical and organizational safeguards such as encryption, '
                'PIN-based controls, trusted-device checks, access scoping, '
                'audit signals, and restricted logging. No system is perfectly '
                'secure, and we cannot guarantee absolute security. You are '
                'responsible for protecting your PIN, devices, recovery '
                'materials, and wallet actions.',
          ],
        ),
        _PolicySection(
          title: 'Children',
          paragraphs: [
            'VaultAI is not intended for children under 13 or for users below '
                'the age required by local law to use online services without '
                'parental consent. If you believe a child provided personal '
                'information to VaultAI, contact us so we can review and delete '
                'it where appropriate.',
          ],
        ),
        _PolicySection(
          title: 'Policy Updates',
          paragraphs: [
            'We may update this policy as VaultAI changes. We will change the '
                'effective date above and may provide additional notice in the '
                'app or by other reasonable means. Continued use of VaultAI '
                'after an update means the updated policy applies.',
          ],
        ),
        _PolicySection(
          title: 'Contact',
          paragraphs: [
            'Questions, privacy requests, and deletion requests can be sent to '
                '$kVaultAiPrivacyContactEmail.',
          ],
        ),
        SizedBox(height: 32),
      ],
    );
  }
}

class _PolicySection extends StatelessWidget {
  final String title;
  final List<String> paragraphs;

  const _PolicySection({
    required this.title,
    required this.paragraphs,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 10),
          for (final paragraph in paragraphs) _PolicyParagraph(paragraph),
        ],
      ),
    );
  }
}

class _PolicyParagraph extends StatelessWidget {
  final String text;

  const _PolicyParagraph(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: SelectableText(
        text,
        style: const TextStyle(
          color: Color(0xFFE8EAED),
          fontSize: 16,
          height: 1.58,
        ),
      ),
    );
  }
}
