# 验证说明

以下内容记录本仓库公开发行前后用于检查文档和入口命令的结果。

## 已验证

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `python3 scripts/install_skill.py` | 通过 | 默认只安装 Codex 入口 |
| `python3 scripts/install_skill.py --targets codex workbuddy` | 通过 | 只创建指定入口，不覆盖已有目录 |
| `python3 scripts/install_skill.py --targets all --verify` | 通过 | 四个可用入口都指向唯一维护源 |
| `python3 scripts/install_skill.py --dry-run` | 通过 | 当前环境输出 `OK codex ...`，用于预览安装动作与冲突提示 |
| `python3 scripts/install_skill.py --verify` | 通过 | 当前 Codex 入口指向唯一维护源 |
| `python3 scripts/doctor.py --project-only` | 通过 | 项目检查通过 |
| `python3 -m unittest discover -s tests -v` | 通过 | 合成回归测试全部通过 |
| `node --check assets/dashboard/i18n.js` | 通过 | 语法检查通过 |
| `node --check assets/dashboard/app.js` | 通过 | 语法检查通过 |
| `python3 scripts/package_release.py --output-dir dist` | 通过 | 生成 `dist/codex-session-lifecycle-manager-v0.6.0.zip` |

真实恢复验证必须在 Codex 仍运行时启动，并显式使用 `--verify-closed-loop`。助手确认“启动时正在运行 → 完全退出 → 内容和索引恢复成功”后，才会写入本机能力标记；手工创建标记文件不属于验证。

## 暂未验证

- 真实机器上的闭环恢复到 Codex
- 永久删除的实机全流程
- Windows 运行链路

## 结论

公开发行文案只描述已验证边界；任何未进入上表“已验证”的能力，都应继续标记为待确认或待实测。
