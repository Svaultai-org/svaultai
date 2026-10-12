import 'package:flutter/material.dart';

import 'theme.dart';

/// Paints before reading local credentials or checking a remembered session.
/// The actual application is not mounted until initialization succeeds, so a
/// cached identity can never bypass the existing authentication/route guards.
class AppStartupGate extends StatefulWidget {
  final Future<Widget> Function() initialize;

  const AppStartupGate({super.key, required this.initialize});

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
          return snapshot.requireData;
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
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.shield_outlined, size: 48),
                      const SizedBox(height: 20),
                      if (!failed) const CircularProgressIndicator(),
                      const SizedBox(height: 20),
                      Text(
                        failed
                            ? 'SVaultAI could not start. Please try again.'
                            : 'Opening SVaultAI…',
                        textAlign: TextAlign.center,
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
        );
      },
    );
  }
}
