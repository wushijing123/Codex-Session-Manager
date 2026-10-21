# 安装指南

[中文](INSTALLATION.md) · [English](INSTALLATION.en.md)

## 1. 前置要求

- Python 3.11 或更高版本
- Codex 已完成安装并至少运行过一次
- Git
- Node.js 24 仅用于开发检查，日常运行不要求

完整执行链路以 macOS 为主。Linux 支持扫描、报告、看板和测试；Windows 的软链接可能需要开发者模式或管理员权限。

## 2. 推荐安装：作为 Codex Skill 使用

共享 Skill 的唯一维护源是：

```text
~/.agents/skills/codex-session-lifecycle-manager
```

首次安装只需要克隆一次并创建 Codex 入口：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/wushijing123/Codex-Session-Manager.git \
  ~/.agents/skills/codex-session-lifecycle-manager
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/install_skill.py
```

安装器默认只创建 Codex 入口，不会改动 Claude Code、Antigravity 或 WorkBuddy。

验证安装：

```bash
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/doctor.py
```

## 3. 不安装 Skill，直接运行看板

只想使用本地看板时，可以把仓库放在任意目录，不需要创建任何软链接：

```bash
git clone https://github.com/wushijing123/Codex-Session-Manager.git
cd Codex-Session-Manager
python3 scripts/doctor.py --project-only
python3 scripts/session_manager.py dashboard
```

不自动打开浏览器：

```bash
python3 scripts/session_manager.py dashboard --no-open
```

独立会话库支持搜索、阅读、备份与本机协议允许的操作；受保护、已知置顶、当前及关联会话会按规则跳过。安装到其他 Agent 仅增加 Skill 入口，不增加其他产品的会话数据源。

## 4. 可选：连接其他 Agent

先预览，不写入文件：

```bash
python3 scripts/install_skill.py --targets all --dry-run
```

连接 Codex、Claude Code、Antigravity 和 WorkBuddy：

```bash
python3 scripts/install_skill.py --targets all
```

只连接指定 Agent：

```bash
python3 scripts/install_skill.py --targets codex workbuddy
```

安装器的结果：

- `OK`：已正确指向维护源
- `CREATED`：新建了软链接
- `CONFLICT`：目标已存在且不是正确软链接；保留原内容并停止

安装器没有 `--force`，不会静默覆盖已有目录或 Skill。

## 5. 从旧 Skill 名称安全迁移

旧版本维护源为：

```text
~/.agents/skills/wushijing-codex-session-manager
```

先预览迁移：

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
python3 scripts/install_skill.py --migrate-legacy --dry-run
```

确认后执行：

```bash
python3 scripts/install_skill.py --migrate-legacy
```

迁移器只会：

1. 在新目录不存在时，把旧维护源原子改名为新名称；
2. 迁移明确指向旧维护源的软链接；
3. 创建默认 Codex 入口。

如果新目录、同名 Agent 入口或真实目录已存在，迁移会停止并保留原内容。它不会合并目录，也不会覆盖用户文件。

## 6. 启动

```bash
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/session_manager.py dashboard
```

也可以在 Codex 中输入：

```text
使用 $codex-session-lifecycle-manager 打开 Codex-Session-Manager
```

## 7. 更新

```bash
cd ~/.agents/skills/codex-session-lifecycle-manager
git pull --ff-only
python3 scripts/doctor.py
```

入口是软链接，不需要每次更新后重新安装。

## 8. 从 Release 安装包安装

每个 GitHub Release 都附带运行时 Skill ZIP。解压后必须保持一个根目录和一个根 `SKILL.md`。若作为 Skill 使用，请将根目录放到 `~/.agents/skills/codex-session-lifecycle-manager`，再运行安装器；只使用独立看板时可解压到任意位置。

## 9. Windows 说明

Windows 创建目录软链接可能需要启用“开发者模式”或管理员权限。若无法创建，安装器会明确报错且不覆盖目标。当前 Release 与 CI 不把 Windows 永久删除执行链路标记为已验证。

## 10. 常见问题

### `legacy_source_detected`

当前仍在旧维护源目录中。按第 5 节先运行 `--migrate-legacy --dry-run`，确认后再执行正式迁移。

### `migration_target_exists` / `migration_entry_conflict`

新目录或新名称入口已经存在。迁移器不会猜测哪一份应被保留，也不会覆盖它。请先人工核对两份内容；不要直接删除未知目录。

### `source_must_be_canonical`

只有“安装为 Skill”时才要求仓库位于 `~/.agents/skills/codex-session-lifecycle-manager`。若只使用看板，请运行 `doctor.py --project-only`，无需移动仓库。

### `CONFLICT`

目标入口已有真实目录或指向其他位置。先人工核对内容；确认无用后将它移动到备份位置，再重新运行安装器。

### 看板地址打不开

确认启动命令仍在运行，并使用本次终端输出的新地址。旧的启动令牌不能复用。

### Doctor 提示 Node.js 缺失

这是开发检查警告，不影响日常扫描和看板运行。提交代码前应安装 Node.js 并完成 JavaScript 语法检查。
