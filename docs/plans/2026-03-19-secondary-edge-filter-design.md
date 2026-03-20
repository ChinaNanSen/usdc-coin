# Secondary Edge Filter Design

**Goal:** Reduce low-value secondary turnover without blocking primary rebalance exits.

**Context:** Recent runs show execution stability is acceptable, but profit density is low. The main remaining issue is that `rebalance_secondary_*` and second-layer entry quotes can still trade at very thin edge in 1-2 tick conditions.

**Design:**
- Add a shared passive-edge calculation used by both strategy creation and executor overlay preservation.
- Apply a soft filter only to secondary quotes:
  - below minimum positive edge: do not create the quote
  - at thin edge: create the quote with reduced size
  - at healthy edge: create the quote at normal size
- Apply a stricter edge threshold to `join_second_*` layers so extra layers only appear when spread quality is better.
- Keep `rebalance_open_short`, `rebalance_open_long`, and `release` behavior unchanged except for already-landed safeguards.

**Non-goals:**
- No global dynamic profit floor yet.
- No changes to primary rebalance quote generation.
- No new executor throttling or execution transport changes.

**Validation:**
- Strategy tests for thin-edge scaling, below-threshold suppression, and stricter second-layer gating.
- Executor test ensuring overlay preservation uses the same secondary edge definition.
