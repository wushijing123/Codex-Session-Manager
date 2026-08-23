# 贡献指南

[中文](CONTRIBUTING.md) · [English](CONTRIBUTING.en.md)

## 原则

- 大道至简：优先减少步骤、概念和重复入口
- 只改目标相关代码，不顺手重构无关区域
- 事实、建议和计划必须保持分离
- 可恢复动作优先于永久删除
- 所有安全结论必须有合成测试证据
- 默认中文与英文界面必须同时完整
- 遵守 [行为准则](CODE_OF_CONDUCT.md)

## 开发环境

```bash
git clone <repository-url>
cd wushijing-codex-session-manager
python3 scripts/doctor.py --project-only
python3 -m unittest discover -s tests -v
```

Node.js 24 用于检查 Dashboard：

```bash
node --check assets/dashboard/i18n.js
node --check assets/dashboard/app.js
```

## 修改 Dashboard

- 静态中文文案写在 `index.html`
- 动态中文文案通过 `t("中文源文案")` 输出
- 英文翻译写入 `assets/dashboard/i18n.js`
- 不复制第二套页面或第二套动作逻辑
- 检查中文、英文、375px、桌面尺寸、键盘焦点和控制台

翻译覆盖由自动化测试检查，缺少英文映射时测试失败。

## 修改生命周期动作

任何会移动、隔离、恢复或删除真实数据的改动都必须：

1. 先写能复现问题的合成测试
2. 保持 scan → plan → receipt → confirm → manifest → execute 分层
3. 检查数据库歧义、置顶、父子关系、状态冲突和 Codex 进程
4. 验证中断回滚和重复执行幂等性
5. 更新安全文档与 CHANGELOG

## 提交前检查

```bash
python3 scripts/doctor.py --project-only
python3 -m unittest discover -s tests -v
node --check assets/dashboard/i18n.js
node --check assets/dashboard/app.js
python3 scripts/package_release.py --output-dir dist
git diff --check
```

## Pull Request

PR 必须说明：

- 用户能感知到的结果
- 是否影响真实会话或破坏性动作
- 测试证据
- 兼容性与迁移影响
- 中英界面是否同步
- 是否已更新公开文档与验证说明

不要在 PR 中上传真实数据库、会话正文、报告、manifest 或令牌。

公开发布前请先阅读 [路线图](ROADMAP.md) 和 [验证说明](docs/VERIFICATION.md)。

## 版本

使用语义版本：

- PATCH：兼容修复
- MINOR：向后兼容的新能力
- MAJOR：破坏兼容的状态、计划或安装变更

Release 标签必须与 `VERSION` 完全一致。
