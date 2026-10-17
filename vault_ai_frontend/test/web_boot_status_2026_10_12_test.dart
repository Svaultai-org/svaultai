import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

String _html() => File('web/index.html').readAsStringSync();

String _script() => RegExp(
      r'<script id="svaultai-boot-script">([\s\S]*?)</script>',
    ).firstMatch(_html())!.group(1)!;

Map<String, dynamic> _run(String scenario) {
  // The actual checked-in JavaScript executes in Node's isolated VM with a
  // synthetic DOM, events and timers only. No browser, HTTP or vault storage.
  final code = '''
const vm = require('node:vm');
const events = Object.create(null);
const buttonEvents = Object.create(null);
let timer = null, delay = null, cleared = 0, removed = 0, previewRemoved = 0, recoveryRemoved = 0, reloads = 0;
const status = { remove() { removed++; } };
const preview = { remove() { previewRemoved++; } };
const message = { textContent: '', hidden: true };
const recovery = { hidden: true, remove() { recoveryRemoved++; } };
const retry = { hidden: true, addEventListener(k, fn) { buttonEvents[k] = fn; } };
const window = {
  setTimeout(fn, ms) { timer = fn; delay = ms; return 1; },
  clearTimeout(id) { if (id !== 1) throw new Error('unexpected timer'); cleared++; },
  addEventListener(k, fn) { events[k] = fn; },
  location: { reload() { reloads++; } }
};
const document = { getElementById(id) {
  return { 'svaultai-boot-status': status, 'svaultai-boot-message': message, 'svaultai-boot-retry': retry, 'seo-content': preview, 'svaultai-boot-recovery': recovery }[id];
} };
vm.runInNewContext(${jsonEncode(_script())}, { window, document });
$scenario
console.log(JSON.stringify({text: message.textContent, messageHidden: message.hidden, hidden: retry.hidden, delay, cleared, removed, previewRemoved, recoveryRemoved, recoveryHidden: recovery.hidden, reloads}));
''';
  final result = Process.runSync('node', ['-e', code]);
  expect(result.exitCode, 0, reason: 'Synthetic boot-script fixture must run');
  expect(result.stderr, isEmpty);
  return Map<String, dynamic>.from(jsonDecode(result.stdout as String) as Map);
}

Map<String, dynamic> _runRoute(String path) {
  final script = RegExp(
    r'<script id="svaultai-route-visibility">([\s\S]*?)</script>',
  ).firstMatch(_html())!.group(1)!;
  final code = '''
const vm = require('node:vm');
const classes = [], metadata = [], removed = [];
const location = { pathname: ${jsonEncode(path)}, search: '?keep=example', hash: '#keep' };
const document = {
  documentElement: { classList: { add(value) { classes.push(value); } } },
  querySelector(selector) {
    if (selector === 'meta[name="robots"]') return { setAttribute(name, value) { metadata.push([name, value]); } };
    return { remove() { removed.push('canonical'); } };
  },
  querySelectorAll() { return [{ remove() { removed.push('schema'); } }]; }
};
vm.runInNewContext(${jsonEncode(script)}, { window: { location }, document });
console.log(JSON.stringify({classes, metadata, removed, location}));
''';
  final result = Process.runSync('node', ['-e', code]);
  expect(result.exitCode, 0);
  expect(result.stderr, isEmpty);
  return Map<String, dynamic>.from(jsonDecode(result.stdout as String) as Map);
}

Map<String, dynamic> _cleanReleaseMarker(String url) {
  final script = RegExp(
    r'<script id="svaultai-release-marker-cleanup">([\s\S]*?)</script>',
  ).firstMatch(_html())!.group(1)!;
  final code = '''
const vm = require('node:vm');
const calls = [], state = { route: 'synthetic-history-state' };
const window = {
  location: { href: ${jsonEncode(url)} },
  history: { state, replaceState(nextState, title, url) {
    calls.push({ sameState: nextState === state, title, url });
  } }
};
vm.runInNewContext(${jsonEncode(script)}, { URL, window, document: { title: 'SVaultAI' } });
console.log(JSON.stringify({calls}));
''';
  final result = Process.runSync('node', ['-e', code]);
  expect(result.exitCode, 0);
  expect(result.stderr, isEmpty);
  return Map<String, dynamic>.from(jsonDecode(result.stdout as String) as Map);
}

void main() {
  test('early cleanup removes only the migration marker and keeps deep links',
      () {
    for (final path in ['/', '/login', '/signup', '/chat', '/unlock']) {
      final input = Uri.parse('https://app.svaultai.com$path'
          '?keep=first&_vaultai_release=synthetic-release&keep=second&next=%2Fstorage'
          '#keep-fragment');
      final result = _cleanReleaseMarker(input.toString());
      final calls = result['calls'] as List;
      expect(calls, hasLength(1));
      final call = calls.single as Map;
      expect(call['sameState'], isTrue);
      expect(call['title'], 'SVaultAI');
      final actual = Uri.parse(call['url'] as String);
      expect(actual.path, input.path);
      expect(actual.fragment, input.fragment);
      expect(actual.queryParametersAll, {
        'keep': ['first', 'second'],
        'next': ['/storage'],
      });
    }
    expect(
        _cleanReleaseMarker(
            'https://app.svaultai.com/login?keep=value#same')['calls'],
        isEmpty);
  });

  test('only the public root gets readable content during engine startup', () {
    for (final path in ['/', '////']) {
      final result = _runRoute(path);
      expect(result['classes'], ['svaultai-public-startup']);
      expect(result['removed'], isEmpty);
      expect(result['metadata'], isEmpty);
    }
    for (final path in [
      '/login',
      '/login/',
      '/signup',
      '/unlock',
      '/chat',
      '/pin',
      '/recover',
      '/device-pending',
      '/unknown',
      '/help-and-faq-public',
    ]) {
      final result = _runRoute(path);
      expect(result['classes'], isEmpty, reason: path);
      expect(result['metadata'],
          path == '/help-and-faq-public' ? isEmpty : isNotEmpty);
      expect(result['location'], {
        'pathname': path,
        'search': '?keep=example',
        'hash': '#keep',
      });
    }
  });

  test('a private-data-free shell paints before Flutter and opaque bootstrap',
      () {
    final html = _html();
    expect(html.indexOf('id="svaultai-boot-status"'),
        lessThan(html.indexOf('src="flutter_bootstrap.js"')));
    expect(html.indexOf('id="svaultai-boot-script"'),
        lessThan(html.indexOf('src="assets/opaque/vaultai-opaque-init.js"')));
    expect(
        html, contains('role="status" aria-live="polite" aria-atomic="true"'));
    expect(html, isNot(contains('Opening SVaultAI securely')));
    expect(html, contains('id="svaultai-boot-name">SVaultAI</p>'));
    expect(html, contains('id="svaultai-boot-retry" type="button" hidden'));
    expect(html, contains('#seo-content { display: none; }'));
    expect(html, contains('.svaultai-public-startup #seo-content {'));
  });

  test('first paint reuses the unchanged shield with only the SVaultAI name',
      () {
    final html = _html();
    expect(html, contains('id="svaultai-boot-logo" src="icons/Icon-512.png"'));
    expect(html, contains('width="192" height="192" alt="SVaultAI"'));
    expect(
        html, contains('rel="preload" as="image" href="icons/Icon-512.png"'));
    expect(html, contains('id="svaultai-boot-name">SVaultAI</p>'));
    expect(html, isNot(contains('Opening SVaultAI securely')));
    expect(
      sha256
          .convert(File('web/icons/Icon-512.png').readAsBytesSync())
          .toString(),
      'fa682b3a841b4e31159b642544b7797ef38739496083adcf6e339884d5db48e0',
      reason: 'Reuse the existing brand asset without redesigning it',
    );
  });

  test('initial boot has no interim message or automatic reload', () {
    final result = _run('');
    expect(result['text'], isEmpty);
    expect(result['messageHidden'], isTrue);
    expect(result['hidden'], isTrue);
    expect(result['removed'], 0);
    expect(result['previewRemoved'], 0);
    expect(result['reloads'], 0);
    expect(result['delay'], 15000);
  });

  test('bounded wait offers a visible manual retry without an automatic reload',
      () {
    final result = _run('timer();');
    expect(result['text'], contains('taking longer than usual'));
    expect(result['messageHidden'], isFalse);
    expect(result['hidden'], isFalse);
    expect(result['removed'], 0);
    expect(result['reloads'], 0);
  });

  test('the engine first frame never retires the shell before initialization',
      () {
    final result = _run(
        "if (events['flutter-first-frame']) events['flutter-first-frame']();");
    expect(result['removed'], 0);
    expect(result['previewRemoved'], 0);
    expect(result['recoveryRemoved'], 0);
    expect(result['cleared'], 0);
  });

  test('the designed public landing is complete before any app scripts load',
      () {
    final html = _html();
    final start = html.indexOf('<main id="seo-content"');
    final end = html.indexOf('</main>', start);
    final landing = html.substring(start, end);
    expect(html.indexOf('<style id="svaultai-public-landing-style">'),
        lessThan(start));
    expect(end, lessThan(html.indexOf('src="flutter_bootstrap.js"')));
    expect(landing, contains('Your digital life.<br>One encrypted vault.'));
    expect(landing, contains('class="hero"'));
    expect(landing, contains('href="/signup">Create your free vault</a>'));
    expect(landing, contains('href="/login">Open your vault</a>'));
    expect(landing, contains('href="/pricing/"'));
    expect(landing, contains('href="/features/digital-inheritance/"'));
    expect(landing, contains('href="/privacy/"'));
    expect(landing, contains('1 GB included'));
    expect(
        landing, contains('actual localized price and current availability'));
    expect(landing,
        contains('Wallet features require an eligible paid storage plan'));
    expect(landing, contains('Approval releases credentials immediately'));
    expect(landing, contains('declining clears the request and countdown'));
    expect(landing, contains('on servers and with service providers'));
    expect(landing, contains('public-vault-blue.png'));
    expect(landing, isNot(contains('public-vault-demo.jpg')));
    expect(landing, isNot(contains('onclick=')));
    expect(_script(), isNot(contains('1000')));
  });

  test('initialized app render signal retires shell and cancels its timer', () {
    final result = _run("window.svaultaiAppRendered();");
    expect(result['removed'], 1);
    expect(result['previewRemoved'], 1);
    expect(result['cleared'], 1);
    expect(result['reloads'], 0);
  });

  test('late initialized render recovers after timeout or bootstrap error', () {
    for (final preceding in [
      "timer();",
      "events.error({message:'synthetic-private-marker'});"
    ]) {
      final result = _run("$preceding window.svaultaiAppRendered();");
      expect(result['removed'], 1);
      expect(result['cleared'], 1);
      expect(result['reloads'], 0);
      expect(result['text'], isNot(contains('synthetic-private-marker')));
    }
  });

  test('errors before the bounded wait preserve the safe startup status', () {
    for (final event in ['error', 'unhandledrejection']) {
      final result = _run(
          "events['$event']({message:'synthetic-private-marker', reason:'synthetic-private-marker'});");
      expect(result['text'], isEmpty);
      expect(result['messageHidden'], isTrue);
      expect(result['hidden'], isTrue);
      expect(result['reloads'], 0);
    }
  });

  test('delayed errors and rejected promises show safe generic copy only', () {
    for (final event in ['error', 'unhandledrejection']) {
      final result = _run(
          "events['$event']({message:'synthetic-private-marker', reason:'synthetic-private-marker'}); timer();");
      expect(result['text'],
          'SVaultAI could not open. Check your connection and try again.');
      expect(result['hidden'], isFalse);
      expect(result['messageHidden'], isFalse);
      expect(result['reloads'], 0);
      expect(result['text'], isNot(contains('synthetic-private-marker')));
    }
  });

  test('errors after the bounded wait update recovery without auto reload', () {
    final result = _run('timer(); events.error({});');
    expect(result['text'], contains('could not open'));
    expect(result['messageHidden'], isFalse);
    expect(result['reloads'], 0);
  });

  test('a missing image does not claim that the app failed', () {
    final result = _run("events.error({target:{tagName:'IMG'}}); timer();");
    expect(result['text'], contains('taking longer than usual'));
    expect(result['text'], isNot(contains('could not open')));
    expect(result['reloads'], 0);
  });

  test('post-handoff errors or old timer do not cover a running app', () {
    final result = _run(
        "window.svaultaiAppRendered(); events.error({}); events.unhandledrejection({}); timer(); window.svaultaiAppRendered();");
    expect(result['removed'], 1);
    expect(result['cleared'], 1);
    expect(result['hidden'], isTrue);
    expect(result['messageHidden'], isTrue);
    expect(result['text'], isEmpty);
  });

  test('a hidden or stale retry cannot reload a healthy startup', () {
    for (final scenario in [
      'buttonEvents.click();',
      "timer(); window.svaultaiAppRendered(); buttonEvents.click();",
    ]) {
      expect(_run(scenario)['reloads'], 0);
    }
  });

  test('only explicit retry reloads the same current route', () {
    final result = _run('timer(); buttonEvents.click();');
    expect(result['reloads'], 1);
    expect(_script(), contains('window.location.reload()'));
    expect(_script(), isNot(contains('location.href')));
    expect(_script(), isNot(contains('location.pathname')));
  });

  test('boot shell never touches authentication storage or requests content',
      () {
    final script = _script();
    for (final forbidden in [
      'localStorage',
      'sessionStorage',
      'indexedDB',
      'cookie',
      'fetch(',
      'XMLHttpRequest',
      'vault_name',
      'session_token'
    ]) {
      expect(script, isNot(contains(forbidden)));
    }
  });
}
