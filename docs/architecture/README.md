# OmniEvolve 架构图

> 交互式 HTML 架构图，支持暗/亮主题切换、语义聚焦、PNG/SVG 导出。
> 用浏览器打开即可浏览。

## 图表清单

| 图表 | 类型 | 文件 | 说明 |
|------|------|------|------|
| **系统总览** | Architecture | [system-overview.html](system-overview.html) | 全局模块关系：Engine / Agents / Storage / Sandbox / Meta 的数据流和控制流 |
| **Fast Loop** | Data Flow | [fast-loop.html](fast-loop.html) | 单候选 11 步进化流水线：Router → MCTS → Director → Coder → Critic → Sandbox → Commit |
| **Slow Loop** | Data Flow | [slow-loop.html](slow-loop.html) | 策略窗口评估与受控元进化：Telemetry → Health → MetaPlanner → Governance → Champion/Challenger |
| **存储架构** | Architecture | [storage.html](storage.html) | 持久化层：SQLite + CAS Artifact + Vector (HNSW) + Graph + Git Code Store |

## 查看方式

```bash
# 直接用浏览器打开
xdg-open docs/architecture/system-overview.html

# 或启动一个本地服务器
python -m http.server 8000 --directory docs/architecture
# 然后访问 http://localhost:8000
```

## 交互功能

- **主题切换**：右上角按钮切换暗/亮主题（自动记忆）
- **语义聚焦**：点击节点查看依赖关系和调用路径
- **导出**：导出菜单支持 PNG / JPEG / WebP / SVG
- **搜索**：按 `/` 搜索任意节点
- **路线探测**：按 `R` 追踪两个节点之间的路径
- **Story 模式**：按 `P` 播放引导式阅读序列（如有定义）

## JSON 源文件

每个 HTML 旁边有对应的 `.json` 源文件，可用 archify 工具链重新渲染：

```bash
cd ~/.qwen/skills/archify
node bin/archify.mjs render architecture <input>.json <output>.html
node bin/archify.mjs render dataflow <input>.json <output>.html
```
