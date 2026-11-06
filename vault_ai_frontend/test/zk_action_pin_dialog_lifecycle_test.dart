import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show ZkActionPinDialog;

void main() {
  testWidgets('PIN dialog survives its closing animation after submit',
      (tester) async {
    String? returned;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(builder: (context) {
          return FilledButton(
            onPressed: () async {
              returned = await showDialog<String>(
                context: context,
                builder: (_) => const ZkActionPinDialog(title: 'Verify PIN'),
              );
            },
            child: const Text('Open'),
          );
        }),
      ),
    ));
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('zk_action_pin_field')), '123456');
    await tester.tap(find.text('Continue'));
    await tester.pump();
    expect(tester.takeException(), isNull);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(returned, '123456');
    expect(find.byKey(const Key('zk_action_pin_field')), findsNothing);
  });

  testWidgets('PIN dialog survives its closing animation after cancel',
      (tester) async {
    String? returned = 'unset';
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(builder: (context) {
          return FilledButton(
            onPressed: () async {
              returned = await showDialog<String>(
                context: context,
                builder: (_) => const ZkActionPinDialog(title: 'Verify PIN'),
              );
            },
            child: const Text('Open'),
          );
        }),
      ),
    ));
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pump();
    expect(tester.takeException(), isNull);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(returned, isNull);
    expect(find.byKey(const Key('zk_action_pin_field')), findsNothing);
  });
}
