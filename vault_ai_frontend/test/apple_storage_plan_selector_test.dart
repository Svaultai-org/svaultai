import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/storage_page.dart';

const _productId = 'svaultai.storage.50gb.monthly';
const _choice = StoreStorageTierChoice(
  productId: _productId,
  capacityLabel: '50 GB',
  localizedPrice: r'$25.00',
  rank: 1,
  periodLabel: 'month',
);

Widget _app(Widget child) => MaterialApp(
      home: Scaffold(body: Center(child: child)),
    );

void main() {
  test('catalog uses only backend-recognized Apple products', () {
    final plans = parseAppleStorageCatalog({
      'product_id': _productId,
      'billing_period': 'P1M',
      'storage_entitlement_bytes': 53687091200,
    });
    expect(plans, hasLength(1));
    expect(plans.single.productId, _productId);
    expect(plans.single.capacityLabel, '50 GB');
    expect(plans.single.billingPeriod, 'P1M');
  });

  test('catalog preserves all recognized total-storage Apple tiers', () {
    const capacities = <String, int>{
      '50gb': 53687091200,
      '100gb': 107374182400,
      '150gb': 161061273600,
      '200gb': 214748364800,
      '250gb': 268435456000,
      '300gb': 322122547200,
      '500gb': 536870912000,
      '1tb': 1073741824000,
    };
    final plans = parseAppleStorageCatalog({
      'products': [
        for (final entry in capacities.entries)
          {
            'product_id': 'svaultai.storage.${entry.key}.monthly',
            'billing_period': 'P1M',
            'storage_entitlement_bytes': entry.value,
            'display_capacity': entry.key == '1tb'
                ? '1 TB'
                : '${entry.key.substring(0, entry.key.length - 2)} GB',
          },
      ],
    });

    expect(plans, hasLength(8));
    expect(
      plans.map((plan) => plan.capacityLabel),
      ['50 GB', '100 GB', '150 GB', '200 GB', '250 GB', '300 GB',
       '500 GB', '1 TB'],
    );
    expect(plans.every((plan) => plan.billingPeriod == 'P1M'), isTrue);
  });

  testWidgets('selection and Continue are required before product is returned',
      (tester) async {
    String? selected;
    await tester.pumpWidget(_app(Builder(
      builder: (context) => ElevatedButton(
        key: const Key('open_apple_selector'),
        onPressed: () async {
          selected = await showModalBottomSheet<String>(
            context: context,
            isScrollControlled: true,
            builder: (_) => const AppleStoragePlanPicker(choices: [_choice]),
          );
        },
        child: const Text('Choose storage'),
      ),
    )));

    await tester.tap(find.byKey(const Key('open_apple_selector')));
    await tester.pumpAndSettle();
    expect(selected, isNull);
    expect(find.text(r'$25.00 / month'), findsOneWidget);
    expect(find.textContaining('50 GB total storage'), findsOneWidget);
    expect(find.textContaining('Adds 50 GB'), findsNothing);
    expect(
      tester
          .widget<ElevatedButton>(
            find.byKey(const Key('apple_storage_continue')),
          )
          .onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const Key('apple_storage_plan_$_productId')));
    await tester.pump();
    expect(selected, isNull);
    expect(
        find.byKey(const Key('apple_storage_selected_review')), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('apple_storage_continue')));
    await tester.tap(find.byKey(const Key('apple_storage_continue')));
    await tester.pumpAndSettle();
    expect(selected, _productId);
  });

  testWidgets('Cancel returns no product', (tester) async {
    String? selected = 'not-returned';
    await tester.pumpWidget(_app(Builder(
      builder: (context) => ElevatedButton(
        onPressed: () async {
          selected = await showModalBottomSheet<String>(
            context: context,
            builder: (_) => const AppleStoragePlanPicker(choices: [_choice]),
          );
        },
        child: const Text('Choose storage'),
      ),
    )));
    await tester.tap(find.text('Choose storage'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('apple_storage_cancel')));
    await tester.pumpAndSettle();
    expect(selected, isNull);
  });
}
