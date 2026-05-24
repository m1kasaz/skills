---
name: repo-to-resume
description: 将代码仓库转化为适合简历和面试表达的项目产出，包括一句话项目定位、2 到 4 条简历要点、系统架构与模块概览、核心执行流程以及代码证据。支持分析本地仓库，也支持直接分析 GitHub repo（URL 或 owner/repo），适用于用户希望把仓库总结为简历内容、面试项目介绍或项目产出，而不是单纯解释代码实现的场景。
---

# Repo to Resume

> **何时使用**: 当用户不是想知道“代码怎么写”，而是想把一个项目仓库转成 **简历可写内容 / 面试可讲项目介绍 / 项目产出总结** 时使用。

这个 skill 的目标不是做普通 code walkthrough，而是把 repo 中能被代码证明的系统能力，翻译成适合招聘语境的输出。

它既适用于**当前本地仓库**，也适用于**未拉到本地的 GitHub 仓库**。对于 GitHub repo，可以基于仓库 URL、`owner/repo`、README、目录结构、关键源码文件、Actions/配置文件等做证据化提炼，而不要求一定先 clone 到本地。

## Hard Rules

1. **不编造数据**
   - 不要虚构 QPS、DAU、可用性、性能指标、成本收益。
   - 如果仓库里没有明确数据，只能写定性表述。
   - 可以优先使用仓库中**可直接验证的量化事实**，例如支持的渠道数、Provider 数、入口类型数、关键模块数、接口数、核心流程数等。
   - 但不要为了“看起来高级”强行量化；没有可靠证据时宁可不写数字。

2. **不夸大 ownership**
   - repo 只证明“系统做了什么”，不自动证明“用户亲自主导了什么”。
   - 除非用户明确说明，否则用“参与建设 / 参与维护 / 围绕…实现”这类更稳妥表述。

3. **所有关键结论必须有代码证据**
   - 至少给出 entrypoint、主要 API 面、3~5 个核心 proof files。
   - 对重要结论标注 file path；必要时加函数名。

4. **区分事实和推断**
   - 代码直接证明的内容可以直接写。
   - 推断性的内容要写成 “可以概括为 / 更适合包装成 / likely / inferred”。

5. **优先提炼工程复杂性，而不是内部名词**
   - 不要只复述模块名。
   - 要把模块翻译成更通用的工程语言，例如：
     - canvas mode -> 可视化工作流编排
     - connector mode -> 外部事件/触发器接入层
     - apaas mode -> DSL 驱动的运行时引擎

## Recommended Workflow

### 先判断分析来源：本地 repo 还是 GitHub repo
在开始前先判断用户给的是：
- 当前工作区 / 本地仓库
- GitHub URL
- `owner/repo` 形式的 GitHub 仓库标识

对于 **GitHub repo**：
- 不要求先 clone 到本地
- 优先使用可直接获取的远程证据：README、仓库文件树、关键源码文件、`package.json` / `pyproject.toml` / `go.mod` / `Dockerfile` / `.github/workflows/*` / `cmd/*` / `src/*` / `app/*` / `server/*` 等
- 如果能直接通过远程读取拿到足够证据，就不要为了完成任务而强制要求本地拉仓
- 只有在远程证据明显不足、且用户希望继续深挖时，才建议 clone 或让用户提供更多路径/文件

### 推荐工具策略

#### 本地 repo
- 已知文件优先直接读文件
- 搜入口、模块、引用关系时，优先做轻量搜索
- 需要落盘时，默认写到 `docs/repo-to-resume/`
- 目标是“少量高价值证据”，不是把本地代码全部走读一遍

#### GitHub repo
- 如果用户给的是 GitHub URL 或 `owner/repo`，优先用 **GitHub CLI / 远程文件读取** 做分析
- 对 GitHub 相关内容，优先使用 `gh` 获取仓库信息、默认分支、README、目录树、关键文件内容；不要默认要求 clone
- 如果仓库可能是私有的或需要认证，优先走已认证的 GitHub 访问方式，不要依赖匿名网页抓取
- 远程分析时，优先拿这些证据：默认分支 README、入口文件、依赖声明文件、CI/workflow、部署配置、核心目录下 3~5 个关键文件
- 只有当核心流程无法从远程证据中建立，才建议用户 clone、贴文件、或授权进一步读取

#### 证据策略
- 证据优先级：源码文件 > 配置/注册文件 > README / 文档 > issue / PR 描述
- 对 GitHub repo，能引用具体文件路径时，不要只引用仓库首页
- 如果结论主要来自 README 而不是源码，要明确这是“文档证据”，不要伪装成“代码直接证明”

### Step 1: 找服务入口和初始化路径
先确认 repo 的启动方式与系统边界：
- entrypoint（如 `main.go`, `cmd/*`, `server/*`）
- 初始化哪些 client / runtime / consumer / scheduler
- 是否是长生命周期服务、CLI、库、前端应用或混合系统

### Step 2: 找主要 API / 模块边界
定位：
- 统一 handler / controller / route 注册文件
- 核心业务目录
- 异步入口（consumer / queue / cron / worker）
- 可观测性或外部系统接入点

输出时不要只列目录，要回答：
- 这个系统主要服务什么问题？
- 模块之间是如何分工的？

### Step 3: 找 3~5 条最能体现系统价值的核心流程
优先寻找：
- 模板 / 配置 -> 运行时实例化
- 请求 / 事件 -> 核心业务执行
- 异步消息消费 -> 状态推进
- 调度 / 重试 / 触发器 / 回调
- 指标埋点 / 审批 / 缓存 / 外部 RPC / 数据持久化

每条流程尽量回答：
1. 输入是什么？
2. 中间经过哪些关键层？
3. 输出或副作用是什么？
4. 这条流程为什么能体现工程复杂性？

### Step 4: 找可包装成“能力”的技术点
把 repo 事实翻译成招聘语言，例如：
- workflow orchestration
- event-driven execution
- DSL/runtime engine
- trigger integration
- transactional persistence
- observability / metrics / tracing
- rule engine / decision system
- platform abstraction / extensibility

### Step 5: 生成面向招聘场景的输出
默认输出以下内容：
1. 一句话项目定位
2. 2~4 条简历 bullets
3. 系统 / 模块概览
4. 2~5 条核心流程
5. 技术能力画像
6. code evidence appendix
7. 可选：30 秒 / 90 秒面试讲述版本

### Step 6: 默认落地为 docs Markdown
如果用户没有明确要求“只在对话里输出”，默认还要把结果写成 Markdown 文档。

默认落地规则：
- 对于**本地仓库**：优先写到 repo 下的 `docs/repo-to-resume/`
- 文件名使用可读的 kebab-case，例如：`project-summary.md`、`repo-name-resume-summary.md`
- 如果仓库已经有 `docs/`，就在其下新增 `repo-to-resume/` 子目录；不要把这类文档散落在根目录
- 对于**远程 GitHub repo**：如果当前会话没有本地仓库副本，默认只在对话里输出；只有用户明确要求落盘，或当前工作区就是一个可写项目目录时，再写 Markdown
- 写完后在回复里明确告诉用户输出文件路径；如果未落盘，也要明确说明“本次仅对话输出，未写入本地文件”

如果用户指定了别的文档路径，以用户指定为准。

## Output Format

### 1. 项目一句话定位
用一句话说明：
- 这是个什么系统
- 它解决什么问题
- 复杂性在哪里

### 2. Resume-ready bullets
输出 2~4 条可以直接粘进简历的 bullet。

要求：
- 尽量用动词开头：参与建设 / 设计并实现 / 围绕…构建 / 完善…能力
- 避免“负责接口开发”“参与日常开发”这种空话
- 在有证据时，**优先适度加入量化产出**，让 bullet 更像简历成品
- 量化不要求每条都写；有些 repo 适合 1 条，有些适合 2~3 条，视证据强弱而定
- 可用的量化优先级：代码里可直接数出来的事实 > README / 配置 / 注册表里明确写出的数量 > 用户明确提供的数据
- 不写没有证据的数字

### 3. System Overview / Module Map
说明主要模块和职责分工。

### 4. Core Flows
至少列 2 条，最好 3~5 条。
每条都要带：
- 流程标题
- 关键路径说明
- 代码证据

### 5. Code Evidence Appendix
格式建议：
- 结论
- file path / GitHub path / URL
- 为什么这个文件能支撑该结论

如果是 GitHub repo，代码证据可以写成：
- `README.md`
- `pyproject.toml`
- `package.json`
- `.github/workflows/ci.yml`
- `cmd/server/main.go`
- `src/app.ts`
- 或直接给出用户提供的 GitHub URL 下的具体路径

### 6. Optional Interview Narrative
如果用户需要面试版本，再补：
- 30 秒版本
- 90 秒版本

## Preferred Writing Style

### 适合写在简历上的句子风格
- 参与建设统一工作流编排平台，支持……
- 围绕模板、实例、节点执行链路实现……
- 基于事务 + 异步消息驱动完成……
- 沉淀 DSL 校验、运行时执行与监控埋点能力……
- 在证据充分时，可写成：支持 X 类入口 / Y 个渠道 / Z 类 Provider / N 条核心链路

### 不推荐的句子风格
- 这个项目很复杂，做了很多功能。
- 负责接口开发与功能迭代。
- 提升了系统性能和稳定性。

除非代码或用户明确给出证据，否则不要写这类空泛结论。

## Output Quality Checklist

在给用户最终结果前，检查：

- 是否识别了 repo 类型（后端服务 / 前端应用 / CLI / SDK / monorepo）？
- 是否识别了分析来源（本地 repo / GitHub repo）？
- 是否找到了明确入口文件？
- 是否至少引用了 3 个关键代码文件或远程代码证据？
- 是否给出了面试官能听懂的系统抽象，而不是仅仅复述目录名？
- 是否在有证据时加入了适度量化，而不是全部停留在抽象描述？
- 是否避免了没有证据的指标和 ownership？
- 是否真的能直接复制到简历里？

## Example Prompts

- “总结这个 repo，给我 3 条可以写进简历的 bullet。”
- “从这个项目仓库生成一版面试可讲的项目介绍和核心流程。”
- “不要讲代码细节，帮我把这个 repo 转成项目产出。”
- “先给我项目一句话定位，再给我 resume bullet 和 code evidence。”
- “帮我分析这个 GitHub repo，输出成简历 bullets，不用拉到本地。”
- “这是一个 GitHub URL，帮我总结成项目介绍和代码证据。”
- “根据 `owner/repo` 直接做 repo-to-resume，总结时优先用远程代码证据。”

## Example Output Skeleton

```markdown
## 项目一句话定位
...

## 简历 bullets
- ...
- ...
- ...

## 系统概览
- 模块 A: ...
- 模块 B: ...

## 核心流程
### 流程 1: ...
...
**代码证据**
- path/to/file

### 流程 2: ...
...

## 技术能力画像
- ...
- ...

## 代码证据附录
| 结论 | 代码证据 |
|---|---|
| ... | ... |
```

## Notes

- 这个 skill 更偏“对外表达”和“项目提炼”，不是普通的代码理解 skill。
- 如果用户同时要“总结 repo + 生成文档”，先按本 skill 提炼内容，再落到 markdown 文档中。
- 默认应同时产出 Markdown 文件，优先写到 `docs/repo-to-resume/`；只有用户明确说不要落盘时，才只在对话里输出。
- 对 GitHub repo，不要求先 clone；优先远程分析，必要时再建议本地拉取。
- 如果用户只要一句话或 2 条 bullet，也仍然要先做最小必要的代码证据检查。
