# 安装指南

[中文](INSTALLATION.md) · [English](INSTALLATION.en.md)

## 1. 前置要求

- Python 3.11 或更高版本
- Codex 已完成安装并至少运行过一次
- Git；私有仓库推荐使用已登录的 GitHub CLI
- Node.js 24 仅用于开发检查，日常运行不要求

完整执行链路以 macOS 为主。Linux 支持扫描、报告、看板和测试；Windows 的软链接可能需要开发者模式或管理员权限。

## 2. 安装到唯一维护源

共享 Skill 的唯一维护源必须是：

```text
~/.agents/skills/wushijing-codex-session-manager
```

首次安装：

```bash
mkdir -p ~/.agents/skills
gh repo clone wushijing123/wushijing-codex-session-manager \
  ~/.agents/skills/wushijing-codex-session-manager
cd ~/.agents/skills/wushijing-codex-session-manager
```

如果目录已经存在，不要重复克隆：

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
git pull --ff-only
```

## 3. 创建 Agent 入口

预览：

```bash
python3 scripts/install_skill.py --dry-run
```

安装 Codex、Claude Code、Antigravity 和 WorkBuddy 入口：

```bash
python3 scripts/install_skill.py
```

只安装指定入口：

```bash
python3 scripts/install_skill.py --targets codex
python3 scripts/install_skill.py --targets codex workbuddy
```

安装器只有三种结果：

- `OK`：已正确指向维护源
- `CREATED`：新建了软链接
- `CONFLICT`：目标已存在且不是正确软链接，安装器停止并保留原内容

安装器没有 `--force`，不会静默覆盖已有 Skill。

## 4. 验证

```bash
python3 scripts/install_skill.py --verify
python3 scripts/doctor.py
```

预期结果是四个入口均为 `OK`，Doctor 没有 `FAIL`。

## 5. 启动

```bash
python3 scripts/session_manager.py dashboard
```

不自动打开浏览器：

```bash
python3 scripts/session_manager.py dashboard --no-open
```

也可以在 Codex 中输入：

```text
使用 $wushijing-codex-session-manager 打开会话生命周期看板
```

## 6. 更新

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
git pull --ff-only
python3 scripts/doctor.py
```

入口是软链接，不需要每次更新后重新安装。

## 7. 从 Release 安装包安装

每个 GitHub Release 都附带运行时 Skill ZIP。解压后必须保持一个根目录和一个根 `SKILL.md`。推荐仍将该根目录放到 `~/.agents/skills/`，再运行安装器。

## 8. Windows 说明

Windows 创建目录软链接可能需要启用“开发者模式”或管理员权限。若无法创建，安装器会明确报错且不覆盖目标。当前 Release 与 CI 不把 Windows 永久删除执行链路标记为已验证。

## 9. 常见问题

### `source_must_be_canonical`

仓库不在 `~/.agents/skills/wushijing-codex-session-manager`。移动或重新克隆到该路径，再运行安装器。

### `CONFLICT`

目标入口已有真实目录或指向其他位置。先人工核对内容，不要直接删除。确认无用后再把它移到备份位置，然后重新运行安装器。

### 看板地址打不开

确认启动命令仍在运行，并使用本次终端输出的新地址。旧的启动令牌不能复用。

### Doctor 提示 Node.js 缺失

这是开发检查警告，不影响日常扫描和看板运行。提交代码前应安装 Node.js 并完成 JavaScript 语法检查。
