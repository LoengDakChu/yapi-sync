---
name: yapi-sync
description: >-
  代码开发完成后，将新增或修改的 Java Controller 接口同步到 YApi，并按模板生成前端对接文档。
  解析 Spring Boot Controller 源码（路径、方法、参数、DTO、返回类型），与 YApi 已有接口比对后精准同步：
  新增、更新或跳过。支持生成前端对接文档（含增量字段 diff）。当用户说"同步接口到YApi"、
  "上传接口"、"更新yapi"、"写前端对接文档"等时触发。
license: MIT
metadata:
  author: WorkBuddy
  keywords: [yapi, sync, java, spring-boot, api-doc, frontend]
  version: 1.1.0
---

# YApi 接口同步 + 前端对接文档

## 触发场景

用户代码开发完（Controller 端点已写好），需要把接口更新到 YApi，并生成前端对接文档。

**触发词**：同步接口、上传接口到 YApi、更新 YApi、写前端对接文档、同步 API 文档

## 工具位置

所有脚本位于：`~/.claude/skills/yapi-sync/scripts/`

| 文件 | 职责 |
|------|------|
| `sync.bat` / `sync.sh` | 一键启动器（自动设置 UTF-8 编码，避免中文乱码） |
| `yapi_sync.py` | 主流程：git diff → 解析 Controller → 比对 YApi → 同步 → 生成文档 |
| `java_parser.py` | Java 源码解析器（提取注解、参数、DTO 字段、返回类型） |
| `yapi_client.py` | YApi Open API 封装（列表、新增、更新） |
| `config_reader.py` | 读取 `.easy.api.yml` 和 `ServiceModuleConstant.java` |
| `doc_generator.py` | 前端对接文档生成器（增量 diff） |

模板参考：`~/.claude/skills/yapi-sync/templates/frontend-api-doc-template.md`
配置示例：`~/.claude/skills/yapi-sync/.easy.api.yml.example`

## 运行命令

**首次使用前先安装 Python 依赖：**

```bash
pip install -r ~/.claude/skills/yapi-sync/requirements.txt
```

**推荐用一键启动器（已自动处理编码，中文不乱码）：**

```bash
# Windows (cmd / Git Bash)
~/.claude/skills/yapi-sync/scripts/sync.bat <项目路径> [选项]

# macOS / Linux
~/.claude/skills/yapi-sync/scripts/sync.sh <项目路径> [选项]
```

**或直接用 Python（需手动设置编码环境变量，否则中文乱码）：**

```bash
# Windows (Git Bash)
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python ~/.claude/skills/yapi-sync/scripts/yapi_sync.py <项目路径> [选项]
```

### 选项说明

| 选项 | 说明 |
|------|------|
| `--dry-run` | 只预览不实际修改 YApi |
| `--doc` | 同步后生成前端对接文档 |
| `--doc-name="名称"` | 文档文件名（中文） |
| `--module=member-service` | 只同步指定模块 |
| `--base=master` | 与指定分支对比差异（默认看未提交的变更） |
| `--config=xxx.yml` | 指定配置文件（默认 `<项目路径>/.easy.api.yml`） |

### 典型用法

```bash
# 1. 先预览（dry-run）
sync.bat <项目路径> --dry-run

# 2. 实际同步 + 生成前端文档
sync.bat <项目路径> --doc --doc-name="商品推荐配置"

# 3. 与 master 分支对比（查看本期所有改动）
sync.bat <项目路径> --base=master --doc --doc-name="V1版本接口"

# 4. 只同步某个模块
sync.bat <项目路径> --module=member-service --doc
```

## 执行流程

### 第一步：确认变更范围

运行 dry-run，查看哪些 Controller 有变更、解析出哪些接口：

```bash
~/.claude/skills/yapi-sync/scripts/sync.bat <项目路径> --dry-run
```

输出包含：
- 变更的 Controller 文件列表
- 每个接口的状态：NEW（将新增）、EXISTS（已存在）
- YApi 已有接口总数

**向用户展示 dry-run 结果，确认后再执行实际同步。**

### 第二步：执行同步 + 生成文档

```bash
~/.claude/skills/yapi-sync/scripts/sync.bat <项目路径> --doc --doc-name="<文档名>"
```

脚本会输出 JSON 报告：
```json
{
  "new": 3,
  "updated": 2,
  "skipped": 154,
  "errors": 0,
  "modules": { ... },
  "doc_path": "docs/frontend-api/xxx文档.md"
}
```

### 第三步：AI 补充文档内容

脚本生成的是**结构化草稿**，以下部分已自动填充：
- ✅ YApi 地址（含接口 ID）
- ✅ 接口路径、HTTP 方法
- ✅ 新增接口的出参字段表
- ✅ 修改接口的增量入参/出参表（自动 diff 旧定义 vs 新定义）
- ✅ 业务流程 ASCII 图

以下部分需要**你（AI）阅读代码后补充**：
- **调用时机**：前端在什么场景下调这个接口
- **前置条件**：是否需要登录、需要什么权限
- **行为变化**：逻辑变化描述（针对修改的接口）
- **出参重要字段**：从自动提取的全量字段中筛选前端真正需要的字段

**补充方法**：
1. 阅读对应的 Controller 方法代码
2. 阅读 Service 层实现代码
3. 理解业务逻辑后填写上述内容
4. 参考模板：`~/.claude/skills/yapi-sync/templates/frontend-api-doc-template.md`

## 适用项目条件

- Java Spring Boot 微服务项目（Gradle 多模块）
- 使用 `@RestController` + `@RequestMapping` + `@GetMapping/@PostMapping` 等注解
- 项目根目录有 `.easy.api.yml`（含 yapi.server 和各模块 token）
- `common` 模块中有 `ServiceModuleConstant.java`（定义路径前缀常量）
- 无需 Swagger 注解

## 依赖

- Python 3.7+
- `requests`、`PyYAML` 库：`pip install -r ~/.claude/skills/yapi-sync/requirements.txt`

## 项目约定（不同项目可改）

脚本默认按以下约定解析，若目标项目不同，改对应位置即可：

| 约定 | 位置 |
|------|------|
| 统一响应包装类 `WrapperResp<T>` | `java_parser.py` 顶部 `WRAPPER_RESP_TYPES` |
| 分页包装类 `PageDataResp<T>` | `java_parser.py` 顶部 `PAGE_RESP_TYPES` |
| 路径前缀常量类路径 | `config_reader.py` 顶部 `SERVICE_MODULE_CONSTANT_PATH` |
| 字符常量 `CharPool` | `config_reader.py` 的 `charpool` |
| 模块名以 `-service` 结尾 | `yapi_sync.py` 的 `get_module_name` |

## 注意事项

1. **编码**：必须设置 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`，否则中文乱码
2. **Controller 范围**：默认只同步 `controller/web/` 和 `controller/mobile/`，跳过 `feign/`
3. **Token**：从项目 `.easy.api.yml` 读取，不存储在技能中
4. **文档生成**：需要先执行同步（非 dry-run），因为需要接口 ID 生成 YApi 链接
5. **增量 diff**：对修改的接口，脚本会从 YApi 获取旧定义，与新定义做 JSON Schema diff，只输出新增/变更字段
6. **响应体**：自动解包 `WrapperResp<T>` → 提取 T 的字段
7. **分页**：YApi 可能有大几百个接口，脚本会自动翻页获取全部
