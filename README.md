# yapi-sync

把 Java Spring Boot Controller 接口同步到 YApi，并自动生成前端对接文档（含增量字段 diff）。

解析 Controller 源码（路径、HTTP 方法、参数、DTO、返回类型），与 YApi 已有接口比对后精准同步：**新增 / 更新 / 跳过**。

## 适用条件

- Java Spring Boot 多模块项目（Gradle / Maven 均可）
- `@RestController` + `@RequestMapping` + `@GetMapping/@PostMapping` 等注解（无需 Swagger）
- 项目根目录有 `.easy.api.yml`（含 YApi 服务地址和各模块 token）

## 安装

### 1. 放入技能目录

解压本包，得到 `yapi-sync/` 目录，放到你所用 agent 的技能目录下：

- **Claude Code / 本环境**：`~/.claude/skills/` → `~/.claude/skills/yapi-sync/`
- 其它按各自 agent 的约定（如 Codex 的 `~/.codex/plugins/`）

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

依赖：`requests`、`PyYAML`（Python 3.7+）

## 项目配置

在**你的项目根目录**准备 `.easy.api.yml`（参考本包内 `.easy.api.yml.example`）：

```yaml
yapi:
  server: http://your-yapi.example.com
  token:
    micro-services.member-service.main: "member 模块的 token"
    micro-services.order-service.main: "order 模块的 token"
```

> ⚠️ token 是敏感信息，请勿提交到 git。

## 使用

### 方式一：AI 触发（推荐）

安装后直接对 AI 说：

- “同步接口到 YApi”
- “更新 yapi”
- “写前端对接文档”

### 方式二：一键脚本（已自动处理中文编码）

```bash
# Windows (cmd / Git Bash)
~/.claude/skills/yapi-sync/scripts/sync.bat D:/projects/your-project --dry-run

# macOS / Linux（首次可能需 chmod +x）
~/.claude/skills/yapi-sync/scripts/sync.sh ~/projects/your-project --doc --doc-name="商品推荐配置"
```

### 方式三：直接用 Python

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python ~/.claude/skills/yapi-sync/scripts/yapi_sync.py <项目路径> [选项]
```

### 选项

| 选项 | 说明 |
|------|------|
| `--dry-run` | 只预览，不实际修改 YApi |
| `--doc` | 同步后生成前端对接文档 |
| `--doc-name="名称"` | 文档文件名 |
| `--module=member-service` | 只同步指定模块 |
| `--base=master` | 与指定分支对比（默认看未提交变更） |
| `--config=xxx.yml` | 指定配置文件（默认 `<项目路径>/.easy.api.yml`） |

### 典型流程

```bash
# 1. 先预览
sync.bat D:/projects/your-project --dry-run

# 2. 确认无误后实际同步 + 生成文档
sync.bat D:/projects/your-project --doc --doc-name="商品推荐配置"
```

## 目录结构

```
yapi-sync/
├── SKILL.md                      # 技能定义（AI 触发规则）
├── README.md
├── requirements.txt              # Python 依赖
├── .easy.api.yml.example         # 配置示例（复制到项目根目录改成 .easy.api.yml）
├── templates/
│   └── frontend-api-doc-template.md
└── scripts/
    ├── sync.sh / sync.bat        # 一键启动（自动处理中文编码）
    ├── yapi_sync.py              # 主流程
    ├── java_parser.py            # Java 源码解析
    ├── yapi_client.py            # YApi Open API 封装
    ├── config_reader.py          # 读取配置与路径前缀常量
    └── doc_generator.py          # 前端对接文档生成
```

## 项目约定（重要）

脚本默认按以下约定解析，若你的项目不同，改对应位置即可：

| 约定 | 位置 | 说明 |
|------|------|------|
| 统一响应包装类 `WrapperResp<T>` | `java_parser.py` 顶部 `WRAPPER_RESP_TYPES` | 自动解包取 `data` |
| 分页包装类 `PageDataResp<T>` | `java_parser.py` 顶部 `PAGE_RESP_TYPES` | 自动解包取列表 |
| 路径前缀常量 `ServiceModuleConstant` | `config_reader.py` 顶部 `SERVICE_MODULE_CONSTANT_PATH` | 类路径不同时改这里 |
| 字符常量 `CharPool` | `config_reader.py` 的 `charpool` | 按需补充 |
| 模块名以 `-service` 结尾 | `yapi_sync.py` 的 `get_module_name` | 模块命名不同时改这里 |
| 只同步 `controller/web/`、`controller/mobile/` | `yapi_sync.py` 的 `is_web_or_mobile` | 目录约定不同时改这里 |

## 许可证

MIT
