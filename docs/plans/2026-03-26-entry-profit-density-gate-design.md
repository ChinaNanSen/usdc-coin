# Entry Profit Density Gate Design

**Context**

当前数据已经说明：

- 总周转提升了
- 但每 `1万成交` 利润下降了

这代表：

- 系统更忙了
- 但有一部分新增 `entry` 成交并不值钱

当前代码已经有：

- `entry_markout_penalty_factor`

但它只盯短期逆风，不盯真实利润密度。

**Recommendation**

先加“滚动 entry 利润密度门”。

不动执行层，只影响：

- `entry` 的下单大小

**Chosen behavior**

新增一组配置：

- `entry_profit_density_enabled`
- `entry_profit_density_window_minutes`
- `entry_profit_density_soft_per10k`
- `entry_profit_density_hard_per10k`
- `entry_profit_density_soft_size_factor`
- `entry_profit_density_hard_size_factor`

逻辑：

- 每轮根据当前实例最近窗口内的 `entry` 成交额和已实现利润，算 `entry per10k`
- 若低于软阈值：
  - `entry` 缩小到 `soft_size_factor`
- 若低于硬阈值：
  - `entry` 缩小到 `hard_size_factor`
- 只影响 `join_best_bid / join_best_ask`
- 不影响：
  - `rebalance`
  - `release`

**Implementation shape**

先从状态快照提供最近累计计数做最小版，不做复杂 DB 在线查询：

- 在 state 中增加一个滚动 entry 利润密度输入槽
- 在 bot 中周期性从 audit/journal 计算最近窗口的 `entry per10k`
- 策略读取这个值，对 entry 做缩放

这是最小可落地版本。

**Non-goals**

这次不做：

- 组合级全局降温器
- `rebalance` 的滚动利润门
- 跨实例统一 per10k 控制

这次只做第 1 刀。
