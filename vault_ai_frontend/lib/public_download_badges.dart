import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

const String kGooglePlayListingUrl =
    'https://play.google.com/store/apps/details?id=com.svaultai.app';
const String kGooglePlayBadgeUrl =
    'https://play.google.com/intl/en_us/badges/static/images/badges/'
    'en_badge_web_generic.png';
const String kConfiguredAppStoreUrl =
    String.fromEnvironment('APP_STORE_URL', defaultValue: '');
const String kConfiguredMacAppStoreUrl =
    String.fromEnvironment('MAC_APP_STORE_URL', defaultValue: '');

Future<void> _openExternal(String rawUrl) async {
  final uri = Uri.parse(rawUrl);
  await launchUrl(
    uri,
    mode: kIsWeb ? LaunchMode.platformDefault : LaunchMode.externalApplication,
    webOnlyWindowName: kIsWeb ? '_blank' : null,
  );
}

class PlatformDownloadBadges extends StatelessWidget {
  final bool compact;
  final String appStoreUrl;
  final String macAppStoreUrl;

  const PlatformDownloadBadges({
    super.key,
    this.compact = false,
    this.appStoreUrl = kConfiguredAppStoreUrl,
    this.macAppStoreUrl = kConfiguredMacAppStoreUrl,
  });

  @override
  Widget build(BuildContext context) {
    final height = compact ? 46.0 : 54.0;
    final configuredAppleUrl = appStoreUrl.trim();
    final configuredMacUrl = macAppStoreUrl.trim();
    final hasAppleUrl = configuredAppleUrl.isNotEmpty;
    final hasDedicatedMacUrl =
        configuredMacUrl.isNotEmpty && configuredMacUrl != configuredAppleUrl;
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Semantics(
          link: true,
          label: 'Get SVaultAI on Google Play. Opens in a new tab.',
          child: Tooltip(
            message: 'Get SVaultAI on Google Play',
            child: InkWell(
              key: const Key('google_play_download_badge'),
              onTap: () => _openExternal(kGooglePlayListingUrl),
              borderRadius: BorderRadius.circular(8),
              child: Image.network(
                kGooglePlayBadgeUrl,
                width: height * 2.584,
                height: height,
                fit: BoxFit.contain,
                webHtmlElementStrategy: WebHtmlElementStrategy.fallback,
                excludeFromSemantics: true,
                errorBuilder: (_, __, ___) => _BadgeFallback(
                  height: height,
                  label: 'Get it on Google Play',
                  icon: Icons.shop_2_outlined,
                ),
              ),
            ),
          ),
        ),
        if (!hasAppleUrl)
          Semantics(
            key: const Key('apple_app_store_badge'),
            label: 'SVaultAI for Apple platforms. Store link not configured.',
            enabled: false,
            excludeSemantics: true,
            child: Tooltip(
              message: 'Apple App Store',
              child: _AppleStoreBadge(height: height),
            ),
          )
        else
          Semantics(
            key: const Key('apple_app_store_badge'),
            link: true,
            label: 'Download SVaultAI on the App Store. Opens in a new tab.',
            excludeSemantics: true,
            child: Tooltip(
              message: 'Download SVaultAI on the App Store',
              child: InkWell(
                key: const Key('apple_app_store_download_link'),
                onTap: () => _openExternal(configuredAppleUrl),
                borderRadius: BorderRadius.circular(8),
                child: _AppleStoreBadge(height: height),
              ),
            ),
          ),
        if (hasDedicatedMacUrl)
          Semantics(
            link: true,
            label: 'Download SVaultAI for Mac. Opens in a new tab.',
            child: Tooltip(
              message: 'Download SVaultAI for Mac',
              child: InkWell(
                key: const Key('mac_app_store_download_action'),
                onTap: () => _openExternal(configuredMacUrl),
                borderRadius: BorderRadius.circular(8),
                child: _BadgeFallback(
                  height: height,
                  label: 'Download for Mac',
                  icon: Icons.laptop_mac_outlined,
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _AppleStoreBadge extends StatelessWidget {
  final double height;

  const _AppleStoreBadge({required this.height});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: height * 3.012,
      height: height,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white24),
        ),
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: height * 0.2),
          child: Row(
            children: [
              Icon(Icons.apple, size: height * 0.54, color: Colors.white),
              SizedBox(width: height * 0.12),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Download on the',
                      maxLines: 1,
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: height * 0.17,
                        height: 1,
                      ),
                    ),
                    SizedBox(height: height * 0.04),
                    Text(
                      'App Store',
                      maxLines: 1,
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: height * 0.34,
                        height: 1,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _BadgeFallback extends StatelessWidget {
  final double height;
  final String label;
  final IconData icon;

  const _BadgeFallback({
    required this.height,
    required this.label,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white24),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 22, color: Colors.white),
          const SizedBox(width: 9),
          Flexible(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                label,
                maxLines: 1,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class PublicMobileAppsSection extends StatelessWidget {
  const PublicMobileAppsSection({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow = constraints.maxWidth < 720;
        final copy = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Take your private vault with you.',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
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
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [copy, const SizedBox(height: 24), art],
                )
              : Row(
                  children: [
                    Expanded(flex: 3, child: copy),
                    const SizedBox(width: 40),
                    Expanded(flex: 2, child: art),
                  ],
                ),
        );
      },
    );
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
          Wrap(
            spacing: 6,
            children: [
              TextButton(
                onPressed: () => Navigator.pushNamed(context, '/privacy'),
                child: const Text('Privacy'),
              ),
              TextButton(
                onPressed: () =>
                    Navigator.pushNamed(context, '/help-and-faq-public'),
                child: const Text('Help Center'),
              ),
            ],
          ),
          const PlatformDownloadBadges(compact: true),
        ],
      ),
    );
  }
}
