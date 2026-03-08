# Trend Bot 6

`trend_bot_6` 是一个面向 `USDC-USDT` 现货的 OKX 微做市骨架，重点不是“每分钟白捡 1 tick”，而是把以下关键环节先做对：

- 行情走公共 WebSocket `books5`
- 账户与订单回报走私有 WebSocket `account` / `orders`
- 启动时先用 REST 做一次元数据、余额、挂单对账
- 下单与撤单第一版继续走 REST，确认以后再切到私有 WS 交易
- 全程使用 `clOrdId` 做幂等管理
- 默认 `shadow` 模式，不带私钥也可以先跑观察逻辑

## 为什么不是直接照抄 bot5

`trend_bot_5` 的 OKX 下单链路方向是对的：启动先连交易所、运行时用订单回报对账、执行层统一封装、风险先行。

但 `bot5` 是永续合约系统，核心是：

- 市价开仓
- 成交后补挂止损 / 止盈算法单
- 方向型仓位管理

`bot6` 面向的是 `USDC-USDT` 现货双边挂单，关键矛盾变成：

- 排队与成交概率
- 库存偏移
- 撤单重挂节奏
- 盘口失真 / 断线保护

所以 `bot6` 沿用了 `bot5` 的“启动对账 + 执行器 + 风控 + 私有回报确认”思路，但把策略和执行模型换成了现货微做市版本。

## 目录

- `main.py`：CLI 入口
- `config/config.example.yaml`：配置样例
- `src/config.py`：配置加载
- `src/okx_rest.py`：OKX REST 客户端
- `src/market_data.py`：公共盘口 WebSocket
- `src/private_stream.py`：私有订单 / 账户 WebSocket
- `src/strategy.py`：双边挂单策略
- `src/risk.py`：库存、断线、亏损、陈旧盘口保护
- `src/executor.py`：REST 下单 / 撤单 / 对账
- `src/state.py`：本地状态
- `docs/feasibility.md`：方案可行性与数据依据

## 运行

1. 复制配置

```bash
copy config\config.example.yaml config\config.yaml
```

2. 配环境变量

```bash
set OKX_API_KEY=...
set OKX_SECRET_KEY=...
set OKX_PASSPHRASE=...
```

3. 先跑影子模式

```bash
python main.py --config config/config.yaml --mode shadow
```

4. 确认日志、盘口、库存逻辑正常后，再切实盘

```bash
python main.py --config config/config.yaml --mode live
```

## 注意

- 第一版默认只做 `USDC-USDT`
- 第一版只做一档 / 单边一个挂单
- 第一版不默认启用应急 IOC 扫单
- OKX 零费政策可能变化，`bot6` 不把“永久零费”写死在代码里
