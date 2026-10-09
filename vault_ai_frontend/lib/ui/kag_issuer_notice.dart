import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'crypto_wallet_engine_design.dart';

const kKagIssuerTermsUrl = 'https://kmslabs.money/kms-labs-tcs/';
const kKagEligibilityNote = 'KMS Labs eligibility and sanctions restrictions '
    'apply to holding, receiving and sending KAG. It is not available to every '
    'person or jurisdiction. Review the issuer terms before receiving or sending.';

/// Issuer eligibility, not a purchase, redemption or company-onboarding flow.
class KagIssuerNotice extends StatelessWidget {
  const KagIssuerNotice({super.key});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(kKagEligibilityNote,
              key: Key('kag_issuer_eligibility_note'),
              style: kWalletMutedStyle),
          TextButton.icon(
            key: const Key('kag_issuer_terms_link'),
            onPressed: () async {
              try {
                await launchUrl(Uri.parse(kKagIssuerTermsUrl),
                    mode: LaunchMode.externalApplication);
              } catch (_) {
                // The fixed public URL remains visible when no browser opens.
              }
            },
            icon: const Icon(Icons.open_in_new, size: 16),
            label: const Text('KMS Labs terms'),
          ),
          const SelectableText(kKagIssuerTermsUrl, style: kWalletMutedStyle),
          const SizedBox(height: 12),
        ],
      );
}
