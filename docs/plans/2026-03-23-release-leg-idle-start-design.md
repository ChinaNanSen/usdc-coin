# Release Leg Idle-Start Design

**Context**

`USD1-USDC` 已经被改成 release-only 模式，但当前还有一个现实问题：

- 启动预算门禁会要求配置预算不能大于账户当前余额
- release-only 腿如果当前没有足够 `USD1`，就可能在启动阶段直接被拦掉

这和 release-only 的目标冲突。一个真正的释放腿应该是：

- 可以常驻运行
- 没库存时自动待机
- 库存一多时自动开始释放

而不是每次都要人为再启动一次。

**Approach comparison**

**方案 A：脚本启动前先查余额**

- 优点：实现简单
- 缺点：如果之后余额变多，release 腿仍然没启动，必须人工再拉起

**方案 B：release-only 模式绕过启动预算门禁**

- 优点：最符合 release 腿定位，可以常驻待机
- 缺点：需要明确只对 release-only 生效，避免误伤普通实例

**Recommendation**

采用方案 B。

**Chosen behavior**

当 `strategy.release_only_mode=true` 时：

- 启动预算门禁不再因为“当前账户 `base/quote` 小于配置预算”而直接停机
- release 腿常驻启动
- 没有足够外部库存时，由策略返回 `release_only_idle`
- 一旦账户余额刷新后外部库存超过保留量，release 腿自动进入释放

**Safety boundary**

这个放行只针对 release-only 模式，不影响：

- `USDC-USDT`
- `USD1-USDT`
- 其他普通做市实例

普通实例仍然保留现有启动预算门禁。

**Script behavior**

对应地，`scripts/run_binance_stable_core.sh` 默认应当把 `USD1-USDC` 也带起来。

原因：

- 现在 release-only 腿已经可以安全待机
- 再默认跳过它，反而会失去“库存一来就自动释放”的意义

保留环境变量开关即可：

- 默认启动
- `START_USD1_USDC=0` 时手动关闭

**Testing**

最关键测试：

1. release-only 实例在预算高于当前余额时，预算门禁不拦截
2. 普通实例仍然会被预算门禁拦截
3. 稳定币一键脚本默认启动 release 腿，但语法保持有效
