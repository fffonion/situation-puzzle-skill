# 完整题库索引

## 文件

- 题库：`references/MASTER_all_puzzles.json`
- 来源快照：`/mnt/TEMP/haitotang/puzzles_raw/MASTER_all_puzzles.json`
- 收录：21 期，共 324 题
- 字节数：411014
- SHA-256：`85ae80a53cc32254abadbaf9e11385d6d47edbeb0901eee0ef68133370a0ddd3`

## 结构

根节点是期数数组；每期包含 `episode`、`type_theme`、`puzzles`。每道题通常包含：

- `type`
- `difficulty`
- `surface`
- `solution`
- `hints`
- `key_facts`
- `question_trace`
- `source_episode`

## 使用边界

- 创作新题前，读取并检查全部 324 题的汤面、汤底和抽象因果骨架。
- 相似性比较关注核心条件、揭晓依赖、信息顺序和关键词重释，不能只比较字面。
- 该文件包含私密汤底、提示和判定表，不得在玩家上下文中加载或引用。
- 主持单题时继续使用该题自己的私密 JSON；完整题库仅用于原创比对、作者侧审查和题库研究。
- 更新快照时重新统计期数与题数，并核对 JSON、字节数和 SHA-256。
