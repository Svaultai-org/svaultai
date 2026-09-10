import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

const String kGooglePlayListingUrl =
    'https://play.google.com/store/apps/details?id=com.svaultai.app';
const String kAppStoreListingUrl =
    'https://apps.apple.com/us/app/svaultai/id6800601455';

Future<void> _openStore(String rawUrl) async {
  await launchUrl(
    Uri.parse(rawUrl),
    mode: kIsWeb ? LaunchMode.platformDefault : LaunchMode.externalApplication,
    webOnlyWindowName: kIsWeb ? '_blank' : null,
  );
}

class PlatformDownloadBadges extends StatelessWidget {
  final bool compact;

  const PlatformDownloadBadges({super.key, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final height = compact ? 46.0 : 54.0;
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _StoreBadge(
          key: const Key('google_play_download_badge'),
          height: height,
          label: 'Get it on\nGoogle Play',
          icon: Icons.shop_2_outlined,
          semanticsLabel: 'Get SVaultAI on Google Play. Opens in a new tab.',
          onTap: () => _openStore(kGooglePlayListingUrl),
        ),
        _StoreBadge(
          key: const Key('app_store_download_badge'),
          height: height,
          label: 'Download on the\nApp Store',
          icon: Icons.apple,
          semanticsLabel:
              'Download SVaultAI on the App Store. Opens in a new tab.',
          onTap: () => _openStore(kAppStoreListingUrl),
        ),
      ],
    );
  }
}

class _StoreBadge extends StatelessWidget {
  final double height;
  final String label;
  final IconData icon;
  final String semanticsLabel;
  final VoidCallback onTap;

  const _StoreBadge({
    super.key,
    required this.height,
    required this.label,
    required this.icon,
    required this.semanticsLabel,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      link: true,
      label: semanticsLabel,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          height: height,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: Colors.black,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.white30),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: height * .48, color: Colors.white),
              const SizedBox(width: 9),
              Text(
                label,
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w600,
                  fontSize: height * .24,
                  height: 1.05,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class PublicMobileAppsSection extends StatelessWidget {
  const PublicMobileAppsSection({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final narrow = constraints.maxWidth < 720;
      final copy = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Take your private vault with you.',
            style: Theme.of(context)
                .textTheme
                .headlineSmall
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 12),
          const Text(
            'Use SVaultAI across supported Android and Apple devices with '
            'the same zero-knowledge, user-controlled account.',
            style: TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 16,
              height: 1.55,
            ),
          ),
          const SizedBox(height: 20),
          const PlatformDownloadBadges(),
        ],
      );
      final art = Container(
        height: 190,
        decoration: BoxDecoration(
          color: const Color(0xFF181B20),
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: Colors.white10),
        ),
        child: const Center(
          child: Icon(
            Icons.phonelink_lock_outlined,
            size: 78,
            color: Color(0xFF10A37F),
          ),
        ),
      );
      return Container(
        key: const Key('public_mobile_apps_section'),
        padding: EdgeInsets.all(narrow ? 22 : 34),
        decoration: BoxDecoration(
          color: const Color(0xFF111318),
          borderRadius: BorderRadius.circular(26),
          border: Border.all(color: Colors.white10),
        ),
        child: narrow
            ? Column(children: [copy, const SizedBox(height: 24), art])
            : Row(children: [
                Expanded(flex: 3, child: copy),
                const SizedBox(width: 40),
                Expanded(flex: 2, child: art),
              ]),
      );
    });
  }
}

class PublicLandingFooter extends StatelessWidget {
  const PublicLandingFooter({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('public_landing_footer'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 28),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: Colors.white10)),
      ),
      child: Wrap(
        spacing: 20,
        runSpacing: 16,
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const Text(
            'SVaultAI — Private AI-Powered Digital Vault',
            style: TextStyle(color: Color(0xFFB4B4B4)),
          ),
          Wrap(spacing: 6, children: [
            TextButton(
              onPressed: () => Navigator.pushNamed(context, '/privacy'),
              child: const Text('Privacy'),
            ),
            TextButton(
              onPressed: () =>
                  Navigator.pushNamed(context, '/help-and-faq-public'),
              child: const Text('Help Center'),
            ),
          ]),
          const PlatformDownloadBadges(compact: true),
        ],
      ),
    );
  }
}
