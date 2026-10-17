import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../services/web_boot_handoff.dart';
import 'theme.dart';

/// Paints before reading local credentials or checking a remembered session.
/// The actual application is not mounted until initialization succeeds, so a
/// cached identity can never bypass the existing authentication/route guards.
class AppStartupGate extends StatefulWidget {
  final Future<Widget> Function() initialize;
  final VoidCallback? onAppRendered;

  const AppStartupGate({
    super.key,
    required this.initialize,
    this.onAppRendered,
  });

  @override
  State<AppStartupGate> createState() => _AppStartupGateState();
}

class _AppStartupGateState extends State<AppStartupGate> {
  late Future<Widget> _initialization;

  @override
  void initState() {
    super.initState();
    _initialization = Future<Widget>.sync(widget.initialize);
  }

  void _retry() {
    setState(() {
      _initialization = Future<Widget>.sync(widget.initialize);
    });
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Widget>(
      future: _initialization,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.done &&
            snapshot.hasData) {
          return _InitializedAppHandoff(
            onRendered: widget.onAppRendered ?? notifyWebAppRendered,
            child: snapshot.requireData,
          );
        }
        // Do not render exception text: local-storage/platform failures may
        // contain implementation details that do not belong on an auth page.
        final failed = snapshot.connectionState == ConnectionState.done &&
            snapshot.hasError;
        return MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: VaultTheme.dark(),
          // A bootstrap Navigator would consume deep links or report "/" to
          // the web engine before the real app restores its guarded routes.
          // This builder-only shell must not own a navigation stack.
          builder: (context, child) => Scaffold(
            body: SafeArea(
              child: Center(
                child: SingleChildScrollView(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Image.asset(
                          'assets/branding/vaultai-icon-1024.png',
                          width: 192,
                          height: 192,
                          fit: BoxFit.contain,
                          semanticLabel: 'SVaultAI logo',
                        ),
                        const SizedBox(height: 20),
                        Semantics(
                          liveRegion: true,
                          child: Text(
                            failed
                                ? 'SVaultAI could not start. Please try again.'
                                : kIsWeb
                                    ? 'SVaultAI'
                                    : 'Opening SVaultAI securely…',
                            textAlign: TextAlign.center,
                          ),
                        ),
                        if (failed) ...[
                          const SizedBox(height: 20),
                          FilledButton(
                            onPressed: _retry,
                            child: const Text('Try again'),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// The engine's first frame may still be the pending initialization screen.
/// Keep the HTML landing/brand until initialization succeeded and the real
/// app rendered. Its root/deep-link guards use the first app post-frame pass;
/// the next rendered frame contains their selected screen. No timed wait or
/// authentication decision is added here.
class _InitializedAppHandoff extends StatefulWidget {
  const _InitializedAppHandoff({required this.child, required this.onRendered});

  final Widget child;
  final VoidCallback onRendered;

  @override
  State<_InitializedAppHandoff> createState() => _InitializedAppHandoffState();
}

class _InitializedAppHandoffState extends State<_InitializedAppHandoff> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.onRendered();
      });
      WidgetsBinding.instance.scheduleFrame();
    });
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
