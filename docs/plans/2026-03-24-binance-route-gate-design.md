# Binance Route Gate Design

**Context**

用户最终目标不是再做单腿做市，而是把 `USDC-USDT / USD1-USDT / USD1-USDC` 做成能自动利用多出口的图路由系统。

但当前架构还是单市场实例：

- `USDC-USDT` 一个 bot
- `USD1-USDT` 一个 bot
- `USD1-USDC` 一个 release-only bot

直接上“跨市场自动出口执行器”会是大重构。

**Recommended first slice**

先做第一阶段最小闭环：

1. 为 `USDC-USDT` 和 `USD1-USDT` 增加三市场路由快照
2. 把进场买单改成“路由感知的进场闸门”
3. 只有当当前买单价格满足“双出口安全边”条件时，才允许挂买单

这一步先解决：

- 少做低价值买单
- 减少把钱沉成 `USDC / USD1`
- 提高后续出口可选性

**Alternatives**

**方案 A：直接做完整跨市场自动出口执行**

- 优点：最接近终局
- 缺点：会改执行层、仓位所有权、跨实例账本，太大

**方案 B：单独做一个外部路由观察器**

- 优点：侵入小
- 缺点：不能直接影响当前挂单行为，价值不够

**方案 C：路由感知进场闸门**

- 优点：最小改动，直接影响成交质量
- 缺点：还没有真正做跨市场自动出口

**Recommendation**

先做方案 C。

**Chosen behavior**

支持的当前市场：

- `USDC-USDT`
- `USD1-USDT`

不对 `USD1-USDC` 做这个闸门，因为它现在是 release-only。

对于这两个市场，bot 低频抓取另外两个市场的 best bid/ask，形成一个三市场快照。

### 1. `USD1-USDT` 买单的双出口

如果在 `USD1-USDT` 上买到 `USD1`，有两个出口：

- 直接在 `USD1-USDT` 被动卖出
- 走 `USD1-USDC -> USDC-USDT`

用当前快照计算：

- 直接被动出口价：`ask(USD1-USDT)`
- 间接立即出口价：`bid(USD1-USDC) × bid(USDC-USDT)`

### 2. `USDC-USDT` 买单的双出口

如果在 `USDC-USDT` 上买到 `USDC`，有两个出口：

- 直接在 `USDC-USDT` 被动卖出
- 走 `USDC -> USD1 -> USDT`

用当前快照计算：

- 直接被动出口价：`ask(USDC-USDT)`
- 间接立即出口价：`bid(USD1-USDT) / ask(USD1-USDC)`

### 3. 打分规则

定义：

- `direct_exit_edge_bp`
- `indirect_exit_edge_bp`
- `strict_dual_exit_edge_bp = min(direct, indirect - penalty)`
- `best_exit_edge_bp = max(direct, indirect - penalty)`

允许挂买单的条件：

- `strict_dual_exit_edge_bp >= triangle_strict_dual_exit_edge_bp`
  或
- `best_exit_edge_bp >= triangle_best_exit_edge_bp`
  且
- `strict_dual_exit_edge_bp >= -triangle_max_worst_exit_loss_bp`

这就是第一阶段的“一个买成功，至少两个出口中有一个够赚，最差出口也不能太烂”。

**State and visibility**

路由快照放进 `BotState`，用于：

- 策略读取
- 状态快照落盘
- 后续面板/摘要可视化

**Non-goals**

这次不做：

- 真正的跨市场自动出口下单
- 真正的纯三角 taker 执行器
- 全局多实例共享库存账本

这些等第一阶段数据跑出来再说。
