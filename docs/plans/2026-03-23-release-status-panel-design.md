# Release Status Panel Design

**Context**

`USD1-USDC` 已经有了 release-only 逻辑，但现在终端状态面板里还看不出：

- 它是不是 release-only
- 外部库存还剩多少
- 保留量是多少
- 当前是在待机还是在释放

这会让用户盯盘时看不懂：

- 为什么这个实例没挂单
- 为什么它突然开始挂卖单

**Approach comparison**

**方案 A：只看 runtime_reason**

- 优点：零新增字段
- 缺点：信息不够，还是看不到库存剩余和保留量

**方案 B：状态面板新增一行 release**

- 优点：最直接，几乎不影响其他逻辑
- 缺点：需要给状态面板传入 release-only 配置

**Recommendation**

采用方案 B。

**Chosen design**

状态面板新增一行：

- `释放 | 模式=是/否 外部库存剩余=... 保留量=... 可释放=... 当前动作=待机/释放中`

展示规则：

- 只在 `release_only_mode=true` 时显示
- `外部库存剩余` 来自 `state.external_base_inventory_remaining`
- `保留量` 来自 `strategy.release_only_base_buffer`
- `可释放` 用 `state.external_release_base_size()` 算
- `当前动作`
  - 决策是 `release_external_sell_only` 或存在 `release_external_long` 卖单时显示“释放中”
  - 否则显示“待机”

**Scope control**

这次不做：

- 单独的 release-only runtime state
- 面板颜色或格式大改
- 新增更多 release-only 统计指标

这次只做最小可读性增强。

**Testing**

补一条状态面板测试，验证 release-only 面板里能看到：

- `释放 |`
- `模式=是`
- `外部库存剩余`
- `保留量`
- `可释放`
- `当前动作=释放中`
