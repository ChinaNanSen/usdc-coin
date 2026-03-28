# Route-Aware Buy Cap Design

**Context**

当前系统已经有：

- route-aware entry gate
- route-aware direct sell floor
- USD1 链的间接优先 handoff

但买入方向还不对称。

如果当前持有的是负仓，需要买回，而图路由判断：

- 直接买回更贵
- 绕路买更便宜

当前系统还会按本市场直接回补价格去买。

**Recommendation**

先补“route-aware direct buy ceiling”，不做自动间接买入执行。

这样做的好处：

- 最小改动
- 对称补齐买卖两侧利润保护
- 不引入新的跨市场执行器

**Chosen behavior**

新增：

- `triangle_direct_buy_ceiling_enabled`

逻辑：

- 当 `triangle_exit_route_choice.direction == "buy"`
- 且 `primary_route` 不是 `direct_*`
- 且当前市场没有对应的 buy-side handoff 机制
- 且 `improvement_bp` 超过阈值

则：

- 直接回补买价不能高于 `primary_reference_price`

人话版：

- 如果系统已经知道“绕路买更便宜”
- 那至少不要在本市场用更差价格直接买回

**Scope**

这次只影响：

- 需要买回时的 `rebalance_buy`

这次不影响：

- 普通 entry 买单
- 纯 taker 三角
- 跨市场自动买入执行
