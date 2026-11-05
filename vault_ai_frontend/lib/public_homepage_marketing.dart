import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'public_download_badges.dart';

// Public presentation only. Existing routes and services own account access,
// subscriptions and the beneficiary release rules.
const String kPublicHomepageHeadline =
    'Your digital life.\nOne encrypted vault.';
const String kPublicHomepageOpening =
    'Keep files, photos, logins and memories together. Find what you need with AI, '
    'manage supported digital assets and crypto, and prepare access for someone you trust.';
const String kPublicHomepageInheritanceHeading =
    'Prepare access for someone you trust.';
const String kPublicHomepageInheritance =
    'A paired beneficiary can request access if they believe the vault owner '
    'has died. The owner signs in to approve or decline. Approval releases the '
    'prepared credentials immediately, with no 30-day wait. Declining clears '
    'the request and returns the arrangement to normal. An unanswered request '
    'has a countdown, normally 30 days; after it expires, the beneficiary can '
    'claim the credentials. The app shows the actual deadline. SVaultAI does '
    'not verify death or automatically transfer assets.';
const String kPublicHomepageCtaHeading = 'Start with your free 1 GB vault.';
const String kPublicHomepageCtaButton = 'Create your free vault';
const String kPublicHomepageCtaCaption =
    '1 GB included · No email or phone number required · Optional paid storage';

const _blue = Color(0xFF77B8FF);
const _muted = Color(0xFFB9C6D8);
const _body = TextStyle(color: _muted, fontSize: 16, height: 1.55);

Future<void> _openPublicPage(String path) async {
  await launchUrl(
    Uri.parse('https://app.svaultai.com$path'),
    mode: kIsWeb ? LaunchMode.platformDefault : LaunchMode.externalApplication,
    webOnlyWindowName: kIsWeb ? '_blank' : null,
  );
}

Widget _heading(BuildContext context, String text) => Text(
  text,
  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
    fontWeight: FontWeight.w800,
    height: 1.2,
    color: Colors.white,
  ),
);

class PublicHomepageHero extends StatelessWidget {
  const PublicHomepageHero({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'SVaultAI · ENCRYPTED DIGITAL VAULT',
          style: TextStyle(
            color: _blue,
            fontWeight: FontWeight.w700,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 18),
        Text(
          kPublicHomepageHeadline,
          style: Theme.of(context).textTheme.headlineLarge?.copyWith(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            height: 1.08,
            letterSpacing: -1,
          ),
        ),
        const SizedBox(height: 20),
        const Text(kPublicHomepageOpening, style: _body),
        const SizedBox(height: 24),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            FilledButton(
              key: const Key('public_homepage_primary_cta'),
              style: FilledButton.styleFrom(
                backgroundColor: _blue,
                foregroundColor: const Color(0xFF091B30),
                padding: const EdgeInsets.symmetric(
                  horizontal: 22,
                  vertical: 18,
                ),
              ),
              onPressed: () => Navigator.pushNamed(context, '/signup'),
              child: const Text(kPublicHomepageCtaButton),
            ),
            OutlinedButton(
              key: const Key('public_homepage_sign_in'),
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: const BorderSide(color: Color(0xFF51647D)),
                padding: const EdgeInsets.symmetric(
                  horizontal: 22,
                  vertical: 18,
                ),
              ),
              onPressed: () => Navigator.pushNamed(context, '/login'),
              child: const Text('Open your vault'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        const Text(
          kPublicHomepageCtaCaption,
          style: TextStyle(color: _muted, height: 1.6, fontSize: 14),
        ),
        const SizedBox(height: 10),
        const Text(
          'Start on the web, or use the iPhone, iPad and Android apps.',
          style: TextStyle(color: _muted, height: 1.5, fontSize: 14),
        ),
        const SizedBox(height: 18),
        const PlatformDownloadBadges(compact: true),
        const SizedBox(height: 8),
        TextButton(
          style: TextButton.styleFrom(foregroundColor: _blue),
          onPressed: () => _openPublicPage('/pricing/'),
          child: const Text('See storage and pricing'),
        ),
      ],
    );
  }
}

class PublicHomepageDemo extends StatelessWidget {
  const PublicHomepageDemo({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('public_homepage_demo'),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: const Color(0xFF142033),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: const Color(0xFF304A6B)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Image.asset(
            'assets/branding/public-vault-blue.png',
            width: double.infinity,
            height: 420,
            fit: BoxFit.contain,
            semanticLabel: 'SVaultAI chat interface and vault controls.',
          ),
          const Padding(
            padding: EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'A look inside your vault.',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  'See the SVaultAI chat interface.',
                  style: TextStyle(color: _muted, height: 1.5, fontSize: 14),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PublicPanel extends StatelessWidget {
  const _PublicPanel({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(24),
    decoration: BoxDecoration(
      color: const Color(0xFF141C29),
      border: Border.all(color: const Color(0xFF2A3C55)),
      borderRadius: BorderRadius.circular(20),
    ),
    child: child,
  );
}

class _PublicGrid extends StatelessWidget {
  const _PublicGrid({required this.children, this.columns = 2});
  final List<Widget> children;
  final int columns;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final count = constraints.maxWidth < 680 ? 1 : columns;
      final width = (constraints.maxWidth - 16 * (count - 1)) / count;
      return Wrap(
        spacing: 16,
        runSpacing: 16,
        children: [
          for (final child in children) SizedBox(width: width, child: child),
        ],
      );
    },
  );
}

class _PublicFeature extends StatelessWidget {
  const _PublicFeature({
    required this.icon,
    required this.title,
    required this.copy,
  });
  final IconData icon;
  final String title;
  final String copy;

  @override
  Widget build(BuildContext context) => _PublicPanel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: _blue, size: 28),
        const SizedBox(height: 16),
        Text(
          title,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 19,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 10),
        Text(copy, style: _body),
      ],
    ),
  );
}

class PublicHomepageDetails extends StatelessWidget {
  const PublicHomepageDetails({super.key});

  @override
  Widget build(BuildContext context) => Column(
    key: const Key('public_homepage_details'),
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      _heading(context, 'More of your digital life, in one place.'),
      const SizedBox(height: 20),
      const _PublicGrid(
        children: [
          _PublicFeature(
            icon: Icons.folder_copy_outlined,
            title: 'Files, photos and memories',
            copy:
                'Keep important documents, private photos, videos, saved '
                'logins and personal memories organized in your vault.',
          ),
          _PublicFeature(
            icon: Icons.chat_bubble_outline,
            title: 'Find it with AI',
            copy:
                'Ask “where is my passport scan?” in everyday language. '
                'AI and document features may process content you authorize '
                'on servers and with service providers.',
          ),
          _PublicFeature(
            icon: Icons.account_balance_wallet_outlined,
            title: 'Digital Assets & Crypto',
            copy:
                'Supported non-custodial cryptocurrency, PAXG Digital Gold '
                'and Ethereum KAG Digital Silver, with balances, receive, '
                'send and history on supported networks. Wallet features '
                'require an eligible paid storage plan.',
          ),
          _PublicFeature(
            icon: Icons.people_outline,
            title: 'Beneficiary access',
            copy:
                'Prepare encrypted vault credentials for a trusted person, '
                'with requests, approval, decline and a waiting period. '
                'Plan access before it is needed.',
          ),
        ],
      ),
      const SizedBox(height: 32),
      _PublicPanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _heading(context, 'Find it now. Prepare access for later.'),
            const SizedBox(height: 12),
            const Text(
              'Save a passport scan and ask chat to find it before a trip. '
              'Separately, prepare vault credentials for a beneficiary '
              'who may need access in the future. One helps you find '
              'information today; the other helps you plan ahead.',
              style: _body,
            ),
          ],
        ),
      ),
      const SizedBox(height: 40),
      const PublicHomepageInheritance(),
      const SizedBox(height: 40),
      const PublicHomepagePricing(),
      const SizedBox(height: 12),
      Wrap(
        spacing: 10,
        runSpacing: 6,
        children: [
          TextButton(
            key: const Key('public_homepage_plan_details'),
            onPressed: () => _openPublicPage('/pricing/'),
            style: TextButton.styleFrom(foregroundColor: _blue),
            child: const Text('View storage pricing and plan details'),
          ),
          TextButton(
            onPressed: () => _openPublicPage('/features/digital-vault/'),
            style: TextButton.styleFrom(foregroundColor: _blue),
            child: const Text('Explore SVaultAI features'),
          ),
        ],
      ),
      const SizedBox(height: 32),
      _PublicPanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _heading(context, 'Understand how your information is used.'),
            const SizedBox(height: 14),
            const Text(
              'Protected files and records are encrypted while stored. '
              'Your vault name and PIN are required to open your account; '
              'keep them safe because support cannot recover them. '
              'AI and document features may process the content you '
              'authorize on servers and with service providers.',
              style: _body,
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                TextButton(
                  key: const Key('public_homepage_security_details'),
                  style: TextButton.styleFrom(foregroundColor: _blue),
                  onPressed: () =>
                      _openPublicPage('/features/zero-knowledge-security/'),
                  child: const Text('How encryption and AI work'),
                ),
                TextButton(
                  style: TextButton.styleFrom(foregroundColor: _blue),
                  onPressed: () => _openPublicPage('/privacy/'),
                  child: const Text('Privacy policy'),
                ),
              ],
            ),
          ],
        ),
      ),
      const SizedBox(height: 28),
    ],
  );
}

// USD examples match the app’s storage examples. Store checkout supplies the
// actual localized price and current availability; this page starts no purchase.
const _publicStorageExamples = [
  ('50 GB', r'$14.99'),
  ('100 GB', r'$19.99'),
  ('150 GB', r'$24.99'),
  ('500 GB', r'$49.99'),
];

class PublicHomepagePricing extends StatelessWidget {
  const PublicHomepagePricing({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('public_homepage_pricing'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _heading(context, 'Start free. Add storage when you need it.'),
          const SizedBox(height: 18),
          const _PublicFeature(
            icon: Icons.cloud_outlined,
            title: r'Free base vault · 1 GB · $0',
            copy:
                'No subscription required. Start with files, photos, logins and '
                'memories. Create a vault with a vault name and PIN; no email '
                'address or phone number is required.',
          ),
          const SizedBox(height: 16),
          _PublicPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Optional paid storage · USD monthly examples',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 19,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 16),
                for (final plan in _publicStorageExamples)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(
                      children: [
                        Expanded(child: Text(plan.$1, style: _body)),
                        Flexible(
                          child: Text(
                            '${plan.$2}/month',
                            textAlign: TextAlign.end,
                            style: _body.copyWith(color: Colors.white),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 12),
                const Text(
                  'Examples are for comparison. Current plans, prices, taxes and '
                  'availability vary by store and region. Choose a plan in the '
                  'mobile app and review its localized checkout price before '
                  'confirming. No purchase is required to start free.',
                  style: _body,
                ),
                const SizedBox(height: 10),
                const Text(
                  'Cryptocurrency wallet features require an eligible paid '
                  'storage plan. Supported networks, issuer terms and country '
                  'restrictions also apply.',
                  style: _body,
                ),
              ],
            ),
          ),
        ],
      );
}

class PublicHomepageInheritance extends StatelessWidget {
  const PublicHomepageInheritance({super.key});

  @override
  Widget build(BuildContext context) => Column(
    key: const Key('public_homepage_inheritance'),
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      _heading(context, kPublicHomepageInheritanceHeading),
      const SizedBox(height: 18),
      const _PublicGrid(
        columns: 3,
        children: [
          _PublicFeature(
            icon: Icons.person_add_alt_outlined,
            title: '1. Pair a beneficiary',
            copy:
                'Connect with someone you trust through the supported '
                'beneficiary pairing workflow.',
          ),
          _PublicFeature(
            icon: Icons.key_outlined,
            title: '2. Prepare credentials',
            copy:
                'Prepare an encrypted package containing the vault name '
                'and PIN you choose to share.',
          ),
          _PublicFeature(
            icon: Icons.fact_check_outlined,
            title: '3. Review a request',
            copy:
                'An in-app notification tells the owner about a request. '
                'Approve to release access or decline to stop the request.',
          ),
        ],
      ),
      const SizedBox(height: 18),
      const Text(kPublicHomepageInheritance, style: _body),
      const SizedBox(height: 10),
      const Text(
        'Open Notifications and Inheritance in the app to review requests. '
        'The owner can choose Approve now or Reject request. The beneficiary '
        'can use Cancel request while a request is pending. Rejection or '
        'cancellation stops that request’s '
        'countdown, and the beneficiary may request again later. '
        'Check in the app rather than relying on email or SMS alerts.',
        style: _body,
      ),
      const SizedBox(height: 10),
      const Text(
        'For example, a paired family member can reveal the prepared '
        'vault name and PIN after authorized release, then use them to '
        'sign in. These credentials can unlock the associated vault; '
        'this is not a permission to share only selected files.',
        style: _body,
      ),
      const SizedBox(height: 10),
      const Text(
        'Digital access planning does not replace a legal will or '
        'transfer legal ownership of accounts, property or crypto.',
        style: TextStyle(color: _muted, fontSize: 14, height: 1.5),
      ),
      const SizedBox(height: 8),
      TextButton(
        style: TextButton.styleFrom(foregroundColor: _blue),
        onPressed: () => _openPublicPage('/features/digital-inheritance/'),
        child: const Text('Read the complete beneficiary access flow'),
      ),
    ],
  );
}

class PublicHomepageFinalCta extends StatelessWidget {
  const PublicHomepageFinalCta({super.key});

  @override
  Widget build(BuildContext context) => _PublicPanel(
    child: Column(
      key: const Key('public_homepage_final_cta'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _heading(context, kPublicHomepageCtaHeading),
        const SizedBox(height: 14),
        const Text(
          'Choose a vault name and PIN to get started on the web.',
          style: _body,
        ),
        const SizedBox(height: 20),
        FilledButton(
          key: const Key('public_homepage_create_vault_button'),
          style: FilledButton.styleFrom(
            backgroundColor: _blue,
            foregroundColor: const Color(0xFF091B30),
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 18),
          ),
          onPressed: () => Navigator.pushNamed(context, '/signup'),
          child: const Text(kPublicHomepageCtaButton),
        ),
        const SizedBox(height: 14),
        const Text(
          kPublicHomepageCtaCaption,
          style: TextStyle(color: _muted, fontSize: 14, height: 1.5),
        ),
      ],
    ),
  );
}
