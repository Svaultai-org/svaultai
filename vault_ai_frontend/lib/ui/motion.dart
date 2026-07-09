

import 'package:flutter/material.dart';
import 'tokens.dart';


class FadeSlideIn extends StatelessWidget {
  final Widget child;
  final Duration duration;
  final Duration delay;
  final double offset;
  final Curve curve;
  final bool animate;

  const FadeSlideIn({
    super.key,
    required this.child,
    this.duration = VaultMotion.emphasized,
    this.delay = Duration.zero,
    this.offset = 8,
    this.curve = VaultMotion.curveStandard,
    this.animate = true,
  });

  @override
  Widget build(BuildContext context) {
    if (!animate) return child;
    
    
    if (MediaQuery.of(context).disableAnimations) return child;
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: 0, end: 1),
      duration: duration,
      curve: curve,
      builder: (context, t, c) {
        return Opacity(
          opacity: t.clamp(0.0, 1.0),
          child: Transform.translate(
            offset: Offset(0, (1 - t) * offset),
            child: c,
          ),
        );
      },
      child: child,
    );
  }
}


class PulseDot extends StatefulWidget {
  final double size;
  final Color color;
  final Duration period;
  final double phase; 

  const PulseDot({
    super.key,
    this.size = 6,
    this.color = VaultColors.textSecondary,
    this.period = const Duration(milliseconds: 1200),
    this.phase = 0,
  });

  @override
  State<PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<PulseDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: widget.period)
      ..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    
    if (MediaQuery.of(context).disableAnimations) {
      return Container(
        width: widget.size,
        height: widget.size,
        decoration: BoxDecoration(
          color: widget.color.withValues(alpha: 0.85),
          shape: BoxShape.circle,
        ),
      );
    }
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) {
        final t = ((_ctrl.value + widget.phase) % 1.0);
        
        final eased = (1 - (t - 0.5).abs() * 2).clamp(0.0, 1.0);
        final opacity = 0.25 + eased * 0.75;
        final scale = 0.85 + eased * 0.15;
        return Transform.scale(
          scale: scale,
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: widget.color.withValues(alpha: opacity),
              shape: BoxShape.circle,
            ),
          ),
        );
      },
    );
  }
}


class BreatheScale extends StatefulWidget {
  final Widget child;
  final Duration period;
  final double from;
  final double to;

  const BreatheScale({
    super.key,
    required this.child,
    this.period = const Duration(milliseconds: 2400),
    this.from = 1.0,
    this.to = 1.05,
  });

  @override
  State<BreatheScale> createState() => _BreatheScaleState();
}

class _BreatheScaleState extends State<BreatheScale>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: widget.period)
      ..repeat(reverse: true);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    
    if (MediaQuery.of(context).disableAnimations) return widget.child;
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, c) {
        final t = Curves.easeInOutSine.transform(_ctrl.value);
        final scale = widget.from + (widget.to - widget.from) * t;
        return Transform.scale(scale: scale, child: c);
      },
      child: widget.child,
    );
  }
}
