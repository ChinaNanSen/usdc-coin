# USD1 Route Chain Report Design

**Context**

当前系统已经具备：

- `USD1-USDT` 主腿状态快照
- `USD1-USDC` release 腿状态快照
- 共享路由账本
- 按原因归因的成交分析工具

但现在要验证“这条链到底有没有改善周转和盈利”，还缺一个聚合视图。

**Recommendation**

新增一个独立报告，不改现有 audit summary。

原因：

- 当前 `audit_summary` 更偏单实例
- `USD1` 这条链是多实例协作
- 独立报告更容易把主腿、release 腿、共享账本放在同一页看

**Chosen behavior**

新增：

- `src/binance_route_chain_report.py`
- `scripts/binance_route_chain_report.py`

报告聚合以下内容：

1. 主腿当前状态
- `runtime_state`
- `runtime_reason`
- `strategy_position_base`
- `triangle_exit_route_choice`

2. release 腿当前状态
- `runtime_state`
- `runtime_reason`
- `external_base_inventory_remaining`
- `shared_release_inventory_base`

3. 主腿最近一次有成交 run 的归因
- `entry / rebalance`
- 成交额
- 已实现利润
- 每 `1万成交` 利润

4. release 腿最近一次有成交 run 的归因
- `release`
- 成交额
- 已实现利润

5. 共享账本汇总
- release 事件数
- release 总数量
- release 总金额

**Output shape**

输出保持纯文本，便于终端查看：

- `USD1 Route Chain Report`
- `Main Leg`
- `Release Leg`
- `Route Ledger`
- `Attribution`

**Non-goals**

这次不做：

- 图表
- sqlite 聚合重构
- 多链通用报告器

这次只服务 `USD1-USDT + USD1-USDC` 这条链。
