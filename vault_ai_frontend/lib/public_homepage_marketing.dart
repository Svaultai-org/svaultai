import 'package:flutter/material.dart';

// Public marketing copy only. Access, billing and inheritance behavior remain
// owned by their existing routes and services.
const String kPublicHomepageHeadline =
    "SVaultAI — The Vault Your Family Can Actually Open";

const String kPublicHomepageOpening =
    "SVaultAI is an encrypted vault for the digital records that matter to you — logins, "
    "documents, photos, memories and supported asset records — with optional inheritance "
    "access planning built in. Pair a beneficiary with a code and prepare the vault "
    "credentials you want them to receive. A beneficiary can request access; you can "
    "approve or decline, or the prepared credentials can become available after the "
    "request's waiting period if you do not respond.";

const String kPublicHomepageInheritanceHeading =
    "Inheritance: digital access planning";

const String kPublicHomepageInheritance =
    "Pair a beneficiary with a code, then prepare an encrypted package containing the vault "
    "name and PIN you choose to share. A beneficiary must request access before the waiting "
    "period starts. Approve to make that package available; decline to stop that pending "
    "release. If you do not respond before the request's waiting period expires, your "
    "beneficiary can claim and reveal the prepared credentials. This is a digital access "
    "feature, not a legal will or a substitute for estate advice.";

const String kPublicHomepageCtaHeading =
    "Create your free vault. Help your family find what matters.";

const String kPublicHomepageCtaButton = "Create your free vault";

const String kPublicHomepageCtaCaption =
    "Free base vault · No email address or phone number required · Optional paid storage plans";

class PublicHomepageInheritance extends StatelessWidget {
  const PublicHomepageInheritance({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('public_homepage_inheritance'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 22),
        Text(
          kPublicHomepageInheritanceHeading,
          style: Theme.of(context)
              .textTheme
              .headlineSmall
              ?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 14),
        const Text(
          kPublicHomepageInheritance,
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 16, height: 1.6),
        ),
      ],
    );
  }
}

class PublicHomepageFinalCta extends StatelessWidget {
  const PublicHomepageFinalCta({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('public_homepage_final_cta'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          kPublicHomepageCtaHeading,
          style: Theme.of(context)
              .textTheme
              .headlineSmall
              ?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 14),
        FilledButton(
          key: const Key('public_homepage_create_vault_button'),
          onPressed: () => Navigator.pushNamed(context, '/signup'),
          child: const Text(kPublicHomepageCtaButton),
        ),
        const SizedBox(height: 14),
        const Text(
          kPublicHomepageCtaCaption,
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 16, height: 1.6),
        ),
      ],
    );
  }
}
