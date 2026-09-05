# 固定题组模型跑分

仅在用户要求评价某个模型作为海龟汤玩家的推理能力、比较多个玩家模型，或运行固定题组 benchmark 时加载本文件。普通双代理演练继续使用 `references/subagent-rehearsal.md`。

## 目标

- 使用与双子代理演练相同的带锁 mailbox 协议和信息隔离。
- 主持人与玩家各自在独立子代理上下文中运行。
- 不启动 Telegram 直播；主代理等待每局完成后评分。
- 主持人参数在同一次 baseline 中固定；默认 Luna high，用户可明确覆盖为 Luna max 等配置，覆盖值必须写入 `run.json`，同一比较内不得变化。
- 使用固定题组、固定顺序和固定重复次数；禁止随机抽题或临时换题。
- 默认逐局串行以保护延迟可比性；用户明确要求同一 provider 全题并发时，可按 trial 将 12 题并发运行。全部玩家配置必须采用相同并发度和批次结构。
- 同时报告原始指标、100 分评分、分层结果和重复运行离散程度。

## 固定题组

固定套件：

```text
/home/wow/.cache/turtlesoup/benchmarks/fixed-v1/
├── manifest.json
├── SHA256SUMS
└── puzzles/
    ├── SPB-C-E-01.json
    ├── SPB-C-E-02.json
    ├── SPB-C-M-01.json
    ├── SPB-C-M-02.json
    ├── SPB-C-H-01.json
    ├── SPB-C-H-02.json
    ├── SPB-A-E-01.json
    ├── SPB-A-E-02.json
    ├── SPB-A-M-01.json
    ├── SPB-A-M-02.json
    ├── SPB-A-H-01.json
    └── SPB-A-H-02.json
```

ID 规则：

- `C`：浓汤类型；`A`：荒诞类型。
- `E`：简单；`M`：中等；`H`：困难。
- 每个“类型 × 难度”固定两题，共 12 题。

默认每题重复 3 次，共 36 局。用户可明确指定不同重复次数，但同一比较中的全部模型必须保持一致。

### GitHub 分发与自动恢复

TurtleBench 仓库不跟踪题目 JSON。runner 启动时若配置的 `fixed-v1` 目录不存在，会从 GitHub Release `fixtures-v1` 自动下载加密 ZIP、校验固定 SHA-256，并使用 README 公布的密码解包。目录已经存在时直接沿用，禁止重新下载或覆盖；后续仍由 `verify_suite` 校验 manifest 与逐题哈希。

### 固定性要求

跑分前必须执行：

```bash
cd /home/wow/.cache/turtlesoup/benchmarks/fixed-v1
sha256sum -c SHA256SUMS
```

任一题缺失或哈希不匹配时停止。禁止：

- 从题库重新随机抽题；
- 用相似题替换失败文件；
- 因模型已经失败而跳过某题；
- 在不同模型之间改变题目顺序、重复次数、最大轮数或提示额度；
- 覆盖 `fixed-v1`。题组调整必须新建 `fixed-v2`。

## 固定运行参数

主持人默认使用：

```text
provider=openai-codex
model=gpt-5.6-luna
reasoning_effort=high
```

用户明确指定主持参数时，以用户值覆盖默认值，并将覆盖后的固定参数写入 `run.json`。本次 Luna max baseline 使用 `reasoning_effort=max`。

玩家使用用户指定的 provider、model、reasoning effort。未指定 reasoning effort 时，使用 `references/subagent-rehearsal.md` 中该模型条目的玩家默认值。

共同参数：

```text
max_rounds=50
player_hint_limit=2
role=leaf
fresh_context=true
cli_max_turns=180
session_source=turtle-bench
```

CLI 并发模式中，每轮通常需要一次 wait 和一次 write，`--max-turns` 不得沿用 80；50 轮题组固定使用 180。达到旧的 CLI 迭代上限属于基础设施无效局，保留记录后按同一 trial 重跑。长时间 baseline 必须使用可脱离聊天回合的进程管理方式，并把 stdout/stderr 写入 run 目录；runner 异常退出后按已有 terminal score、preliminary 和 mailbox 状态续跑。

每局都创建全新的 mailbox 和两个全新的子代理。不得复用上一局上下文、公开问答、提示或候选答案。

## 运行目录

```text
~/.cache/turtlesoup/benchmarks/runs/<run-id>/
├── run.json
├── summary.json
└── games/
    └── <player-model-slug>/
        └── <puzzle-id>/
            └── trial-<NN>/
                ├── game.json
                └── score.json
```

`run.json` 至少记录：套件版本、固定 manifest 路径、玩家 provider/model/reasoning、重复次数、开始和结束时间。不要把汤底复制进 `run.json`、`summary.json` 或 `score.json`。

## 每局启动流程

1. 按 `manifest.json` 顺序固定题目与 trial 编号。
2. 默认每次只运行一局。用户明确要求同一 provider 全题并发时，每个 trial 同时启动 12 道题；trial-01、02、03 依次运行，玩家配置仍按用户指定顺序串行切换。并发模式下延迟数据反映该固定负载条件，报告必须标注并发度。
3. 为每个 trial 创建独立目录，用 `game_mailbox.py init --max-rounds 50` 初始化 `game.json`。
4. 从 `references/subagent-rehearsal.md` 取主持人和玩家固化提示词，替换本局绝对路径和 game ID。
5. 主持人提示词可读取本局私密题目；玩家提示词只包含 mailbox 路径，禁止包含题目、manifest、suite 目录或其他题目路径。
6. 启动两个独立角色：
   - 串行默认模式：用一个 `delegate_task` batch，设置 `blocking=true`；
   - 用户明确要求全题并发且委派并发额度不足：可由 `scripts/benchmark_runner.py` 为每局启动两个独立 `hermes chat` CLI 会话，并显式传入 provider、model、reasoning effort、terminal toolset 和隔离规则。
   - host task/session：使用本次 baseline 在 `run.json` 中固定的主持参数；
   - player task/session：使用用户指定模型参数。
7. 不启动 `telegram_game_stream.py`，不写 main actor 的 hint/stop，不进行局中人工干预。
8. 每题三个 trial 终局后启动独立 judge；judge 必须通过 terminal 原子写入并回读 `judge.json`。runner 不能把评分员的自然语言“写入成功”视为交付，必须检查文件存在、JSON 数组恰有三项且 trial 集合为 1—3。
9. judge 返回 0 但文件缺失或结构错误时，保留每次日志并用新会话重试，最多三次；三次均失败才终止该玩家配置。
10. judge 通过后生成三个 `score.json`，再进入下一题或下一玩家配置。

委派形状（默认串行模式；主持参数替换为本次 baseline 的固定值）：

```text
delegate_task(
  tasks=[
    {goal: <主持人固化提示词>, role: leaf,
     provider: openai-codex, model: gpt-5.6-luna,
     reasoning_effort: high},
    {goal: <玩家固化提示词>, role: leaf,
     provider: <被测provider>, model: <被测model>,
     reasoning_effort: <被测等级>}
  ],
  blocking=true
)
```

不得把两个角色合并成一个子代理，也不得让主持人使用被测模型。

### benchmark 模式超时附加规则

把固化提示词中的持续 mailbox 等待改为单次 120 秒，并要求子代理把 terminal 工具超时设为至少 150 秒：

- mailbox 在 120 秒内无 revision 变化：先 snapshot，不得盲目重复刚才的写入。
- 自己刚写的事件已经存在：保存最新 revision，改用 wait。
- 自己刚写的事件不存在：以最新 revision 重试一次。
- 连续 3 次等待都没有 revision 前进：尽最大可能写 `type=exit, finish=error` 后退出。

这样 blocking batch 或 CLI 双进程可在一方异常退出时结束，不会无限等待。

## 有效局与无效局

### 无效局：保留记录并重跑

以下情况标为 `invalid_infrastructure` 或 `invalid_host`，不计入模型分数；使用相同 puzzle ID 和 trial 编号追加 `retry-01`。重跑前先做单请求 provider 健康探针；探针恢复后重跑，持续复现相同路由错误时停止该 provider，并将结果报告为 `N/A`。零有效局禁止显示 0 分：

- mailbox、文件锁、JSON 或委派基础设施失败；
- 角色日志出现 `API call failed after ...`、HTTP 4xx/5xx、provider 空流超时等外部调用失败；此类判定由 runner 根据日志确定性覆盖 judge，避免同类故障被分成有效失败与基础设施无效；
- 主持人泄露私密信息；
- 主持人回答与汤底、key_facts 或已确认事实明显矛盾，并实质改变玩家路径；
- 主持人把题目未限定、可任意替换且不影响核心链的扩展细节反复判为“是也不是”，诱导玩家误入虚假必解分支；
- 主持人未按顺序发布提示；
- 主持人提前退出导致玩家无法继续。

### 有效失败局：计入模型分数

以下属于玩家能力或可靠性，不能重跑抹除：

- 50 轮仍未解出；
- 玩家提前放弃；
- 玩家错误使用协议且未自行恢复；
- 玩家耗尽提示后仍无法形成闭合答案；
- 玩家自身工具使用或 revision 处理失败。

## 原始指标

从 mailbox 事件时间和问答序列计算：

- `solved`：是否解出；
- `rounds`：终局轮数；
- `hints_used`：玩家自主提示次数；
- `first_question_latency_s`：surface 到第一问；
- `player_latency_p50_s`、`player_latency_p90_s`：主持 response/hint 到下一条玩家 question；
- `total_wall_time_s`：surface 到终局；
- `question_count`；
- `atomic_question_rate`：只含一个可判定核心命题的问题比例；
- `useful_constraint_rate`：产生新约束、有效切分或连接已有事实的问题比例；
- `redundant_question_rate`：重复确认已有事实或同义改写比例；
- `unsupported_story_guess_rate`：没有已确认父节点便直接枚举具体故事的比例；
- `irrelevant_branch_max`：连续真正无关问题的最长长度；
- `contradiction_count`：遗忘、反转或误记主持回答的次数；
- `partial_misread_count`：把“是也不是”整体记为真或假的次数；
- `hint_conversion_rate`：提示后两轮内形成新有效约束或核心推进的比例。

延迟只计算玩家可行动区间。主持人的思考时间单独记录，不混入玩家延迟。

### 仪表盘耗时口径

- 时间轴使用每局平均净玩家耗时：`(player_active_time_s - context_compaction_time_s) / games`。
- `player_active_time_s` 只累加主持 response/hint 到下一条玩家 question 的区间，天然排除主持人行动阶段。
- 发布历史结果时，默认从 `~/.hermes/state.db` 的同 session 消息时间戳识别原地上下文压缩消息簇，扣除压缩期间等待；公开 JSON 只保留聚合秒数，不得输出 session ID。
- 资源表的总耗时也使用扣除压缩后的净玩家耗时，便于和图表保持同一口径。

## 100 分量化标准

### 1. 解题成功与轮数效率：30 分

- 成功解出：20 分；未解出：0 分。
- 轮数效率：最多 10 分，仅在解出时计算。

难度预算：

```text
简单 B=15
中等 B=25
困难 B=40
最大轮数 M=50
```

若 `rounds <= B`，轮数效率为 10。否则：

```text
round_score = 10 × max(0, (M - rounds) / (M - B))
```

### 2. 可观察推理链质量：20 分

仅依据公开问题序列评分，不奖励冗长内部独白。四项各 0—5 分：

1. **承接性**：下一问是否以已经确认的事实为父节点；
2. **层级推进**：是否从身份／状态／空间／时间逐步进入机制和因果；
3. **跨异常连接**：是否用同一条件解释多个汤面异常；
4. **分支回收**：否定或无关后能否回到最近有效节点，而非继续扩写旧故事。

`0` 表示几乎随机枚举，`3` 表示大部分问题有可见承接，`5` 表示形成清晰且最小的闭合链。

### 3. 问题信息价值：15 分

三项各 0—5 分：

1. **原子性**：问题能否得到单一清晰判定；
2. **压缩能力**：是否有效切分较大的解释空间；
3. **去重与聚焦**：是否避免同义重复、纯背景和无关装饰。

高分要求：`atomic_question_rate` 与 `useful_constraint_rate` 较高，同时 `redundant_question_rate`、`unsupported_story_guess_rate` 较低。

### 4. 提示决策与利用：10 分

从 6 分起，最终限制在 0—10：

- 每次在明确停滞后请求，并在随后两轮形成核心推进：`+2`，累计最多 `+4`；
- 无提示解出且过程中没有持续停滞：`+4`；
- 前 3 轮内请求提示：每次 `-2`；
- 连续请求两次提示：`-2`；
- 提示后两轮没有任何有效推进：每次 `-2`；
- 长时间停滞、仍有提示额度、最终却因轮数耗尽失败：`-2`。

“明确停滞”指连续至少 3 个问题没有新增约束，或现有事实无法导出高信息下一问。困难题合理使用提示不直接扣分。

### 5. 一致性、纠错与协议可靠性：10 分

从 10 分起扣分，最低 0：

- 每次明确遗忘或反转已确认回答：`-2`；
- 无新限定地重访已排除假设：`-1`；
- 每次误读“是也不是”：`-2`；
- revision 冲突、timeout 或控制事件后未按协议恢复：每次 `-2`；
- 玩家原因导致非正常提前退出：扣至 0。

### 6. 最终假设闭合度：5 分

- `5`：覆盖核心条件、因果链和全部汤面异常；
- `3—4`：核心机制基本正确，但遗漏一个必要关系或异常；
- `1—2`：只命中若干局部事实；
- `0`：没有形成可检验的最终假设。

主持人判定 solved 时通常为 5；评分者仍需检查是否因主持误判而应标记 `invalid_host`。

### 7. 玩家响应速度：10 分

先计算玩家响应延迟的 P50 和 P90：

```text
p50_component = 7 × clamp((60 - P50) / 55, 0, 1)
p90_component = 3 × clamp((120 - P90) / 110, 0, 1)
speed_score = p50_component + p90_component
```

其中 `clamp(x,0,1)` 把结果限制在 0—1。首问延迟和总耗时只报告，不重复计分。

## 评分纪律

- 推理链评分只看公开问题如何承接公开回答，不要求或声称读取隐藏思维链。
- 评分者不得因最终答案正确，反向把早期随机猜测评价为高质量推理。
- 评分者不得因模型写得长而提高推理链分数。
- 主持错误导致的假路径先判无效局；不能把该损失归给玩家。
- 轮数、延迟和提示事件必须由 mailbox 时间戳计算，禁止凭印象填写。
- 所有分项保留一位小数，总分为七项之和。

## 重复运行与聚合

每个 puzzle × trial 先得到一份 `score.json`。然后按以下顺序聚合：

1. **题目级**：该题多次运行的总分中位数、IQR、成功率、轮数中位数；
2. **分层级**：同一类型／难度两题的题目级中位数取算术平均；
3. **总榜**：六个分层分数做宏平均，每个分层权重相同；
4. **速度榜**：单列所有有效局的 P50/P90，不用总耗时替代；
5. **可靠性**：报告有效失败率、玩家协议错误率、无效主持局数和基础设施重跑数。

比较多个模型时必须使用相同的 suite version、题序、重复次数和主持参数。报告中位数与 IQR，不只展示最好成绩。

## `score.json` 最小结构

```json
{
  "suite_version": "fixed-v1",
  "puzzle_id": "SPB-C-M-01",
  "trial": 1,
  "player": {
    "provider": "<provider>",
    "model": "<model>",
    "reasoning_effort": "<level>"
  },
  "validity": "valid",
  "status": "solved",
  "raw": {
    "rounds": 0,
    "hints_used": 0,
    "first_question_latency_s": 0.0,
    "player_latency_p50_s": 0.0,
    "player_latency_p90_s": 0.0,
    "total_wall_time_s": 0.0,
    "atomic_question_rate": 0.0,
    "useful_constraint_rate": 0.0,
    "redundant_question_rate": 0.0,
    "unsupported_story_guess_rate": 0.0,
    "irrelevant_branch_max": 0,
    "contradiction_count": 0,
    "partial_misread_count": 0,
    "hint_conversion_rate": 0.0
  },
  "scores": {
    "outcome_round_efficiency": 0.0,
    "reasoning_chain": 0.0,
    "question_information": 0.0,
    "hint_strategy": 0.0,
    "consistency_recovery": 0.0,
    "final_closure": 0.0,
    "response_speed": 0.0,
    "total": 0.0
  },
  "failure_tags": [],
  "notes": []
}
```

`notes` 只写可由公开轨迹核验的简短依据，不写汤底全文。

## 失败标签

统一使用：

- `direction_drift`：从已确认主线漂移；
- `random_story_enumeration`：缺少父节点的具体故事枚举；
- `redundant_confirmation`：重复确认；
- `compound_question_overuse`：复合问题过多；
- `partial_answer_misread`：误读“是也不是”；
- `fact_forgetting`：遗忘已确认事实；
- `hint_too_early`：提示过早；
- `hint_not_used`：提示后无推进；
- `hint_hoarding`：持续停滞仍拒绝提示；
- `premature_final_guess`：过早提交完整故事；
- `missing_causal_closure`：最终假设缺少必要因果；
- `protocol_recovery_failure`：协议错误后未恢复。

## 最终报告

报告至少包含：

- 被测玩家 provider/model/reasoning；
- suite version、12 个固定题 ID、每题重复次数；
- 总分、成功率、轮数中位数、提示使用率、玩家延迟 P50/P90；
- 六个类型／难度分层分数；
- 七个评分维度的雷达式数值表；
- 失败标签频次；
- 每题中位数和 IQR；
- 无效局及重跑原因；
- 结论中的优势、限制和最常见失败模式。

不得公开题目汤底、未发布提示、key_facts 或私密题目路径之外的内容。

## 验证清单

- [ ] 使用 `fixed-v1` manifest，哈希全部通过。
- [ ] 12 题顺序固定，没有随机抽题或替换。
- [ ] 每个模型使用相同重复次数和最大轮数。
- [ ] 每局主持人参数与 `run.json` 记录完全一致，且同一 baseline 内没有变化。
- [ ] 玩家只读取 mailbox 公开内容。
- [ ] 每局使用两个独立角色会话和一个独立 mailbox。
- [ ] 默认模式使用 blocking batch；显式并发模式使用 runner 启动隔离 CLI 双进程。两种模式均没有启动直播。
- [ ] 没有局中人工提示或控制干预。
- [ ] 无效主持／基础设施局保留并按相同 trial 重跑。
- [ ] 玩家失败局没有被选择性删除。
- [ ] 所有延迟和轮数来自 mailbox 时间戳。
- [ ] 总分七项相加等于 100 分上限。
- [ ] 汇总使用六分层宏平均，并报告中位数与 IQR。
