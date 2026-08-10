# 销售回复评测

评测程序批量调用正式 `SalesGraphService`，取得系统回复后供人工与销售回复进行盲评比较。

## 与正式环境的关系

以下内容与正式服务共用：`.env`、模型与回退顺序、单轮超时、提示词、记忆更新和销售图流程。

评测仅省略前端、WebSocket、会话/消息/模型调用记录落库和定时跟进；每一行在进程内模拟一个独立新会话，因此不会写入业务会话数据库。知识、SOP、风控规则和销售案例只读取评测快照，不读取正式数据库或 `data/` 下的正式知识文件。`EVALUATION_MAX_CONCURRENCY` 只控制批量任务同时启动的数量，用于匹配 API 频率限制和电脑性能，不改变单轮处理逻辑。

## 评测知识快照

评测只读取以下固定快照；文件名与正式私有源一致，但目录独立。修改这些文件只影响之后的评测，不影响正式服务；修改正式 `data/` 中的知识也不会改变已复制的评测快照：

```text
evaluation/knowledge_snapshot/identity.md          公司与销售身份说明（Markdown）
evaluation/knowledge_snapshot/skus.csv             SKU
evaluation/knowledge_snapshot/sop.csv              SOP
evaluation/knowledge_snapshot/faq.csv              FAQ
evaluation/knowledge_snapshot/safety_rules.csv     风控规则
evaluation/knowledge_snapshot/sales_cases.csv      RAG 销售案例
```

`sales_cases.csv` 每行包含 `case_id`、`customer_message`、`sales_reply`、`context_before`、`quality_score`、`tags`。开启 `SALES_RAG_ENABLED=true` 或 `SAFETY_VECTOR_ENABLED=true` 后，评测使用当前 `.env` 的 Embedding 配置在内存中为快照建立临时向量缓存；不写入 PostgreSQL。

## 输入 CSV

后续正式评测 CSV 的前四列必须依次为：

```csv
来源,用户消息,销售回复,上文记忆
```

`销售回复` 中的换行表示多条销售消息。每一行独立运行，第四列原样注入正式服务的 `history_summary`；真人回复不会传给模型。

运行：

```powershell
.\.venv\Scripts\python.exe evaluation\run.py --input-csv evaluation\private_datasets\你的评测对话.csv
```

并发数只在 `.env` 中修改：

```dotenv
EVALUATION_MAX_CONCURRENCY=3
```

## 运行输出与盲评

一次运行会在 `evaluation/results/<run_id>/` 生成：

- `系统回复结果.csv`：保留原始 CSV 全部列，并将 `系统销售回复` 插入为第五列；多条消息以单元格内换行保存。
- `技术运行明细.csv`：工程状态、耗时、转人工与错误摘要。
- `盲评表.csv`：只展示用户消息、记忆和随机顺序的候选甲/候选乙回复，供评审填写 0 或 1。
- `盲评映射.csv`：候选甲/候选乙对应真人或系统的内部映射，**不得提供给评审人**。

盲评表为每个候选回复提供五列：信息准确 A、不违规 C、解决问题 R、意向推进 P、用户反馈 F。评审完成后：

当前四列输入没有“下一句客户真实反馈”，因此 `用户反馈 F` 由评审人根据本轮上下文判断该回复是否有助于获得正向反馈；它不是实际转化或满意度统计。若未来需要按真实反馈评分，应另行补充经脱敏的结果字段并重新约定评分口径。

```powershell
.\.venv\Scripts\python.exe evaluation\tools\score.py --run-dir evaluation\results\<run_id> --review-file evaluation\results\<run_id>\盲评表.csv
```

评分程序用内部映射分别汇总真人销售和系统销售：

\[
S=\frac{1}{N}\sum_{i=1}^{N}(30R_i+30P_i+40F_i)A_iC_i
\]

输出 `评分明细.csv` 和 `评估报告.csv`；报告固定先展示业务总分、五项通过率和系统与真人的对比结论，再展示核心技术工程状态。所有正式对话与盲评文件均在 Git 忽略目录中保存。
