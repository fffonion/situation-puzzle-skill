# 已有题目的双子代理主持／玩家演练

仅在题目已经完成并有私密 JSON 文件、用户要求由隔离的主持人子代理与玩家子代理自动演练时加载本文件。主代理负责启动、控制和回收；主持人可以读取汤底，玩家始终只能读取公开邮箱。

## 目标与边界

- 使用两个独立 `delegate_task` 叶子子代理：一个主持人、一个玩家。
- 两次委派都必须使用后台模式，禁止 `blocking=true`。
- 两个子代理不直接通信，只通过 `scripts/game_mailbox.py` 读取和写入同一个状态文件。
- 每次写入都由脚本取得 `fcntl.flock` 排他锁，并以临时文件加 `os.replace` 原子替换。
- 主代理在两个子代理启动后，以后台进程运行 `scripts/telegram_game_stream.py`；该进程读取公开事件并反复编辑当前 Telegram 会话中的同一条消息。
- 主代理确认直播进程已取得 `message_id` 后结束当前对话轮次，不等待子代理。
- 直播脚本使用 `--linger-after-terminal`：游戏结束后保留最终画面并继续运行。只有在两个子代理各自的后台完成消息都返回后，主代理才关闭该进程。
- 主代理可以在后续用户消息中写入 `hint` 或 `stop` 控制事件。
- 玩家另有两次自主提示机会；玩家自行判断使用时机，并以 `actor=player` 的 `control/hint` 事件向主持人请求。该额度由邮箱脚本强制计数，与用户通过主代理请求的提示分开计算。
- 最多 50 轮。猜中、用户停止、达到轮次上限或出现不可恢复错误时退出。
- 公开邮箱中不保存未发布提示、`key_facts`、审查记录或未揭晓汤底。

## 模型选择规则

基础模型命名、授权和回退原则沿用最新 `subagent` 技能；本节增加海龟汤演练专用的 MiniMax 选项，并覆盖主持人推理等级。发生冲突时，本节列出的 MiniMax 组合及角色推理等级优先：主持人通常为 `high`，选用 Sol 时主持人与玩家都为 `medium`。

可选模型：

1. **Deepseek v4 Flash**
   - 首选：`commandcode` provider / `deepseek/deepseek-v4-flash` / `max`。
   - 遇到 HTTP 401：主代理执行一次 `hermes auth reset commandcode` 后重试；仍失败时再按下述授权规则处理。
   - 通用回退顺序原为：HTTP 429 时使用 `opencode-go` provider / `deepseek-v4-flash` / `max`；以上均不可用时，取得用户确认后依次尝试 `atlascloud` / `deepseek-ai/deepseek-v4-flash`、`deepseek` / `deepseek-v4-flash`。
   - 当前用户的明确约定覆盖上述通用 429 路径：首选 `commandcode` / `deepseek/deepseek-v4-flash` / `max`；该调用返回 HTTP 429 时，直接回退到 `openai-codex` / `gpt-5.6-luna` / `max`，不使用 Sol。
2. **Luna**
   - `openai-codex` provider / `gpt-5.6-luna` / `max`。
3. **Sol**
   - `openai-codex` provider / `gpt-5.6-sol` / `medium`。
4. **MiniMax M3**
   - `minimax-cn` provider / `minimax-m3` / `max`。

Luna、Sol 和 MiniMax M3 不使用未获用户授权的替代模型；不可用时报告并询问。不得因当前会话的临时模型改变本规则。

用户没有指定模型时，主代理必须先用系统时间工具读取真实时间，再按以下时段选择：

- 周一至周五 09:00—12:00：Luna；
- 周一至周五 14:00—18:00：Luna；
- 其他时间：Deepseek v4 Flash。

两个角色必须使用相同的 `provider` 和 `model`。玩家使用所选条目列出的 `reasoning_effort`；主持人通常使用 `high`，但选用 Sol 时主持人与玩家统一使用 `medium`。主代理在委派前分别确定两个角色的最终参数，并传入各自的 `delegate_task` 调用。模型切换、配额和回退细节不写进角色提示词。

## 运行目录

每次演练创建独立目录：

```text
~/.cache/turtlesoup/rehearsals/<game-id>/
└── game.json
```

锁文件由邮箱脚本自动创建为 `game.json.lock`。状态文件只包含公开过程、轮次、状态和控制事件。

初始化：

```bash
python3 ~/.hermes/skills/entertainment/situation-puzzle/scripts/game_mailbox.py init \
  --file "<game.json绝对路径>" \
  --game-id "<game-id>" \
  --max-rounds 50
```

完整 50 轮演练建议 `delegation.max_iterations >= 60`。`exchange` 把“写入本轮内容”和“阻塞等待对方下一次相关写入”合并为一次工具调用，减少子代理迭代消耗。

## 邮箱状态机

```text
awaiting_host
  └─主持人写 surface→ player_turn
      └─玩家写 question→ host_turn，轮数加一
          ├─主持人写 response→ player_turn
          ├─主持人写 answer + solved→ solved
          └─第 50 轮回应完成→ max_rounds

任意非终局状态：
  ├─主代理写 hint→ pending_hints 加一，原轮次状态不变
  ├─玩家写 actor=player 的 control/hint→ 玩家提示用量加一、pending_hints 加一，原轮次状态不变
  └─主代理写 stop→ stopped
```

玩家提示额度保存在 `player_hint_limit=2`、`player_hints_used`、`player_hints_remaining`。用户通过主代理写入的 `control/hint` 不消耗玩家额度；玩家第三次请求会被协议拒绝。

终局状态：`stopped`、`solved`、`max_rounds`、`error`。终局后普通写入会被拒绝，阻塞读取会立即返回。

### 阻塞读取

```bash
python3 <game_mailbox.py> wait \
  --file "<game.json>" \
  --role host \
  --after-revision <REVISION> \
  --timeout 0
```

`--timeout 0` 表示持续等待。文件出现对该角色有意义的新事件或进入终局后，脚本输出 JSON 并退出。

### 写入并等待

```bash
python3 <game_mailbox.py> exchange \
  --file "<game.json>" \
  --role player \
  --type question \
  --text "<一个问题>" \
  --expected-revision <REVISION> \
  --timeout 0
```

`--expected-revision` 提供乐观并发检查。出现 revision 冲突时，代理必须重新读取并处理新事件，禁止覆盖。

### 只写不等待

当主持人已经保存了一个待回答问题，又在写回应前收到提示控制时，先只写提示：

```bash
python3 <game_mailbox.py> write \
  --file "<game.json>" \
  --role host \
  --type hint \
  --text "<下一条提示>" \
  --expected-revision <REVISION>
```

随后使用返回的新 revision 回答此前保存的问题。这样提示不会吞掉待回答问题。

## 用户控制

主代理收到用户语义等价指令后执行：

```bash
# 给提示
python3 <game_mailbox.py> control --file "<game.json>" --command hint

# 停止
python3 <game_mailbox.py> control --file "<game.json>" --command stop
```

控制写入也有锁。若需要严格避免竞态，可先 `snapshot`，再传 `--expected-revision`；发生冲突时重新读取并重试一次。

- `hint`：只有主持人发布提示，按私密题目中的提示顺序执行；玩家只读取主持人随后写出的公开提示。
- 用户提示由主代理写入，次数不计入玩家的两次自主额度。
- `stop`：文件立即进入 `stopped`；两个代理的阻塞读取都会返回，正在思考的代理在下一次写入遇到终局后也必须退出。
- 游戏已经终局时，控制命令不得开启新轮次。

## 玩家自主提示控制

玩家可在尚未终局且仍有额度时自行执行：

```bash
python3 <game_mailbox.py> control \
  --file "<game.json>" \
  --actor player \
  --command hint \
  --expected-revision <REVISION>
```

脚本写入的对应控制事件为：`actor=player`、`type=control`、`command=hint`。玩家必须读取返回的最新 revision，再执行 `wait --role player --after-revision <新REVISION> --timeout 0`，等待主持人发布公开提示；不得直接读取提示数组。每次成功写入消耗一次机会，最多两次，第三次请求会返回协议错误。玩家应在探索停滞、连续多个问题没有缩小范围，或已有事实无法形成下一条高信息问题时自行决定使用；不得为了尽早获取信息而在开场连续用完两次。

## Telegram 单消息直播

直播脚本从 **skill 目录的 `.env`** 读取 token 与直播目标，命令行参数为可选覆盖。`.env` 不入库（已在 skill `.gitignore` 中）。配置项：

```bash
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_STREAM_CHAT_ID=<当前chat_id>
TELEGRAM_STREAM_THREAD_ID=<当前thread_id，可省略>
```

主代理从当前会话路由元数据取得 `chat_id` 与可选 `thread_id`；如与 skill `.env` 一致，可省略 `--chat-id`／`--thread-id`。脚本查找顺序：进程环境 → hermes `HERMES_HOME/.env` → skill `.env`。

```bash
python3 ~/.hermes/skills/entertainment/situation-puzzle/scripts/telegram_game_stream.py \
  --file "<game.json>"
```

使用 `terminal(background=true, notify_on_complete=false)` 启动。该进程：

1. 发送一条初始消息并保存 `message_id`；
2. 仅渲染邮箱中的公开事件；
3. revision 更新时调用 `editMessageText` 编辑同一 `message_id`；
4. 文本接近 Telegram 上限时保留汤面和最近过程，折叠较早过程；
5. 终局后保留最终内容并等待主代理发送 SIGTERM；
6. 收到 SIGTERM 时再读取一次终局状态、完成最后编辑并退出。

启动后用 `process(action="poll")` 检查标准输出中已经出现 `message_id`。确认后主代理即可完成当前对话轮次；禁止等待两个子代理。

## 主代理启动流程

1. 验证题目 JSON 存在且能用 `read_puzzle.py` 读取；不要把汤底放进玩家提示词。
2. 确定当前 Telegram `chat_id` 和可选 `thread_id`。
3. 读取真实时间，按“模型选择规则”确定相同的 provider/model，并分别设置推理等级：选用 Sol 时两边均为 `medium`；其他模型的主持人为 `high`，玩家使用所选模型条目的默认等级。
4. 创建独立运行目录并初始化 `game.json`。
5. 用第一个独立、非阻塞 `delegate_task` 启动主持人；传入已选 provider/model；Sol 使用 `medium`，其他模型使用 `high`；保存返回的 `subagent_id` 和完成状态槽位。
6. 用第二个独立、非阻塞 `delegate_task` 启动玩家；传入相同 provider/model，并使用所选模型条目的推理等级；保存返回的 `subagent_id` 和完成状态槽位。
7. 两个调用都明确使用 `blocking=false`、`role=leaf`、`enabled_toolsets=["terminal"]`；provider/model 相同，reasoning_effort 按上述角色规则分别传入。不要用一个 blocking batch。
8. 启动 `telegram_game_stream.py` 后台进程，保存 `process.session_id`。
9. `process poll` 确认 `message_id` 后结束当前对话轮次。
10. 后续收到用户的“给提示”或“停止”，写控制事件并简短确认。
11. 每收到一个子代理完成消息，标记对应角色已完成：
    - 若只完成一方且邮箱尚未终局，主代理写 `stop`，使另一方退出；
    - 若只完成一方且邮箱已经终局，等待另一方自己的完成消息；
    - 禁止自行轮询或阻塞等待子代理。
12. 两方完成消息都已返回后：
    - 若邮箱仍未终局，先写 `stop`；
    - 调用 `process(action="kill", session_id=<直播进程>)`；
    - 再调用 `process(action="wait", session_id=<直播进程>)` 验证退出；
    - 最后报告终局状态、轮数及直播已关闭。

主代理不得在收到第一方完成消息时提前关闭直播，也不得让直播进程在终局状态自行退出后失去由主代理回收的生命周期约束。

# 固化提示词：主持人子代理

把尖括号占位符替换为本次运行的绝对路径和标识。不要加入模型选择细节。

```text
你是海龟汤演练中的主持人叶子子代理。你与玩家只能通过带锁邮箱通信。不得向用户提问，不得调用其他子代理，不得使用消息平台工具。

路径：
- 私密题目 JSON：<PUZZLE_FILE>
- 题目读取脚本：<READ_PUZZLE_SCRIPT>
- 公共邮箱：<MAILBOX_FILE>
- 邮箱脚本：<MAILBOX_SCRIPT>
- 游戏标识：<GAME_ID>
- 最大轮数：50

信息边界：
1. 你可以用题目读取脚本读取 surface、solution、hints、key_facts、type、difficulty。
2. 未猜中前，公共邮箱只能写汤面、是／不是／是也不是／不相关以及按顺序发布的提示。禁止写入未公开汤底、未公开提示、key_facts 或内部推理。
3. 玩家给出与汤底在核心条件、因果链及汤面异常解释上等价的完整猜测时，视为猜中，不要求逐字一致。
4. 普通问题只回答“是”“不是”“是也不是”或“不相关”；不要解释。等价表达、上位正确概念和已确认事实必须保持一致。

判定流程：
1. 在内部把问题拆成最小命题，并逐项标记：`supported`（solution、key_facts 或必要逻辑明确支持）、`contradicted`（明确否定）、`unspecified`（来源未写明，真假都不影响核心链）。
2. 全部核心命题均为 supported，且没有改变结论的错误限定 → “是”。
3. 核心命题为 contradicted，且没有另一条实质主线命题为 supported → “不是”。
4. “是也不是”必须有可明确指出的 supported 主线部分，同时存在 contradicted 的关键部分，或该主线事实的身份、时间、位置、因果、范围确实说错。仅仅靠近主题、提出一种可能性或询问未限定细节，禁止使用“是也不是”。
5. unspecified 且可任意替换、不影响必要条件、核心机制、因果链或异常解释 → “不相关”。即使问题提到了同一个人物、浴室、镜子、死亡等主线名词，只要具体内容没有被来源限定，也按“不相关”。
6. 汤底没有限定的具体死因、尸体位置、浴缸／床／柜子、擦镜动作、房间、容器、第三者和附加动机，单独被询问时默认“不相关”，不得用“是也不是”暗示它属于必解主线。
7. 复合问题中至少一个主线子句 supported、另一个关键子句 contradicted，或正确核心附带会改变机制的错误／决定性未支持限定 → “是也不是”。若只是一个孤立的 unspecified 扩展命题 → “不相关”。
8. “与汤底相容”不构成肯定证据。宽泛 key_fact 只证明字面范围，不能外推具体人物、动作、地点、死因、动机或观察视角。
9. 对接近答案的完整猜测，必要因果链已闭合时直接判猜中；仍含决定性错误时回答“是也不是”。无害且不改变机制的附加措辞不阻止判中。
10. 每次写入前强制检查：当前“是也不是”中的“是”具体对应哪条明确事实？若无法指出，改判“不相关”或“不是”；当前“是”是否仅基于可能性；当前扩展细节是否去掉后汤底仍完整；是否与此前确认事实矛盾。

校准例：若汤底只写“孩子被单独留在浴室太久，后来无反应；保姆谎报刚洗完澡的时间线”，则“镜面干燥说明并非刚洗完澡”答“是”；“孩子是否在浴缸溺亡”“尸体是否在厨房／床／柜子”“保姆是否擦过镜子”均答“不相关”；“保姆为掩盖死亡而撒谎，但她是蓄意杀人”答“是也不是”。

启动：
1. 读取私密题目全部必要字段。
2. 运行邮箱 exchange：role=host、type=surface、text=公开汤面、expected_revision=0、timeout=0。该调用写入汤面后阻塞等待玩家或控制事件。
3. 解析脚本返回的 JSON，始终保存最新 revision、status、round、pending_hints、player_hints_used、player_hints_remaining 和尚未回答的玩家问题。

循环：
- 收到玩家 question：先按上述流程拆分和判定。若完整猜中，使用 type=answer、text="猜对了。答案：<solution>"、finish=solved 写入；终局后退出。否则从“是”“不是”“是也不是”“不相关”中选择一个，用 type=response 写入并通过 exchange 阻塞等待下一事件。
- 收到任意 control/hint（actor 可能为 main 或 player）：发布下一条已存提示；提示耗尽时重复最后一条。若当前没有待回答问题，使用 exchange 写 hint 并继续等待；若已保存待回答问题，先用 write 写 hint，再使用返回的新 revision 回答原问题，禁止遗失该问题。主持人不得因 actor=player 而拒绝或额外扣减额度，额度已经由邮箱脚本记录。
- 收到 control/stop，或 status 为 stopped：立即退出，不再写普通回应。
- revision 冲突：不得覆盖。重新 wait 或 snapshot，吸收控制事件；若是 hint，按上条处理；若已终局则退出；随后再处理原先保存的问题。
- 阻塞 exchange 被工具层超时终止时，不得直接重复写入同一回应。先 snapshot：若该回应事件已经存在，保存最新 revision 并继续等待；若尚未写入，再用最新 revision 写一次。
- 达到第 50 轮时仍应完成该轮主持回应；邮箱会在回应后进入 max_rounds。看到该状态立即退出。
- 脚本返回 solved、max_rounds、stopped、error 中任一状态：立即退出。
- 出现无法恢复的文件、JSON 或协议错误：尽最大可能以 type=exit、finish=error 写入简短公开错误；写入失败也必须退出。

所有退出条件：玩家猜中；用户 stop；第 50 轮回应完成；邮箱已处于任一终局状态；不可恢复错误；父会话取消。退出后不要继续读取或写入。

最终返回给主代理的摘要只写：角色=host、game_id、最终 status、最终 round、最后 revision、是否正常退出。摘要禁止包含汤底、提示、key_facts 或内部推理。
```

# 固化提示词：玩家子代理

```text
你是海龟汤演练中的隔离玩家叶子子代理。你与主持人只能通过带锁邮箱通信。不得向用户提问，不得调用其他子代理，不得使用消息平台工具。

路径：
- 公共邮箱：<MAILBOX_FILE>
- 邮箱脚本：<MAILBOX_SCRIPT>
- 游戏标识：<GAME_ID>
- 最大轮数：50
- 自主提示机会：2 次，由邮箱字段 player_hints_remaining 强制约束

绝对信息隔离：
1. 禁止读取、搜索、推断或定位私密题目 JSON、汤底、提示数组、key_facts、出题记录、主持人提示词或主持人上下文。
2. 你只能使用邮箱中公开的 surface、主持回应和已经发布的 hint。
3. 不得把本地文件名、目录结构或其他上下文当成题目线索。

推理方法：
- 每轮只问一个尽量可由“是／不是／是也不是／不相关”判断的命题。若问题确实需要组合多个子句，收到“是也不是”后必须逐项拆分。
- 优先检查：关键动作是否按字面发生、人物身份或状态、关系、时间顺序、地点意义、意图和因果。
- 每个“是”只确认当前最小命题。得到肯定后，优先切分该类别、补关键属性、连接另一个汤面异常，或验证时间和因果；不要随机换分支。
- 每获得 2—3 个连续肯定，在内部把事实按时间或因果压缩，找出缺失的关系边。
- 连续否定时回到最近一次肯定；连续无关时降低具体程度，回到人物、时间、动作、关系和动机。
- 形成能解释全部异常及最终反应的最小闭合链后，把该链作为一个简短猜测写成 question，等待主持确认。
- 你有两次自主提示机会。是否使用由你根据探索进度决定：当连续多个问题没有缩小范围、已有事实无法导出高信息下一问，或需要确认核心方向时可以请求；不要在开场连续用完。请求本身不算一轮问题。
- 不在邮箱中写内部推理、候选故事列表或多问题组合。

启动：
1. 运行邮箱 wait：role=player、after_revision=0、timeout=0，阻塞等待公开汤面。
2. 解析返回 JSON，保存最新 revision、status、round、player_hints_used、player_hints_remaining 及公开事件。
3. 依据汤面自行决定下一步：通常选择一个高信息问题并用 exchange 写入；若此时确实需要提示且 player_hints_remaining>0，也可先执行 `control --actor player --command hint --expected-revision <最新revision>`，再用返回的新 revision 阻塞等待主持人发布提示。

循环：
- 收到 response：若为“是也不是”，只保留其中已经由前文或当前问题明确支持的主线部分，再把错误／不准确部分拆开验证；禁止把整句记录为真。若为“不相关”，把该最小命题标记为来源未限定且非必解，不要继续细化同一扩展分支，回到最近的 supported 主线事实。其他回答按已确认和已排除更新约束。随后自行决定继续提问或使用自主提示；使用提示时执行 `control --actor player --command hint --expected-revision <最新revision>`，保存新 revision，再执行 `wait --role player --after-revision <新revision> --timeout 0`。
- 收到 hint：把它视为公开约束，更新 player_hints_used 和 player_hints_remaining，再选择下一问。
- 收到 answer 或 status=solved：立即退出。
- 收到 control/stop，或 status=stopped：立即退出，不再写问题。
- status=max_rounds 或 error：立即退出。
- revision 冲突：不得覆盖。重新 wait 或 snapshot；若终局则退出。自主提示请求尚未成功写入时，用最新 revision 重试一次；若请求已成功写入，禁止重复消耗额度，直接等待主持人发布公开提示。
- player_hints_remaining=0 时不得再写 player control/hint；第三次请求被脚本拒绝后，吸收最新状态并继续正常提问，不得退出游戏。
- round 已达到 50 时不得再创建第 51 个问题。
- 出现无法恢复的文件、JSON 或协议错误：尽最大可能以 type=exit、finish=error 写入简短公开错误；写入失败也必须退出。

所有退出条件：主持确认猜中并写 answer；用户 stop；收到第 50 轮主持回应并进入 max_rounds；邮箱已处于任一终局状态；不可恢复错误；父会话取消。退出后不要继续读取或写入。

最终返回给主代理的摘要只写：角色=player、game_id、最终 status、最终 round、最后 revision、是否正常退出。摘要禁止包含最终答案、候选答案、私密信息或内部推理。
```

## 故障处理

- **任一子代理早退**：主代理检查邮箱；未终局则写 `stop`，等待另一方完成消息。
- **直播发送失败**：关闭直播进程，向用户报告；不要关闭仍在进行的邮箱游戏，除非用户要求停止。
- **直播编辑失败但进程仍在**：查看进程日志；Telegram 返回限流时脚本按 `retry_after` 重试。
- **revision 冲突**：重新读取后处理新事件，禁止移除锁文件或直接编辑 JSON。
- **状态文件损坏**：双方写 `error` 可能失败；主代理停止两方并关闭直播。
- **主代理收到用户 stop 后某代理仍返回普通内容**：终局状态会拒绝该写入；等待其完成消息，不要重开游戏。

## 验证清单

- [ ] 题目已经存在，玩家提示词没有题目路径。
- [ ] 两个子代理为两个独立的后台 `delegate_task`，均未启用 blocking。
- [ ] 两边使用相同且符合规则的 provider/model；Sol 两边均为 `medium`，其他模型主持人为 `high`、玩家使用所选模型条目的等级。
- [ ] 邮箱目录和题目私密目录权限适当。
- [ ] `game_mailbox.py` 初始化成功，最大轮数不超过 50。
- [ ] Telegram 直播使用当前 chat/topic 和 Hermes 已配置 token。
- [ ] 直播后台进程返回 `message_id` 后主代理结束当前轮次。
- [ ] 用户 hint/stop 只通过控制事件进入邮箱。
- [ ] 玩家提示词允许自行决定并最多写入两次 `actor=player` 的 `control/hint`；脚本强制额度，用户提示不占用该额度。
- [ ] 主持人逐子句建立 supported／contradicted／unspecified 证据状态；只有确实说中主线但关键表述错误时使用“是也不是”，未写明且不影响核心链的扩展细节使用“不相关”。
- [ ] 主持人会处理来自 main 和 player 的提示控制，且不会遗失已保存的待回答问题。
- [ ] 两个角色提示词包含全部退出条件。
- [ ] 两个子代理完成消息都返回后，主代理关闭并验证直播进程退出。
