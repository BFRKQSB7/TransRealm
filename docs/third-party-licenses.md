# TransRealm 第三方依赖与许可

> 许可信息取自冻结环境（`requirements.lock`，24 项精确版本）下已安装包的元数据，2026-08-08 实测。本文件随依赖变化而更新；任何依赖版本变化必须同步 `requirements.lock` 并重跑全量质量命令（`03` §12.3）。

## 应用本体

- TransRealm 0.2.0 — **MIT License**（见仓库根 `LICENSE`；Copyright (c) 2026 TransRealm Contributors）。

## 运行时依赖

v0.2.0 候选唯一声明的运行时依赖是 PySide6（GUI，Qt 6）。候选冻结版本为 PySide6 6.11.1。

| 包 | 版本 | 许可 |
|---|---|---|
| PySide6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Addons | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Essentials | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |

Qt 商业/开源授权选择：以 LGPL-3.0 分发冻结应用时，需满足动态链接/可重链接要求（候选为 PyInstaller onedir 冻结 PySide6 运行时，属动态库分发场景，发布前应确认合规）。

## 开发 / 测试 / 打包工具链

这些包不进入运行时分发，但随仓库开发、测试与候选构建使用。

| 包 | 版本 | 许可 |
|---|---|---|
| pytest | 9.1.1 | MIT |
| pytest-qt | 4.5.0 | MIT |
| ruff | 0.16.0 | MIT |
| mypy | 2.3.0 | MIT |
| pyinstaller | 6.21.0 | GPL-2.0-or-later（含 Bootloader Exception，允许构建并分发非自由程序） |
| pyinstaller-hooks-contrib | 2026.6 | Apache-2.0 |
| mypy_extensions | 1.1.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| pluggy | 1.6.0 | MIT |
| iniconfig | 2.3.0 | MIT |
| Pygments | 2.20.0 | BSD-2-Clause |
| pathspec | 1.1.1 | MPL-2.0 |
| pefile | 2024.8.26 | MIT |
| altgraph | 0.17.5 | MIT |
| ast_serialize | 0.6.0 | MIT |
| colorama | 0.4.6 | BSD-3-Clause |
| librt | 0.13.0 | MIT |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| setuptools | 83.0.0 | MIT |

## 构建后端

- hatchling（`pyproject` build-system，仅源码构建时使用，不在 `requirements.lock` 快照内）。
