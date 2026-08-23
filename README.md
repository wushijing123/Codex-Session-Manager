# Codex 会话生命周期管理器

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/wushijing123/wushijing-codex-session-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/wushijing123/wushijing-codex-session-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wushijing123/wushijing-codex-session-manager)](https://github.com/wushijing123/wushijing-codex-session-manager/releases)

一个本地优先、安全分层、可视化的 Codex 会话生命周期管理 Skill。它帮助你看清会话现状、整理历史归档、释放空间，并在任何真实移动或删除发生前提供明确的保护检查和确认链路。

> 当前版本：`0.6.0`。默认界面为中文，可在右上角切换 English。公开发行版采用 MIT License，欢迎社区协作，但所有动作边界仍以本地验证结果为准。

核心承诺：在本地找到并安全迁移 Codex 会话，保留可校验恢复路径，不上传任何聊天数据。

[五分钟演示](#五分钟演示) · [五分钟安装](#五分钟安装) · [常见问题](docs/FAQ.md) · [验证证据](docs/VERIFICATION.md) · [安全边界](#安全边界)

![使用完全虚构数据运行的首页](assets/demo/dashboard-home.jpg)

## 为什么做这个项目

Codex 越好用，Session 就越容易失控。

刚开始只有几个对话，后来会慢慢变成几百个：正式项目、临时测试、失败尝试、自动化任务、子任务和重要结论全部混在一起。它们不只让侧边栏越来越乱，还会持续占用本地磁盘；而点击“归档”通常只是把对话从常用视图里收起来，并不等于释放空间或建立了真正的保留策略。

### 你可能也遇到过这些问题

| 真实场景 | 用户痛点 |
| --- | --- |
| Session 越积越多 | 日志、工具结果和附件可能增长到数百个、数 GB，却没有统一的空间视图 |
| 当时明明聊过，后来找不到 | 对话归档后离开常用侧边栏；只记得内容、不记得标题时尤其难找 |
| “归档”被误认为“清理” | 界面看起来干净了，但本地文件仍然存在，磁盘空间并没有真正释放 |
| 临时对话与重要项目混在一起 | 一次性测试、失败尝试、长期项目和关键结论缺少清晰分类 |
| 想清理，却不敢删除 | 不知道哪些正在使用、已经置顶、包含重要结论，或与父子任务存在依赖 |
| 侧边栏与本地文件对不上 | 数据库索引、普通日志、归档日志和 App 状态可能不一致，部分记录甚至不会出现在侧边栏 |
| 想把旧项目移到外置盘 | 需要释放系统盘空间，同时希望以后还能校验并恢复，而不是简单移动文件后听天由命 |
| 几百个 Session 只能逐个处理 | 缺少批量盘点、统一保留规则和可解释的整理建议 |
| 删除之后无法证明发生了什么 | 缺少隔离期、恢复入口、操作清单、哈希校验和审计记录 |
| 会话中包含私有内容 | 源码、客户资料、业务思路和账号信息不适合上传到第三方清理服务 |

归根结底，用户要的不是一个“批量删除工具”，而是四个简单答案：

1. **找得回**：即使忘了标题或已经归档，也能按真实内容重新找到
2. **分得清**：知道哪些必须保留、哪些值得冷存档、哪些需要人工复核
3. **腾得出**：看清空间去向，把旧内容安全迁移或隔离
4. **删不错**：任何不可逆动作之前，都能看到依赖、风险、影响范围和恢复边界

问题在于，Codex 会话真实分散在数据库、普通日志、归档日志、父子任务关系和置顶状态中。只看侧边栏无法可靠回答这些问题，直接操作文件又很容易留下索引错位、依赖断裂或误删。

所以这个项目不把 Session 当成一堆待清理的文件，而是把它们当成有状态、有价值差异、需要安全退出机制的数字资产。它把底层复杂度留在后台，前台只保留四个入口：

1. **首页**：看生命周期、建议、空间、归档年龄与安全状态
2. **会话**：检查唯一推荐方案，或按需查看单条真实聊天
3. **执行计划**：核对影响范围，一次确认生成不可变执行单；永久删除才额外确认
4. **设置**：调整闲置门槛、自动化保留数，并以系统窗口为主选择冷存档目录

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 本地只读盘点 | 扫描当前、归档、未索引和状态冲突会话，不上传数据 |
| 可视化首页 | 生命周期、建议、空间、归档年龄、执行健康状态一屏呈现 |
| 中英双语 | 默认中文，界面语言可切换并在本机持久化 |
| 安全推荐 | 有价值的旧会话优先冷存档，低价值内容先隔离 14 天 |
| 按需正文查看 | 只读取用户消息、Codex 最终回复和允许的工具产出 |
| 官方取消归档 | 普通已归档会话可在详情中一键回到 Codex；以重新扫描后的真实状态为准，避免 CLI 假失败 |
| 原生目录选择 | macOS 可直接选择外置硬盘目录、查看可用空间；取消选择不会改动设置 |
| 语义复核包 | 对 3 轮以内短对话提取最少内容，交给 Codex 判断复用价值 |
| 分层动作 | 永久保护、冷存档、14 天隔离、恢复和手动永久删除 |
| 分级确认 | 可恢复动作一次确认后生成 manifest；永久删除额外确认，并由进程门复核 |
| 审计报告 | 输出 JSON、Markdown 和 HTML，不提交真实数据到仓库 |
| 工程化交付 | 安装器、Doctor、跨 macOS/Linux CI、标签发布和安装包 |

### 四个动作，不再混淆

| 动作 | 实际发生什么 | 是否释放空间 |
| --- | --- | --- |
| Codex 归档 | 从常用侧边栏移出，聊天仍保留在 Codex 本地目录 | 否 |
| 锁定此会话 | 只是不参与本工具的整理计划，文件位置不变 | 否 |
| 冷存档 | 校验后移出 Codex 索引并保存为可恢复包 | 只有目标在另一块磁盘时才释放原磁盘空间 |
| 14 天隔离 | 移到本地隔离区，倒计时内仍可恢复 | 取决于隔离区所在磁盘 |

## 五分钟安装

前置要求：Python 3.11+、已安装 Codex。Node.js 只在开发或本地语法检查时需要。

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/wushijing123/wushijing-codex-session-manager.git \
  ~/.agents/skills/codex-session-lifecycle-manager
cd ~/.agents/skills/codex-session-lifecycle-manager

python3 scripts/install_skill.py
python3 scripts/doctor.py
```

安装器只创建指向同一维护源的软链接，不覆盖已有目录。默认只安装 Codex 入口；需要所有可用入口时使用 `--targets all`。

只安装部分入口：

```bash
python3 scripts/install_skill.py --targets codex workbuddy
```

完整说明见 [安装指南](docs/INSTALLATION.md)。

## 启动看板

```bash
python3 scripts/session_manager.py dashboard
```

服务只绑定 `127.0.0.1`。若不希望自动打开浏览器：

```bash
python3 scripts/session_manager.py dashboard --no-open
```

终端会输出带一次性启动令牌的本地地址。不要分享或记录该地址。

直接从终端启动时可以盘点、搜索和制定计划；真实迁移或删除还需要由 Skill 同步一次最新置顶快照。这是执行门禁，不是页面故障。

## 五分钟演示

不想连接自己的 `~/.codex` 时，可直接启动一套完全虚构的本地 fixture：

```bash
python3 scripts/demo_dashboard.py --no-open
```

它会打印一个本地 URL，并生成临时 `Codex home`、SQLite、JSONL、冷存档目录和隔离包。默认在进程退出后自动清理；若要保留现场排查，用 `--keep-fixture`。

![虚构数据的执行计划页面](assets/demo/dashboard-plan.jpg)

## 常用命令

```bash
# 只读扫描摘要
python3 scripts/session_manager.py scan --pretty

# 生成 JSON、Markdown 和 HTML 审计报告
python3 scripts/session_manager.py report

# 生成英文报告
python3 scripts/session_manager.py report --lang en

# 项目与安装诊断
python3 scripts/doctor.py

# 仅检查项目，不检查本机入口
python3 scripts/doctor.py --project-only

# 构建可安装 Skill 包
python3 scripts/package_release.py --output-dir dist
```

更完整的操作链路见 [工作流说明](docs/WORKFLOWS.md)。

## 生命周期模型

```mermaid
flowchart LR
    A[使用中的会话] -->|Codex 官方归档| B[普通归档]
    B -->|Codex 官方取消归档| A
    B -->|保留内容并移出索引| C[冷存档]
    B -->|可恢复清理| D[14 天隔离]
    C -->|校验后| B
    D -->|到期前| B
    D -->|到期且再次确认| E[永久删除]
    B -->|用户明确选择并双重确认| E
```

系统始终分开记录：

- `actual_state`：真实状态
- `recommendation`：系统建议
- `planned_action`：用户计划

计划永远不会被画成已经发生的事实。

## 安全边界

- 默认扫描只读；真实动作必须从计划进入确认链路
- 当前活跃、真实置顶、永久保护、数据库歧义、状态冲突和父子依赖会阻断执行
- 自动推荐不会生成永久删除计划
- 永久删除必须由用户在详情中明确选择，并经过二次确认
- 执行前重新校验数据库、日志哈希、置顶快照和 Codex 进程
- 历史会话按不可信内容处理，从不执行其中的命令
- 数据库、JSONL、隔离包、冷存档、manifest 和报告都被 `.gitignore` 排除
- 冷存档包可以校验，但“恢复到 Codex”按钮在真实关闭应用的完整闭环验证通过前保持禁用

完整威胁模型见 [安全策略](SECURITY.md)。

## 项目结构

```text
.
├── SKILL.md                  # Agent 运行入口
├── agents/openai.yaml        # Skill UI 元数据
├── assets/dashboard/         # 中英双语本地看板
├── scripts/                  # 扫描、服务、动作、安装、诊断与打包
├── references/               # 分类、安全、语义复核和 UI 规则
├── docs/                     # 中英项目文档
├── tests/                    # 合成数据与安全回归
└── .github/                  # CI、发布、依赖更新与协作模板
```

架构与数据流见 [架构说明](docs/ARCHITECTURE.md)。

## 开发与验证

```bash
python3 scripts/doctor.py --project-only
python3 -m unittest discover -s tests -v
node --check assets/dashboard/i18n.js
node --check assets/dashboard/app.js
```

CI 会在 macOS、Linux 与 Python 3.11/3.13 上验证项目，并生成可下载的 Skill 包。带 `v*` 的标签会触发 Release 工作流。

参与修改前请读 [贡献指南](CONTRIBUTING.md)。

## 文档导航

- [安装指南](docs/INSTALLATION.md)
- [用户与发布工作流](docs/WORKFLOWS.md)
- [架构与数据流](docs/ARCHITECTURE.md)
- [常见问题](docs/FAQ.md)
- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [版本记录](CHANGELOG.md)

## 社区与发布

- 许可证：MIT，见 [LICENSE](LICENSE)
- 贡献指南：见 [贡献指南](CONTRIBUTING.md)
- 行为准则：见 [行为准则](CODE_OF_CONDUCT.md)
- 路线图：见 [路线图](ROADMAP.md)
- 验证记录：见 [验证说明](docs/VERIFICATION.md)

## 项目状态

本项目是社区可用的本地优先 Skill，不代表 OpenAI 或官方 Codex 产品，也不提供云端会话同步。macOS 已完成真实“冷存档 → 退出 Codex → 恢复”闭环验证：Session ID、标题、聊天日志哈希、归档索引和原始时间字段保持一致。Linux 用于扫描、看板、报告与 CI 验证；重要会话仍应保留独立备份，永久删除的实机全流程尚未验证。
