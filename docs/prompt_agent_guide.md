# Prompt 与 Agent 开发指南

S5-16: Prompt 与 Agent 开发指南

## Agent 架构

OmniEvolve 使用三角色 Agent 架构 + Meta Agent：

```
Director → 进化思想（"应该尝试什么方向"）
   ↓
Coder → 生成代码（"将思想实现为代码"）
   ↓
Critic → 静态审查（"代码是否有明显问题"）
   ↓
（通过 → 存储 + 评估 | 不通过 → 回到 Coder 重试）
```

## AgentContext 字段

Agent 通过 `AgentContext` 接收上下文：

| 字段 | 类型 | 说明 |
|------|------|------|
| `experiment_id` | str | 实验 ID |
| `task_id` | str | 任务 ID |
| `generation` | int | 当前代数 |
| `island_id` | str \| None | 岛屿 ID |
| `parent_candidate_ids` | list[str] | 父代候选 ID |
| `parent_thoughts` | list[str] | 父代思想摘要 |
| `parent_artifact_hashes` | list[str] | 父代代码哈希 |
| `inspiration_programs` | list[dict] | 启发程序（高分+随机） |
| `memory_hits` | list[dict] | 检索到的分层记忆 |
| `domain_hints` | list[str] | 领域插件提示 |
| `meta_scratchpad` | str | 全局洞察（失败方向等） |
| `search_policy_id` | str | 当前 Champion Policy ID |
| `prompt_version_id` | str | 当前 Champion Prompt 版本 |
| `model` | str | 路由器分配的模型 |

## Prompt 版本化

Prompt 通过 `PromptVersionRepository` 版本化存储：

```python
from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository

prompt_repo = PromptVersionRepository(db)

# 创建并晋升
pv = prompt_repo.create("director", "You are an expert...", artifact_store=store)
prompt_repo.promote(pv.id)

# 获取当前 champion
champion = prompt_repo.get_latest("director", "champion")
```

**版本生命周期：** `challenger` → `champion`（晋升）/ `rejected` / `retired`（被新 champion 替换）

## 实现自定义 Agent

实现 Protocol 接口即可：

```python
from omnievolve.agents.base import AgentContext, ThoughtOutput, CodeOutput

class MyDirector:
    def evolve_thought(self, ctx: AgentContext) -> ThoughtOutput:
        # 访问 ctx.parent_thoughts, ctx.memory_hits, ctx.inspiration_programs
        # 调用 LLM 生成新思想
        return ThoughtOutput(
            thought="...",
            rationale="...",
            confidence=0.8,
            mechanism_tags=["algorithm_change"],
        )
```

## 结构化输出与修复

Agent 的 LLM 响应应返回 JSON。当 JSON 解析失败时，框架执行三级修复：

1. **直接 JSON 解析**（正常路径）
2. **代码块提取**（从 ` ```python ... ``` ` 中提取）
3. **字段提取**（从不完整 JSON 中提取 `"full_code"` 字段）
4. **裸代码回退**（将整个响应作为代码）

## Retry / Backoff / Fallback

`LLMGateway` 支持自动重试：

```python
gateway = LLMGateway(
    db=db,
    default_model="gpt-4o",
    max_retries=3,           # 每个模型最多重试 3 次
    retry_backoff_base=1.0,  # 指数退避基数
    fallback_model="gpt-4o-mini",  # 主模型耗尽后切换
)
```

重试策略：指数退避（1s, 2s, 4s），全部失败后切换到 fallback 模型。

## 角色条件化路由

模型路由按角色分离奖励：

| 角色 | 奖励组成 |
|------|----------|
| Director | thought_adoption (0.4) + mechanism_novelty (0.3) + frontier_contribution (0.3) |
| Coder | patch_applied (0.2) + compile_success (0.2) + test_pass_rate (0.3) + performance_gain (0.3) |
| Critic | defect_recall (0.5) - false_rejection_rate (0.3) + evaluator_cost_saved (0.2) |

路由算法：Sliding-window UCB（默认）/ Discounted UCB / Thompson Sampling

## Meta-Scratchpad

跨代累积全局洞察，注入 AgentContext 供 Director 参考：

- 失败方向追踪：score < 0.1 的思想关键词被记录
- 注入到 `ctx.meta_scratchpad`，Director 可参考避免重复探索
- 保留最近 5 条失败方向（FIFO）

## Inspiration Programs

每次进化候选时，引擎收集两类启发程序（排除直接父代）：

- **Top-K 高分候选**（exploitation）：提供成功模式的上下文
- **Random-K 随机样本**（exploration）：提供多样化视角

这是 ShinkaEvolve 和 AlphaEvolve 的核心模式之一。
