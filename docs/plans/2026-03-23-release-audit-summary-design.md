# Release Audit Summary Design

**Context**

当前 release-only 腿已经有：

- 状态文件里的 `initial_external_base_inventory`
- 状态文件里的 `external_base_inventory_remaining`
- 运行时面板里的 release 状态

但摘要里还看不到这些信息。

用户要的是：不盯终端，只看摘要，也能知道：

- 这条腿起始外部库存是多少
- 现在还剩多少
- 这轮已经释放了多少
- 现在还能继续释放多少

**Approach comparison**

**方案 A：只在快照区显示 release 状态**

- 优点：最小改动
- 缺点：看不到本次运行里 release 成交的笔数和成交额

**方案 B：快照区 + 运行区都补**

- 优点：最完整
- 快照区看“总剩余 / 已释放”
- 运行区看“本轮 release 成交量 / 成交额”
- 缺点：要补一点 run 级聚合逻辑

**Recommendation**

采用方案 B。

**Chosen design**

在摘要里补两层：

1. 快照区

当 `config.strategy.release_only_mode=true` 时，新增一行：

- `释放模式: 初始外部库存=... 当前剩余=... 已释放=... 保留量=... 当前可释放=...`

口径：

- 初始外部库存：`initial_external_base_inventory`
- 当前剩余：`external_base_inventory_remaining`
- 已释放：`max(initial - remaining, 0)`
- 当前可释放：`max(min(remaining, 当前 base 余额) - 保留量, 0)`

2. 运行区

在 `_render_run_section()` 里，按 `order_update` 事件的 `reason` / `reason_bucket` 统计 release 成交：

- release 成交笔数
- release 成交 base 数量
- release 成交 quote 金额

然后新增一行：

- `释放成交=...笔/...BASE/...U`

**Scope control**

这次不做：

- 多 run 汇总 release 成交
- 独立的 release 日报脚本
- 按 release 原因细分更多类别

这次只在现有摘要里补最值钱的信息。

**Testing**

补两条测试：

1. release-only 快照能显示：
- 初始外部库存
- 当前剩余
- 已释放
- 保留量
- 当前可释放

2. 运行区能显示 release 成交汇总
