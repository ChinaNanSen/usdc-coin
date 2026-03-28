# Rebalance Profit Guard Design

**Context**

当前第 1 刀已经补了：

- `entry` 的滚动利润密度缩单

但数据里已经出现更危险的信号：

- `rebalance` 的 `per10k` 有时会为负

如果回补本身开始亏，整个做市利润会被很快吃掉。

**Recommendation**

第 2 刀先做 `rebalance` 利润保护。

不做复杂版本，只做两件事：

1. 最近 `rebalance per10k` 变差时，提高回补利润要求
2. 最近 `rebalance per10k` 变差时，缩小回补量

**Chosen behavior**

新增配置：

- `rebalance_profit_density_enabled`
- `rebalance_profit_density_window_minutes`
- `rebalance_profit_density_soft_per10k`
- `rebalance_profit_density_hard_per10k`
- `rebalance_profit_density_soft_size_factor`
- `rebalance_profit_density_hard_size_factor`
- `rebalance_profit_density_soft_extra_ticks`
- `rebalance_profit_density_hard_extra_ticks`

运行逻辑：

- bot 周期性从 journal 计算最近窗口内 `rebalance` 的：
  - turnover
  - realized
  - per10k
- state 保存：
  - `rebalance_profit_density_per10k`
  - `rebalance_profit_density_size_factor`
  - `rebalance_profit_density_extra_ticks`

策略读取后：

- 回补单量乘以 size factor
- 回补最小利润 tick 再加 extra ticks

**Scope**

这次只影响：

- `rebalance_open_long`
- `rebalance_open_short`

不影响：

- `entry`
- `release`
