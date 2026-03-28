# Binance Stable Core Design

**Context**

当前仓库已经有：

- Binance 现货适配
- 单实例 Binance `USDC-USDT` 主网配置
- 市场观测器
- 后台启动 / 停止脚本

用户这次确认的目标不是继续讨论，而是按优先级把 Binance 的稳定币做市方案落地：

- `USDC-USDT` 作为主引擎
- `USD1-USDT` 作为第二引擎
- `USD1-USDC` 只做小额度释放通道，不默认当第三个主战场

**Recommended scope**

第一阶段只做“可立即运行的生产骨架”，不改策略核心：

1. 增加 Binance 稳定币观测默认名单
2. 增加 `USD1-USDT` 和 `USD1-USDC` 主网配置
3. 增加 Binance 稳定币一键启动 / 停止脚本
4. `USD1-USDC` 默认通过环境开关控制，避免未准备好库存时自动开跑

这样做的原因：

- 收益最高的前两步是把 `USDC-USDT` 和 `USD1-USDT` 的运行面搭起来
- `USD1-USDC` 当前更适合作为释放通道和小额度试点，默认不自动启动更稳
- 不需要改策略或状态机，就能让用户尽快开始采数据和真钱对比

**Approach comparison**

**方案 A：只加配置和脚本**

- 优点：最快，风险最小
- 缺点：市场观测默认仍然是 OKX 稳定币名单，体验不完整

**方案 B：配置 + 脚本 + Binance 观测默认名单**

- 优点：最符合当前需求，改动小，启动前就能先看 3 个 Binance 对
- 缺点：`USD1-USDC` 仍不是“真正的释放专用模式”，只是小额度单独实例

**方案 C：直接做 Binance 三市场联动调度**

- 优点：更接近最终形态
- 缺点：过早，大改，风险高，不符合当前“先上双核心、再观察释放腿”的优先级

**Chosen design**

采用方案 B。

**Config layout**

新增：

- `config/config.binance.observe.yaml`
- `config/config.binance.usd1usdt.mainnet.yaml`
- `config/config.binance.usd1usdc.mainnet.yaml`

配置原则：

- 全部使用 Binance mainnet
- 保持 `post_only: true`
- 继续关闭辅助挂单
- `USDC-USDT` 作为主引擎，沿用较高额度
- `USD1-USDT` 作为次引擎，额度更小
- `USD1-USDC` 作为释放腿，额度最小

**Script behavior**

新增：

- `scripts/run_binance_stable_core.sh`
- `scripts/stop_binance_stable_core.sh`

启动脚本流程：

1. 先跑 Binance 三市场观测
2. 启动 `USDC-USDT`
3. 启动 `USD1-USDT`
4. 只有当 `START_USD1_USDC=1` 时，才启动 `USD1-USDC`

停止脚本流程：

- 对三套配置都发停止请求
- 等待退出
- 需要时支持 `FORCE_KILL=1`

**Known limitation**

`USD1-USDT` 和 `USD1-USDC` 仍然是普通单市场实例，不是真正的“只释放库存”专用模式。

但这不影响第一阶段目标，因为用户现在最需要的是：

- 先把双核心跑起来
- 让 `USD1-USDC` 有可控的小额度入口
- 用真实数据判断是否值得进入下一阶段

**Testing**

本次主要验证：

- Binance 观测默认名单切换正确
- 配置能被现有加载器正确读取
- 启停脚本语法正确
- 市场观测命令能在 Binance 配置下正常输出三对结果
