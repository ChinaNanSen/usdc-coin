# Shared Inventory Release Design

**Context**

当前系统已经具备：

- 路由感知进场闸门
- 主出口 / 备路评分
- release 腿单独释放
- 共享账本把 release 成交同步回主腿长仓

但还没有做到：

- release 腿根据主腿真实库存自动“放大释放”
- 让间接出口真正成为自动执行路径的一部分

**Recommended next slice**

先做“共享库存驱动释放”，不做完整跨市场自动下双腿。

最小闭环是：

1. `USD1-USDT` 主腿持有 `USD1` 长仓
2. 路由建议显示“间接卖出更优”
3. `USD1-USDC` release 腿按共享库存自动扩大卖出量
4. release 成交后通过共享账本把主腿长仓同步减掉

这样虽然还不是完整的多腿自动成交器，但已经能把：

- 主腿库存
- release 腿执行
- 长仓归因同步

串成一条自动链。

**Alternatives**

**方案 A：直接让主腿去下跨市场第二条腿**

- 优点：终局更接近
- 缺点：会把单市场执行层彻底打散，风险大

**方案 B：共享库存驱动 release 腿**

- 优点：最小改动，现有 release-only 结构能直接吃下
- 缺点：目前只覆盖 `USD1` 这类“通过 release 腿卖出”的方向

**Recommendation**

先做方案 B。

**Chosen behavior**

新增共享库存驱动原则：

- release 腿除了看自己的 `external_base_inventory_remaining`
- 还要看“同资产主腿的长仓可释放量”

然后：

- 可释放总量 = 本腿外部库存可释放 + 主腿共享长仓可释放
- 但单次释放量仍受：
  - 本腿 `quote_size`
  - 盘口深度预算
  - release-only 最小保留量

release 腿只在下面条件同时成立时放大：

1. 自身是 `release_only_mode`
2. 主腿共享长仓 > 0
3. 主腿当前路由建议主路不是 `direct`
4. 共享库存释放后，能通过账本同步回主腿

**State / data flow**

继续使用共享账本，不引入数据库协调器：

- 主腿：
  - 继续写自身状态快照
  - 继续写主出口 / 备路
- release 腿：
  - 读取主腿快照
  - 读取共享长仓规模
  - 自动扩大 release 下单量
  - 成交后写共享账本
- 主腿：
  - 再从共享账本减掉自己的长仓

**Non-goals**

这次不做：

- 通用多资产多腿自动执行器
- 任何方向的自动买入对冲
- 纯 taker 三角执行器

这次只把 `USD1` 的间接卖出路径真正自动化一半。
