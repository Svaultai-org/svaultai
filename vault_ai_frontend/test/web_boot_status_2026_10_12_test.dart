import 'dart:convert';
import 'dart:io';

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
let timer = null, delay = null, cleared = 0, removed = 0, reloads = 0;
const status = { remove() { removed++; } };
const message = { textContent: 'Opening SVaultAI…' };
const retry = { hidden: true, addEventListener(k, fn) { buttonEvents[k] = fn; } };
const window = {
  setTimeout(fn, ms) { timer = fn; delay = ms; return 1; },
  clearTimeout(id) { if (id !== 1) throw new Error('unexpected timer'); cleared++; },
  addEventListener(k, fn) { events[k] = fn; },
  location: { reload() { reloads++; } }
};
const document = { getElementById(id) {
  return { 'svaultai-boot-status': status, 'svaultai-boot-message': message, 'svaultai-boot-retry': retry }[id];
} };
vm.runInNewContext(${jsonEncode(_script())}, { window, document });
$scenario
console.log(JSON.stringify({text: message.textContent, hidden: retry.hidden, delay, cleared, removed, reloads}));
''';
  final result = Process.runSync('node', ['-e', code]);
  expect(result.exitCode, 0, reason: 'Synthetic boot-script fixture must run');
  expect(result.stderr, isEmpty);
  return Map<String, dynamic>.from(jsonDecode(result.stdout as String) as Map);
}

void main() {
  test('a private-data-free shell paints before Flutter and opaque bootstrap',
      () {
    final html = _html();
    expect(html.indexOf('id="svaultai-boot-status"'),
        lessThan(html.indexOf('src="flutter_bootstrap.js"')));
    expect(html.indexOf('id="svaultai-boot-script"'),
        lessThan(html.indexOf('src="assets/opaque/vaultai-opaque-init.js"')));
    expect(html, contains('role="status" aria-live="polite"'));
    expect(html, contains('id="svaultai-boot-retry" type="button" hidden'));
    expect(html, contains('#seo-content { display: none !important; }'));
  });

  test('initial boot is visible without reloading or revealing retry', () {
    final result = _run('');
    expect(result['text'], 'Opening SVaultAI…');
    expect(result['hidden'], isTrue);
    expect(result['removed'], 0);
    expect(result['reloads'], 0);
    expect(result['delay'], 15000);
  });

  test('bounded wait offers a visible manual retry without an automatic reload',
      () {
    final result = _run('timer();');
    expect(result['text'], contains('taking longer than usual'));
    expect(result['hidden'], isFalse);
    expect(result['removed'], 0);
    expect(result['reloads'], 0);
  });

  test('actual first frame retires shell and cancels its timer', () {
    final result = _run("events['flutter-first-frame']();");
    expect(result['removed'], 1);
    expect(result['cleared'], 1);
    expect(result['reloads'], 0);
  });

  test('late first frame recovers normally after timeout or bootstrap error',
      () {
    for (final preceding in [
      "timer();",
      "events.error({message:'synthetic-private-marker'});"
    ]) {
      final result = _run("$preceding events['flutter-first-frame']();");
      expect(result['removed'], 1);
      expect(result['cleared'], 1);
      expect(result['reloads'], 0);
      expect(result['text'], isNot(contains('synthetic-private-marker')));
    }
  });

  test('errors and rejected promises show safe generic copy only', () {
    for (final event in ['error', 'unhandledrejection']) {
      final result = _run(
          "events['$event']({message:'synthetic-private-marker', reason:'synthetic-private-marker'});");
      expect(result['text'],
          'SVaultAI could not open. Check your connection and try again.');
      expect(result['hidden'], isFalse);
      expect(result['reloads'], 0);
      expect(result['text'], isNot(contains('synthetic-private-marker')));
    }
  });

  test('post-first-frame errors or old timer do not cover a running app', () {
    final result = _run(
        "events['flutter-first-frame'](); events.error({}); events.unhandledrejection({}); timer(); events['flutter-first-frame']();");
    expect(result['removed'], 1);
    expect(result['cleared'], 1);
    expect(result['hidden'], isTrue);
    expect(result['text'], 'Opening SVaultAI…');
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
