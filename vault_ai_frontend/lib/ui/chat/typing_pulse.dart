

import 'package:flutter/material.dart';
import '../motion.dart';
import '../tokens.dart';

class TypingPulse extends StatelessWidget {
  final String? label;

  const TypingPulse({super.key, this.label});

  @override
  Widget build(BuildContext context) {
    
    
    return Semantics(
      liveRegion: true,
      label: label ?? 'Svaultai is thinking...',
      child: Padding(
      padding: const EdgeInsets.only(
        left:  VaultSpacing.xs,
        right: VaultSpacing.xs,
        top:   VaultSpacing.xs,
        bottom: VaultSpacing.xs,
      ),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: VaultSpacing.md + 2,
            vertical: VaultSpacing.sm + 2,
          ),
          decoration: BoxDecoration(
            color: VaultColors.bubbleAssistant,
            borderRadius: BorderRadius.circular(VaultRadius.xl),
            border: Border.all(color: VaultColors.borderSubtle),
            boxShadow: VaultShadows.e1,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label ?? 'Svaultai is thinking...',
                style: VaultText.bodySm.copyWith(
                  color: VaultColors.textSecondary,
                  fontStyle: FontStyle.italic,
                ),
              ),
              const SizedBox(width: VaultSpacing.sm + 2),
              const PulseDot(phase: 0.00, size: 5),
              const SizedBox(width: 3),
              const PulseDot(phase: 0.20, size: 5),
              const SizedBox(width: 3),
              const PulseDot(phase: 0.40, size: 5),
            ],
          ),
        ),
      ),
    ),
    );
  }
}
