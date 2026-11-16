# Synthetic dataset validation report

- Database: `database/warehouse_synthetic.db` (full size, seed 20261111, history to 2026-11-10)
- Size configuration: full
- Checked at: 2026-11-16 10:40 UTC
- Result: **PASSED**: 48 passed, 0 failed, 0 skipped

## Integrity

| Check | Result | Value | Expected |
|---|---|---|---|
| No orphan records (foreign keys) | ✅ pass | 0 | 0 |
| No negative stock | ✅ pass | 0 | 0 |
| Movements never take stock below zero | ✅ pass | 0 | 0 |
| Stock equals the sum of its movements | ✅ pass | 0 | 0 |
| Bins within weight and volume limits | ✅ pass | 0 | 0 |
| Active reservations match reserved stock | ✅ pass | 0 | 0 |
| Order lines: shipped <= packed <= picked <= ordered | ✅ pass | 0 | 0 |
| Order status matches its latest history entry | ✅ pass | 0 | 0 |
| Shipped orders have one shipment and the right dates | ✅ pass | 0 | 0 |
| One shipment per order | ✅ pass | 0 | 0 |
| Cancelled orders have a cancel date and ship nothing | ✅ pass | 0 | 0 |
| Returns never exceed shipped units | ✅ pass | 0 | 0 |
| Purchase orders: received <= ordered | ✅ pass | 0 | 0 |
| Picking tasks: picked <= task quantity | ✅ pass | 0 | 0 |

## Volume

| Check | Result | Value | Expected |
|---|---|---|---|
| Warehouses | ✅ pass | 3 | 3 |
| Zones | ✅ pass | 18 | 18 |
| Racks | ✅ pass | 180 | 180 |
| Bins | ✅ pass | 5,760 | 5,760 |
| Products | ✅ pass | 2,000 | 2,000 |
| Suppliers | ✅ pass | 100 | 100 |
| Customers | ✅ pass | 10,000 | 10,000 |
| Carriers | ✅ pass | 6 | 6 |
| Orders | ✅ pass | 499,179 | 500,000 ± 10% |
| Order lines per order | ✅ pass | 2.53 | 2.0 - 3.0 |
| Days of order history | ✅ pass | 730 (2024-11-11 to 2026-11-10) | about 730 |
| Inventory movements per order | ✅ pass | 6.7 | >= 3 (reserve, pick, receipts) |
| Purchase orders | ✅ pass | 67,923 | > 0 |
| Shipments | ✅ pass | 489,248 | > 0 |
| Returns | ✅ pass | 42,045 | > 0 |

## Patterns

| Check | Result | Value | Expected |
|---|---|---|---|
| Weekday orders above weekends | ✅ pass | 1.90x per day | >= 1.3x |
| Holiday peak in November and December | ✅ pass | 1.28x per day | >= 1.15x |
| Growth: second year above the first | ✅ pass | 1.09x per day | > 1.0x |
| Fast movers: top 20 % of products | ✅ pass | 59% of units | >= 50 % |
| Intermittent demand | ✅ pass | 45% of products sell on < 30 % of days | 5 - 60 % |
| Products bought together (baskets) | ✅ pass | 572 product pairs with lift > 3 | >= 5 |
| Supplier lead times differ | ✅ pass | 2.3 to 30.8 days (13.3x) | >= 1.5x between suppliers |
| Suppliers less reliable in peak season | ✅ pass | 39% late vs 25% | peak > rest |
| Late deliveries | ✅ pass | 9.3% | 3 - 20 % |
| Large orders more often late | ✅ pass | 17.6% vs 8.9% | > 1.3x |
| Orders that waited for stock more often late | ✅ pass | 30.3% vs 8.4% | > 1.3x |
| Peak season deliveries more often late | ✅ pass | December 17.6% vs 8.0% | > 1.3x |
| Carriers differ in reliability | ✅ pass | 7.4% to 13.8% late | > 1.3x between carriers |
| Heavy goods on the lowest shelf | ✅ pass | 58% of heavy vs 24% of light stock records on level 1 | heavy > light |
| Fast movers picked nearer to packing | ✅ pass | 26.1 m vs 47.3 m to packing | fast movers nearer |
| Return rate | ✅ pass | 2.6% of shipped units | 1 - 15 % |
| Some returns damaged | ✅ pass | 36% of returned lines | 10 - 60 % |
| Noise: short picks and stock adjustments | ✅ pass | 0.41% short picks, 22,988 adjustments | a little (0 - 2 %) |
| Warehouse space not overfilled | ✅ pass | WH01 86%, WH02 66%, WH03 47% | <= 90% of storage volume |
