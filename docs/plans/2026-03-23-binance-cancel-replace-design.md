# Binance CancelReplace Design

**Context**

`trend_bot_6` 现在的执行层已经有统一的改单入口：

- 策略层只表达目标价和目标数量
- 执行层优先尝试 `amend_order`
- 如果交易客户端不支持改单，或改单失败，就回退到撤单重挂

这套接口最初是按 OKX 的“原地改单”语义长出来的。Binance Spot 不一样：

- 改价不能像 OKX 那样直接原地改
- 更接近的标准接口是 `POST /api/v3/order/cancelReplace`
- 这个接口本质是“撤老单 + 新挂一张单”

用户这次要的不是再解释概念，而是把 `cancelReplace` 真接进执行层，让 Binance 在需要改价/改量时不再直接走“先失败再撤单重挂”的老路径。

**Recommendation**

保留现有执行层统一入口，只在 Binance REST 适配器里实现 `amend_order`。

这样做的原因：

- 策略层和大部分执行层逻辑已经稳定，不值得为了 Binance 单独分叉一套对账流程。
- 现有 `OrderExecutor._amend_order()` 已经是天然接入点，接好以后 Binance 会自动走改单优先、失败回退撤单。
- 风险最小。OKX 不用动，Binance 也只增加一个能力面。

**Chosen behavior**

Binance `amend_order()` 采用下面的行为：

1. 用 `orderId` 优先定位旧单，缺失时再退回 `origClientOrderId`
2. 调用 `POST /api/v3/order/cancelReplace`
3. 固定使用：
   - `cancelReplaceMode=STOP_ON_FAILURE`
   - `newOrderRespType=RESULT`
4. 下新单时继续保持当前 bot 的 `LIMIT_MAKER` / `post_only` 语义
5. 成功后返回“新单”的 `ordId` 和 `clOrdId`

**State bridging**

这是这次实现里最关键的一段，不做会出错。

因为 Binance `cancelReplace` 返回的是一张新单，所以本地状态不能继续把它当成“旧单被原地改成功”。否则会出现：

- 本地还挂着旧单影子
- 新单回报到了以后变成双单
- 下一轮对账时把自己搞成“重复挂单”

因此成功路径必须补一层状态桥接：

- 执行层拿到 Binance `cancelReplace` 成功响应后
- 先把旧单标记成已替换并从本地活跃订单映射中移走
- 再用返回的新 `ordId` / `clOrdId` 和目标价量，写入一条新的本地 live order
- 同时保留“待确认改单”记录，等私有回报或后续订单更新把这次改单正式结案

这样可以保证：

- 下一轮执行时只看见新单
- 仍然保留成交后确认链路
- 旧单迟到的取消回报也不会把新单冲掉

**Failure handling**

Binance `cancelReplace` 有 3 类关键失败面：

1. 撤旧单失败，新单未尝试
2. 旧单撤掉了，但新单下失败
3. 网络或解析异常，交易结果不确定

对应处理：

- 类 1：按“改单失败”记日志，清掉 pending amend，再回退执行层既有撤单逻辑
- 类 2：不要再额外撤一次，因为旧单已经没了；直接把本地旧单标记为已取消/移除，并让后续重挂流程接管
- 类 3：保守处理，清掉 pending amend，交给现有撤单回退和后续同步修正

这次第一版先保证“不把本地状态弄错”，不在这里额外加更复杂的恢复编排。

**Testing**

测试分两层：

- `tests/test_binance_rest.py`
  - 成功解析 `cancelReplace` 响应
  - 遇到 `-2021 / -2022` 等失败时抛出带细节的 `BinanceAPIError`
- 执行层测试
  - Binance 改单成功后，本地活跃订单应切换到新单
  - Binance 改单失败时，仍应回退到原来的撤单逻辑

**Non-goals**

这次不做：

- Binance `keepPriority` 接入
- Binance 批量改单
- Binance WS 写单
- 统一 OKX / Binance 的错误字段命名

这些都可以后续再补，但不应该和本次 `cancelReplace` 接入绑在一起。
