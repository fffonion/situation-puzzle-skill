---
name: situation-puzzle
description: "用于中文海龟汤的原创出题、主持、猜题、隔离盲测及主持人／玩家双子代理直播演练。浓汤、荒诞汤或已有题目自动对局需求出现时使用。"
version: 2.8.1
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [game, puzzle, chinese, 海龟汤, situation-puzzle, role-based, entertainment]
---

# 海龟汤 / 情景解谜

## 安装私密题库

题库不存放在 Git 历史中。加密 ZIP 位于 GitHub Release `puzzle-library-v1`：

```bash
bash scripts/install-puzzle-library.sh
```

ZIP 密码：`123456`

本技能是三个信息隔离角色的总入口。三个角色共享一个私密 JSON 题目文件，但允许读取的信息不同。

## 意图识别

- `出题` / `出一道海龟汤` / `浓汤类型` / `荒诞类型` → **出题者**
- `主持` / `是、不是、不相关` / 用户提供题目路径 → **主持人**
- `你来猜` / `当玩家` / `盲测` / `一起猜` → **玩家**
- `出题然后主持` / `出题给我猜` → 先运行**出题者**完成私密存储，再顺序切换为**主持人**，只展示汤面
- `子代理演练` / `主持人和玩家自动对局` / `直播盲测` → 加载 `references/subagent-rehearsal.md`，使用两个隔离的后台子代理
- `模型跑分` / `玩家模型 benchmark` / `比较模型推理能力` → 加载 `references/model-benchmark.md`，使用固定题组、Luna high 主持人和 blocking 双代理对局

创作请求未指定类型时，先让用户选择 `浓汤类型` 或 `荒诞类型`。

## 角色 reference

只加载当前角色对应的文件：

- **出题者** → `references/creator.md`
- **主持人** → `references/host.md`
- **玩家** → `references/player.md`
- **双子代理演练编排** → `references/subagent-rehearsal.md`
- **固定题组模型跑分** → `references/model-benchmark.md`
- **完整原创比对题库** → 本地 `references/MASTER_all_puzzles.json`（首次使用前按 `references/puzzle-library.md` 从 Release 安装；仅出题者／作者侧加载）

加载方式：

`skill_view(name="situation-puzzle", file_path="references/<role>.md")`

出题者和主持人都可以知道汤底，因此允许按顺序切换。玩家必须保持信息隔离：凡是已经读取汤底、私密 JSON、出题审查记录或 `key_facts` 的上下文，都不能提供真正盲测结论。

扮演玩家时不得加载出题者或主持人 reference。作者侧模拟不得称为盲测。

## 共享数据格式

私密文件位于 `~/.cache/turtlesoup/`：

```json
{
  "type": "浓汤类型" | "荒诞类型",
  "surface": "<公开汤面>",
  "solution": "<私密汤底>",
  "hints": ["<按题型配置、由浅入深的提示>"],
  "key_facts": ["<语义判定表，格式：yes/no/irrelevant::陈述>"],
  "difficulty": "简单" | "中等" | "困难"
}
```

`solution`、未发布的 `hints`、`key_facts`、评分和出题审查记录均属私密信息，不得向玩家暴露。

## 配套脚本

- `scripts/save_puzzle.py`：写入审查完成的题目 JSON，并输出绝对路径
- `scripts/read_puzzle.py`：读取单个字段，支持 `surface`、`solution`、`hint`、`key_facts`、`difficulty`、`type`；列表字段可配合 `--index N`
- `scripts/game_mailbox.py`：以文件锁、revision 和原子替换实现双代理阻塞通信、轮次状态机、用户控制及玩家两次自主提示额度
- `scripts/telegram_game_stream.py`：读取公开邮箱并编辑当前 Telegram 会话中的同一条直播消息

所有相对路径基于：

`/home/wow/.hermes/skills/entertainment/situation-puzzle/`

脚本缺失时先恢复脚本。出题者不得跳过私密存储步骤。

## 角色切换规则

- 出题者 → 主持人：保存成功后允许；主持人只用 `汤面：{surface}` 开场。
- 出题者 → 玩家：同一已知情上下文中禁止。
- 主持人 → 玩家：当前上下文读过汤底时禁止。
- 玩家 → 出题者或主持人：先结束盲测；切换后的工作不再属于盲测。

## 总体验证清单

- [ ] 已识别用户意图和角色。
- [ ] 只加载需要的角色 reference；明确要求出题后主持时允许顺序加载出题者与主持人。
- [ ] 出题者使用本地安装的 `references/MASTER_all_puzzles.json` 完成 324 题原创性比对；完整题库不得进入玩家上下文。
- [ ] 出题者执行 `references/creator.md` 中的量化方法论。
- [ ] 出题者区分作者侧对抗审查与真正盲测。
- [ ] 出题者运行配套脚本并取得真实文件路径。
- [ ] 主持人只公开汤面、四类判断（是／不是／是也不是／不相关）、已发布提示或用户索要的答案。
- [ ] 主持人先拆分复合命题并建立 supported／contradicted／unspecified 证据状态；只有确实说中主线但关键表述错误时使用“是也不是”，未写明且不影响核心链的扩展内容使用“不相关”。
- [ ] 主持人对同义及上位正确概念保持一致判断。
- [ ] 玩家从未访问私密信息。
- [ ] 玩家在核心条件、时间、机制与最终反应基本闭合后主动提交完整因果链；同一语义区域连续两次“是也不是”时停止同义改写，第 35／45 轮执行收敛检查。
- [ ] 真盲测声明有隔离玩家记录支持。
- [ ] 双子代理演练使用两个独立的非 blocking 委派；后台直播只在两个完成消息均返回后由主代理关闭。
- [ ] 模型跑分使用 `fixed-v1` 固定题组、Luna high 主持人、blocking 双代理 batch，不启动直播，并按六个类型／难度分层宏平均。
