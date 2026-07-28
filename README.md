# 译境 / TransRealm

本地优先、AI 辅助的翻译工作台。V1.0 目标：单用户、SQLite、OpenAI-compatible HTTP、Windows 11 绿色版优先。

## 开发基线

- Python 3.12+
- PySide6（Qt 6）
- SQLite
- pytest

## 目录结构

```text
src/transrealm/
  ui/               # PySide6 页面与信号
  application/      # 应用服务与编排
  domain/           # 领域模型与业务规则（不依赖 Qt/SQLite/HTTP）
  infrastructure/   # SQLite、Repository、持久化
  adapters/         # 外部模型端点适配

tests/              # pytest 测试
```

## 安装开发依赖

```bash
py -3.12 -m pip install -e ".[dev]"
```

## 运行测试

```bash
py -3.12 -m pytest
```
