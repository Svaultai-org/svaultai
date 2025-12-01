import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:descope/descope.dart';

// NEW: backend client import (make sure api_client.dart exists)
import 'package:vault_ai_frontend/api_client.dart';

/// ====== INSERT YOUR DESCOPE PROJECT ID ======
const descopeProjectId = 'P34z7YsFexzMXG48tZR3yjUxAjKb';
/// ============================================

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Descope
  Descope.setup(descopeProjectId);
  // Load any saved session
  await Descope.sessionManager.loadSession();

  runApp(const VaultaiApp());
}

/* ======================================================================
  App State
====================================================================== */
class AppState extends ChangeNotifier {
  bool authed = false;
  bool pinSet = false;
  bool unlocked = false;
  bool videoVerified = false;
  String? email; // NEW

  Future<void> hydrate() async {
    final sp = await SharedPreferences.getInstance();
    pinSet = sp.getString('pin_hash') != null;
    videoVerified = sp.getBool('video_verified') ?? false;
    authed = Descope.sessionManager.session?.sessionJwt != null;
    email ??= sp.getString('last_email');
    notifyListeners();
  }

  Future<void> setEmail(String value) async {
    email = value;
    final sp = await SharedPreferences.getInstance();
    await sp.setString('last_email', value);
    notifyListeners();
  }

  Future<void> markAuthed() async {
    authed = true;
    await hydrate();
  }

  Future<void> signOutEverywhere() async {
    try {
      Descope.sessionManager.clearSession();
    } catch (_) {}
    final sp = await SharedPreferences.getInstance();
    await sp.remove('pin_hash');
    await sp.remove('video_verified');
    await sp.remove('last_email');
    authed = false;
    pinSet = false;
    unlocked = false;
    videoVerified = false;
    email = null;
    notifyListeners();
  }

  // Demo hash; replace with Argon2id later.
  String _demoHash(String pin) => pin.split('').reversed.join();

  Future<void> setPin(String pin) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString('pin_hash', _demoHash(pin));
    pinSet = true;
    notifyListeners();
  }

  Future<bool> verifyPin(String pin) async {
    final sp = await SharedPreferences.getInstance();
    final ok = sp.getString('pin_hash') == _demoHash(pin);
    unlocked = ok;
    notifyListeners();
    return ok;
  }

  Future<void> setVideoVerified() async {
    final sp = await SharedPreferences.getInstance();
    await sp.setBool('video_verified', true);
    videoVerified = true;
    notifyListeners();
  }
}

/* ======================================================================
  App + Routes
====================================================================== */
class VaultaiApp extends StatelessWidget {
  const VaultaiApp({super.key});
  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => AppState()..hydrate(),
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'Vaultai',
        theme: ThemeData(
          useMaterial3: true,
          colorSchemeSeed: Colors.teal,
          brightness: Brightness.dark,
          scaffoldBackgroundColor: const Color(0xFF0F1115),
          textTheme: const TextTheme(
            bodyMedium: TextStyle(fontSize: 15, height: 1.45),
          ),
        ),
        routes: {
          '/': (_) => const LandingPage(),
          '/auth': (_) => const AuthEmailOtpPage(),
          '/pin': (_) => const PinGatePage(),
          '/video': (_) => const VideoVerifyPage(),
          '/chat': (_) => const ChatDashboardPage(),
          '/recover': (_) => const RecoveryFlowPage(),
        },
        initialRoute: '/',
      ),
    );
  }
}

/* ======================================================================
  Top Navigation
====================================================================== */
class TopNavBar extends StatelessWidget implements PreferredSizeWidget {
  final bool showActions;
  const TopNavBar({super.key, this.showActions = true});
  @override
  Size get preferredSize => const Size.fromHeight(56);

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final authed = app.authed;
    final email = app.email;

    return AppBar(
      elevation: 0,
      backgroundColor: Colors.black.withOpacity(0.2),
      titleSpacing: 12,
      title: Row(children: const [_Brand()]),
      actions: !showActions
          ? null
          : [
              if (!authed) ...[
                TextButton(
                    onPressed: () => Navigator.pushNamed(context, '/auth'),
                    child: const Text('Login')),
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilledButton(
                    onPressed: () => Navigator.pushNamed(context, '/auth'),
                    child: const Text('Sign up for free'),
                  ),
                ),
              ] else ...[
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: PopupMenuButton<String>(
                    tooltip: 'Account',
                    itemBuilder: (_) => [
                      if (email != null)
                        PopupMenuItem(enabled: false, child: Text(email)),
                      const PopupMenuDivider(),
                      const PopupMenuItem(
                          value: 'sign_out', child: Text('Sign out')),
                    ],
                    onSelected: (v) async {
                      if (v == 'sign_out') {
                        await context.read<AppState>().signOutEverywhere();
                        if (context.mounted) {
                          Navigator.pushNamedAndRemoveUntil(
                              context, '/', (_) => false);
                        }
                      }
                    },
                    child: Row(children: [
                      const Icon(Icons.account_circle, size: 22),
                      const SizedBox(width: 8),
                      Text(email ?? 'Account'),
                      const SizedBox(width: 4),
                      const Icon(Icons.keyboard_arrow_down),
                    ]),
                  ),
                ),
              ]
            ],
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Container(
        width: 28,
        height: 28,
        decoration: BoxDecoration(
          color: Colors.tealAccent.withOpacity(.15),
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Icon(Icons.shield, color: Colors.tealAccent, size: 18),
      ),
      const SizedBox(width: 10),
      const Text('Vaultai',
          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
    ]);
  }
}

/* ======================================================================
  Landing Page
====================================================================== */
class LandingPage extends StatelessWidget {
  const LandingPage({super.key});
  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    final isNarrow = w < 900;
    return Scaffold(
      appBar: const TopNavBar(),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: Padding(
            padding:
                const EdgeInsets.symmetric(horizontal: 18, vertical: 28),
            child: isNarrow
                ? const _LandingColumn()
                : const _LandingRow(),
          ),
        ),
      ),
    );
  }
}

class _LandingRow extends StatelessWidget {
  const _LandingRow();
  @override
  Widget build(BuildContext context) {
    return Row(children: const [
      Expanded(child: _HeroText()),
      SizedBox(width: 40),
      Expanded(child: _HeroCard()),
    ]);
  }
}

class _LandingColumn extends StatelessWidget {
  const _LandingColumn();
  @override
  Widget build(BuildContext context) {
    return Column(children: const [
      _HeroText(),
      SizedBox(height: 24),
      _HeroCard(),
    ]);
  }
}

class _HeroText extends StatelessWidget {
  const _HeroText();
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Private by design.\nSimple by default.',
            style: t.headlineMedium
                ?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 12),
        Text(
          'Vaultai stores your most sensitive information behind passwordless sign-in, a personal 4-digit PIN, and a one-time video consent check. '
          'Ask to save or retrieve logins, IDs, cards, photos, and notes—instantly.',
          style: t.bodyMedium?.copyWith(color: Colors.white70),
        ),
        const SizedBox(height: 20),
        Wrap(spacing: 10, runSpacing: 10, children: [
          FilledButton(
              onPressed: () => Navigator.pushNamed(context, '/auth'),
              child: const Text('Get started')),
          OutlinedButton(
              onPressed: () => Navigator.pushNamed(context, '/auth'),
              child: const Text('Login')),
        ]),
      ],
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard();
  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 10,
      shape:
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.lock_outline,
              size: 42, color: Colors.tealAccent),
          const SizedBox(height: 12),
          Text('How it works',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          const Text(
            'Email code → Create PIN → One-time video → Chat vault',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),
          FilledButton(
              onPressed: () =>
                  Navigator.pushNamed(context, '/auth'),
              child: const Text('Try the flow')),
        ]),
      ),
    );
  }
}

/* ======================================================================
  Auth: Email + One-Time Code (Descope)
====================================================================== */
class AuthEmailOtpPage extends StatefulWidget {
  const AuthEmailOtpPage({super.key});
  @override
  State<AuthEmailOtpPage> createState() => _AuthEmailOtpPageState();
}

class _AuthEmailOtpPageState extends State<AuthEmailOtpPage> {
  final emailCtrl = TextEditingController();
  final otpCtrl = TextEditingController();
  bool sent = false;
  String? err;

  Future<void> _afterAuth(
      AuthenticationResponse authResponse, String email) async {
    final session =
        DescopeSession.fromAuthenticationResponse(authResponse);
    Descope.sessionManager.manageSession(session);
    await context.read<AppState>().setEmail(email);
    await context.read<AppState>().markAuthed();
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, '/pin');
  }

  Future<void> sendEmailOtp() async {
    final email = emailCtrl.text.trim();
    if (!email.contains('@')) {
      setState(() => err = 'Enter a valid email');
      return;
    }
    try {
      await Descope.otp.signUp(
          method: DeliveryMethod.email, loginId: email);
      setState(() {
        sent = true;
        err = null;
      });
    } on DescopeException {
      try {
        await Descope.otp.signIn(
            method: DeliveryMethod.email, loginId: email);
        setState(() {
          sent = true;
          err = null;
        });
      } catch (e) {
        setState(() => err = 'Failed to send code. $e');
      }
    } catch (e) {
      setState(() => err = 'Failed to send code. $e');
    }
  }

  Future<void> verifyEmailOtp() async {
    final email = emailCtrl.text.trim();
    final code = otpCtrl.text.trim();
    if (code.length < 4) {
      setState(() => err = 'Enter the 6-digit code');
      return;
    }
    try {
      final authResponse = await Descope.otp.verify(
        method: DeliveryMethod.email,
        loginId: email,
        code: code,
      );
      await _afterAuth(authResponse, email);
    } catch (e) {
      setState(() => err = 'Code invalid. $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final maxW = MediaQuery.of(context).size.width < 480
        ? MediaQuery.of(context).size.width - 24
        : 420.0;
    return Scaffold(
      appBar: const TopNavBar(),
      body: Center(
        child: SizedBox(
          width: maxW,
          child: Card(
            elevation: 8,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16)),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Text('Sign in with your email',
                    style: TextStyle(
                        fontSize: 22, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                TextField(
                    controller: emailCtrl,
                    decoration:
                        const InputDecoration(labelText: 'Email')),
                const SizedBox(height: 8),
                if (!sent)
                  SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                          onPressed: sendEmailOtp,
                          child: const Text('Send code')))
                else ...[
                  TextField(
                      controller: otpCtrl,
                      decoration: const InputDecoration(
                          labelText: 'Enter 6-digit code')),
                  const SizedBox(height: 8),
                  SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                          onPressed: verifyEmailOtp,
                          child: const Text('Continue'))),
                  const SizedBox(height: 6),
                  TextButton(
                      onPressed: () =>
                          Navigator.pushNamed(context, '/recover'),
                      child:
                          const Text('Lost access to your email?')),
                ],
                if (err != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(err!,
                        style: const TextStyle(
                            color: Colors.redAccent)),
                  ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/* ======================================================================
  PIN Gate
====================================================================== */
class PinGatePage extends StatefulWidget {
  const PinGatePage({super.key});
  @override
  State<PinGatePage> createState() => _PinGatePageState();
}

class _PinGatePageState extends State<PinGatePage> {
  final boxes = List.generate(4, (_) => TextEditingController());
  String? err;
  bool creating = false;

  @override
  void initState() {
    super.initState();
    _decide();
  }

  Future<void> _decide() async {
    final sp = await SharedPreferences.getInstance();
    setState(() => creating = sp.getString('pin_hash') == null);
  }

  String get _pin => boxes.map((c) => c.text.trim()).join();

  Future<void> _submit() async {
    if (_pin.length != 4 || int.tryParse(_pin) == null) {
      setState(() => err = 'Enter exactly 4 digits');
      return;
    }
    final app = context.read<AppState>();
    if (creating) {
      await app.setPin(_pin);
      if (!mounted) return;
      Navigator.pushReplacementNamed(context, '/video');
    } else {
      final ok = await app.verifyPin(_pin);
      if (!mounted) return;
      if (!ok) {
        setState(() => err = 'Incorrect PIN');
        return;
      }
      final sp = await SharedPreferences.getInstance();
      final verified = sp.getBool('video_verified') ?? false;
      Navigator.pushReplacementNamed(
          context, verified ? '/chat' : '/video');
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    return Scaffold(
      appBar: const TopNavBar(showActions: false),
      body: Center(
        child: SizedBox(
          width: w < 420 ? w - 24 : 360,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text(
                    creating
                        ? 'Create 4-digit PIN'
                        : 'Enter 4-digit PIN',
                    style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold)),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment:
                      MainAxisAlignment.spaceEvenly,
                  children: List.generate(
                    4,
                    (i) => SizedBox(
                      width: 60,
                      child: TextField(
                        controller: boxes[i],
                        maxLength: 1,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        obscureText: true,
                        decoration: const InputDecoration(
                            counterText: ''),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                if (err != null)
                  Text(err!,
                      style: const TextStyle(
                          color: Colors.redAccent)),
                const SizedBox(height: 8),
                SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                        onPressed: _submit,
                        child: Text(creating
                            ? 'Create PIN'
                            : 'Unlock'))),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/* ======================================================================
  One-time Video Consent (stub)
====================================================================== */
class VideoVerifyPage extends StatefulWidget {
  const VideoVerifyPage({super.key});
  @override
  State<VideoVerifyPage> createState() => _VideoVerifyPageState();
}

class _VideoVerifyPageState extends State<VideoVerifyPage> {
  bool recorded = false;
  bool verifying = false;

  Future<void> _simulateVerify() async {
    setState(() => verifying = true);
    await Future.delayed(const Duration(seconds: 2));
    await context.read<AppState>().setVideoVerified();
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, '/chat');
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final dateText =
        "${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}";
    final maxW = MediaQuery.of(context).size.width < 520
        ? MediaQuery.of(context).size.width - 24
        : 500.0;

    return Scaffold(
      appBar: const TopNavBar(showActions: false),
      body: Center(
        child: SizedBox(
          width: maxW,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment:
                      CrossAxisAlignment.start,
                  children: [
                    const Text('Identity verification',
                        style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold)),
                    const SizedBox(height: 10),
                    const Text('Record a short video stating:'),
                    const SizedBox(height: 6),
                    const Text(
                        '• Your full name\n'
                        '• Your date of birth\n'
                        '• Today’s date\n'
                        '• “I give Vaultai consent to securely store my information.”',
                        style: TextStyle(color: Colors.white70)),
                    const SizedBox(height: 12),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.04),
                          borderRadius:
                              BorderRadius.circular(10)),
                      child: Text('Today: $dateText',
                          style: const TextStyle(
                              color: Colors.white70)),
                    ),
                    const SizedBox(height: 14),
                    FilledButton.icon(
                      onPressed: () =>
                          setState(() => recorded = true),
                      icon: const Icon(Icons.videocam),
                      label: const Text('Record (demo)'),
                    ),
                    const SizedBox(height: 10),
                    if (recorded)
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                            onPressed:
                                verifying ? null : _simulateVerify,
                            child: Text(verifying
                                ? 'Verifying…'
                                : 'Submit & verify')),
                      ),
                  ]),
            ),
          ),
        ),
      ),
    );
  }
}

/* ======================================================================
  Recovery (lost email) – stub
====================================================================== */
class RecoveryFlowPage extends StatefulWidget {
  const RecoveryFlowPage({super.key});
  @override
  State<RecoveryFlowPage> createState() => _RecoveryFlowPageState();
}

class _RecoveryFlowPageState extends State<RecoveryFlowPage> {
  bool videoOk = false;
  final newEmailCtrl = TextEditingController();
  String? err, info;
  bool busy = false;

  Future<void> _simulateVideoCheck() async {
    setState(() => busy = true);
    await Future.delayed(const Duration(seconds: 2));
    setState(() {
      busy = false;
      videoOk = true;
      info = "Identity verified. Enter your new email.";
    });
  }

  Future<void> _submitNewEmail() async {
    final email = newEmailCtrl.text.trim();
    if (!email.contains('@')) {
      setState(() => err = "Enter a valid email");
      return;
    }
    try {
      setState(() => busy = true);
      setState(() =>
          info = "We’ll update your email to $email after admin approval (stub).");
    } catch (e) {
      setState(() => err = "Could not update email: $e");
    } finally {
      setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    final maxW =
        w < 500 ? w - 24 : 460.0;

    return Scaffold(
      appBar: const TopNavBar(showActions: false),
      body: Center(
        child: SizedBox(
          width: maxW,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment:
                      CrossAxisAlignment.start,
                  children: [
                    const Text("Recover your account",
                        style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    if (!videoOk) ...[
                      const Text(
                          "Record a short video stating your full name, date of birth, today’s date, and consent."),
                      const SizedBox(height: 12),
                      FilledButton(
                          onPressed:
                              busy ? null : _simulateVideoCheck,
                          child: Text(busy
                              ? "Checking…"
                              : "Record & Verify (demo)")),
                    ] else ...[
                      const SizedBox(height: 6),
                      TextField(
                          controller: newEmailCtrl,
                          decoration: const InputDecoration(
                              labelText: "New email address")),
                      const SizedBox(height: 8),
                      FilledButton(
                          onPressed:
                              busy ? null : _submitNewEmail,
                          child: Text(busy
                              ? "Submitting…"
                              : "Change email")),
                    ],
                    if (info != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(info!,
                            style: const TextStyle(
                                color: Colors.tealAccent)),
                      ),
                    if (err != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(err!,
                            style: const TextStyle(
                                color: Colors.redAccent)),
                      ),
                  ]),
            ),
          ),
        ),
      ),
    );
  }
}

/* ======================================================================
  Chat Dashboard (now connected to backend AI)
====================================================================== */
class ChatDashboardPage extends StatefulWidget {
  const ChatDashboardPage({super.key});
  @override
  State<ChatDashboardPage> createState() =>
      _ChatDashboardPageState();
}

class _ChatDashboardPageState extends State<ChatDashboardPage> {
  final input = TextEditingController();
  final List<_Msg> msgs = const [
    _Msg(
      'assistant',
      'You’re verified. I am Vaultai.\n'
      'Tell me what you want to save or ask about your logins.\n'
      'Examples:\n'
      '• "Save this: user=umaarta21 pass=tenta32 for Facebook"\n'
      '• "What is my Facebook login?"\n'
      '• "Show my logins table."',
    ),
  ].toList();

  void _send() async {
    final text = input.text.trim();
    if (text.isEmpty) return;

    // User message
    setState(() => msgs.add(_Msg('user', text)));
    input.clear();

    final app = context.read<AppState>();
    final userId = app.email ?? 'anonymous';

    // Placeholder assistant message for streaming
    setState(() => msgs.add(const _Msg('assistant', '')));
    final int assistantIndex = msgs.length - 1;
    String buffer = '';

    final client = VaultAIClient(baseUrl: 'http://127.0.0.1:8000');

    final stream = client.chatStream(
      userId: userId,
      message: text,
      unlocked: app.unlocked,
      videoVerified: app.videoVerified,
    );

    stream.listen((chunk) {
      setState(() {
        buffer += chunk;
        msgs[assistantIndex] = _Msg('assistant', buffer);
      });
    }, onError: (err) {
      setState(() {
        msgs[assistantIndex] = _Msg(
            'assistant', 'Error talking to Vaultai backend: $err');
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;

    final sidebar = Container(
      width: w < 860 ? 0 : 260,
      color: Colors.black.withOpacity(0.12),
      child: w < 860
          ? null
          : Column(children: [
              const SizedBox(height: 16),
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12),
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                      onPressed: () {},
                      icon: const Icon(Icons.add),
                      label: const Text('New chat')),
                ),
              ),
              const Spacer(),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.logout),
                title: const Text('Sign out'),
                onTap: () async {
                  await context
                      .read<AppState>()
                      .signOutEverywhere();
                  if (!mounted) return;
                  Navigator.pushNamedAndRemoveUntil(
                      context, '/', (_) => false);
                },
              ),
              const SizedBox(height: 8),
            ]),
    );

    return Scaffold(
      appBar: const TopNavBar(showActions: false),
      body: Row(children: [
        sidebar,
        Expanded(
          child: Column(children: [
            Container(
              height: 52,
              alignment: Alignment.centerLeft,
              padding:
                  const EdgeInsets.symmetric(horizontal: 16),
              child: const Text('Chat',
                  style: TextStyle(fontWeight: FontWeight.w600)),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: msgs.length,
                itemBuilder: (_, i) => _Bubble(msg: msgs[i]),
              ),
            ),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.all(12.0),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: input,
                    decoration: const InputDecoration(
                        hintText: 'Message Vaultai…'),
                    onSubmitted: (_) => _send(),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                    onPressed: _send,
                    child: const Text('Send')),
              ]),
            ),
          ]),
        ),
      ]),
    );
  }
}

class _Msg {
  final String role;
  final String text;
  const _Msg(this.role, this.text);
}

class _Bubble extends StatelessWidget {
  final _Msg msg;
  const _Bubble({required this.msg});
  @override
  Widget build(BuildContext context) {
    final isUser = msg.role == 'user';
    return Align(
      alignment:
          isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.symmetric(
            vertical: 10, horizontal: 14),
        decoration: BoxDecoration(
          color: isUser
              ? Colors.teal.shade700
              : Colors.blueGrey.shade800,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(msg.text),
      ),
    );
  }
}
