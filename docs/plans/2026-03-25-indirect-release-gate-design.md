# Indirect Release Gate Design

**Context**

当前系统已经做到：

- 主腿能计算主出口 / 备路
- release 腿能吃共享长仓
- release 成交能同步减主腿仓位

但还缺一个关键冲突闸门：

- 主腿仍可能继续直接挂卖
- release 腿也可能同时代卖同一份逻辑库存

这会导致：

- 两边同时抢卖
- 短时双重暴露
- 行为不稳定

**Recommended next slice**

先做两个门：

1. release 腿只在“共享库存足够大 + 间接改善足够明显”时才放大
2. 主腿在“间接明显更优”时暂停直接卖出回补，把卖出执行权交给 release 腿

这是最小的冲突控制版本。

**Approach comparison**

**方案 A：直接做全局库存 reservation 引擎**

- 优点：最完整
- 缺点：改动大，接近组合引擎重构

**方案 B：阈值 + 主腿让路门**

- 优点：最小改动，已经能明显降低双卖冲突
- 缺点：还是基于多实例协作，不是统一账本引擎

**Recommendation**

先做方案 B。

**Chosen behavior**

新增两个 release-only 共享阈值：

- `release_only_shared_inventory_min_base`
- `release_only_shared_inventory_min_improvement_bp`

release 腿只有在：

- 主腿共享长仓 >= `release_only_shared_inventory_min_base`
- 主腿当前主路不是 `direct`
- `improvement_bp >= release_only_shared_inventory_min_improvement_bp`

时，才把共享长仓算进 release 量。

同时，主腿新增“让路门”：

- 当自己当前 `triangle_exit_route_choice.primary_route` 不是 `direct_*`
- 且 `improvement_bp >= triangle_prefer_indirect_min_improvement_bp`
- 且当前是正仓需要卖出回补

则：

- 不再发直接卖出 `rebalance_open_long`
- 让 release 腿去卖

**Non-goals**

这次不做：

- 全局 reservation 账本
- 任意方向的跨市场自动买入
- 纯三角 taker 执行器

这次只解决“主腿和 release 腿同时卖”的冲突。
