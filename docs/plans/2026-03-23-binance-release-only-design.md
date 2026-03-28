# Binance Release-Only Design

**Context**

`USD1-USDC` 当前只是被配置成一个更小额度的普通单市场实例。

这不满足用户的真实要求。用户要的是：

- `USD1-USDC` 只在 `USD1` 偏多时工作
- 它是“释放腿”，不是第三个普通做市引擎
- 本地状态文件和真实交易必须保持同步

现有代码里有两个关键现实：

1. 策略已经有 `release` 阶段，但那是普通做市仓位的释放，不是“外部库存释放模式”
2. `BotState._record_live_fill()` 里，卖出如果没有正仓，会被记成负仓，也就是本地会认为自己开了空仓

如果直接把 `USD1-USDC` 改成“只挂卖单”，会带来一个错误后果：

- 它卖掉外部 `USD1`
- 但本地状态会把自己记成开空
- 然后它又想买回来

这不是真释放模式。

**Approach comparison**

**方案 A：纯配置单边卖**

- 做法：禁用买单，只保留卖单
- 问题：卖出会被本地账记成负仓，状态和真实意图不一致

**方案 B：真正的释放模式**

- 做法：新增 `release_only_mode`
- 只在“外部库存剩余大于保留量”时发卖单
- 卖出优先冲减“外部库存剩余”，不记成策略负仓
- 余额更新时把外部库存剩余向真实账户余额收敛

**方案 C：跨实例共享库存释放**

- 做法：让 `USD1-USDC` 去释放 `USD1-USDT` 产生的仓位
- 问题：当前单实例账本没有跨实例仓位转移机制，主实例本地仓位会和真实账户脱节

**Recommendation**

采用方案 B。

这是当前最小、最安全、同时满足“状态同步”和“释放腿不变第三引擎”的方式。

**Chosen behavior**

新增两个策略配置：

- `release_only_mode`
- `release_only_base_buffer`

当 `release_only_mode=true` 时：

1. 默认不做双边做市
2. 只有当 `external_base_inventory_remaining > release_only_base_buffer` 时，才允许发卖单
3. 卖单理由使用 `release_external_long`
4. 正常情况下不发买单
5. 只有在本实例真的因为异常产生了负仓时，才允许按现有回补逻辑去买回

**State synchronization**

这是本次设计最重要的部分。

新增一个状态配置：

- `release_tracking_enabled`

开启后：

1. 初始化时，`external_base_inventory_remaining` 继续来自当前 base 余额
2. 卖出成交时，先冲减 `external_base_inventory_remaining`
3. 只有卖出超过外部库存剩余的部分，才会被记成策略负仓
4. 每次余额刷新或账户更新后，`external_base_inventory_remaining` 都会被向真实 base 总余额下压收敛

这保证：

- 状态文件不会把正常释放错记成“做空”
- 如果外部手工划走了一部分币，本地剩余量也不会高于真实余额

**Explicit non-goal**

这次不做跨实例库存共享。

也就是说：

- `USD1-USDC` 的释放模式只对它自己这份“外部库存桶”负责
- 不直接去认领 `USD1-USDT` 实例自己的策略仓位

原因很简单：当前没有跨实例仓位转移账本，硬做会让主实例本地仓位和真实交易不同步。

**Testing**

最关键的测试有 3 类：

1. 策略测试
- release-only 且外部库存高于保留量时，只出卖单
- 外部库存不够时，不出单

2. 状态测试
- release-only 卖出先减少 `external_base_inventory_remaining`
- 不生成负的 `strategy_position_base`

3. 收敛测试
- 余额更新后，`external_base_inventory_remaining` 不得高于真实 base 总余额
