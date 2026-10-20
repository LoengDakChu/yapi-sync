# yapi-sync

一个 [Agent Skills](https://docs.claude.com/en/docs/claude-code/skills) 技能：把 Java Spring Boot Controller 里新增/修改的接口**同步到 YApi**，并自动生成**前端对接文档**（含增量字段 diff）。

解析 Controller 源码（路径、HTTP 方法、参数、DTO、返回类型），与 YApi 已有接口按「方法 + 路径」比对，精准执行 **新增 / 更新 / 跳过**，不会误伤你没改过的接口。

## 它能做什么

| 能力 | 说明 |
|------|------|
| 增量识别 | 基于 `git diff` 只处理本次变更的 Controller，不动全量接口 |
| 源码解析 | 提取 `@RequestMapping`/`@GetMapping`/`@PostMapping` 等注解、路径常量、Query/Path 参数、`@RequestBody` DTO 字段、返回类型 |
| 智能解包 | 自动剥掉 `WrapperResp<T>` 包装取 `data`，识别 `PageDataResp<T>` 分页结构 |
| 精准同步 | 按「方法 + 路径」匹配 YApi 已有接口：不存在则新增，定义有变化则更新，一致则跳过 |
| 增量文档 | 修改过的接口，自动从 YApi 拉旧定义做 JSON Schema diff，只输出**新增/变更字段** |
| 中文友好 | 启动器内置 UTF-8 环境，Windows/macOS/Linux 下输出均不乱码 |

## 适用条件

满足以下条件即可使用，**不需要 Swagger 注解**：

- Java Spring Boot 多模块项目（Gradle / Maven 均可）
- Controller 用 `@RestController` + `@RequestMapping` + `@GetMapping`/`@PostMapping` 等注解
- 项目根目录有 `.easy.api.yml`（YApi 服务地址 + 各模块 token）
- 本机有 Python 3.7+（脚本依赖 `requests`、`PyYAML`）

## 安装

### 方式一：git clone（推荐）

```bash
# 放进你的 agent 技能目录（以 Claude Code 为例）
git clone https://github.com/<你的用户名>/yapi-sync.git ~/.claude/skills/yapi-sync
```

Windows 用户（PowerShell）用：

```powershell
git clone https://github.com/<你的用户名>/yapi-sync.git "$env:USERPROFILE\.claude\skills\yapi-sync"
```

### 方式二：下载压缩包

在仓库页面点 **Code → Download ZIP**，解压后把目录重命名为 `yapi-sync`，放进 `~/.claude/skills/`。

### 安装 Python 依赖

```bash
pip install -r ~/.claude/skills/yapi-sync/requirements.txt
```

> 依赖只有 `requests`、`PyYAML` 两个。若缺失，脚本会直接给出中文提示而非一堆 traceback。

### 其它 agent

不同 agent 的技能目录约定不同，放到对应位置即可（例如 Codex 的插件目录）。核心是：**目录名为 `yapi-sync`，且 `SKILL.md` 位于该目录根级**。

## 项目配置

在**你自己的 Java 项目根目录**创建 `.easy.api.yml`（参考仓库内的 `.easy.api.yml.example`）：

```yaml
yapi:
  server: http://your-yapi.example.com

  token:
    # key 格式：<任意层级>.<模块名>.main，脚本会自动识别以 -service 结尾的段作为模块名
    micro-services.member-service.main: "member-service 的 YApi token"
    micro-services.order-service.main: "order-service 的 YApi token"
```

> ⚠️ `.easy.api.yml` 含 YApi token，属于敏感信息。配置在**你业务项目的根目录**，不要提交进 git，更不要放进本仓库。
> 本仓库的 `.gitignore` 已忽略 `.easy.api.yml`，技能本身不存储任何 token。

YApi token 在 YApi 项目的「设置 → Token 配置」里获取；`server` 填你的 YApi 地址且不带末尾斜杠。

## 使用

### 方式一：直接对 AI 说（推荐）

安装后，正常写代码，然后对 AI 说：

- 「同步接口到 YApi」
- 「把这次改的接口上传到 YApi」
- 「写前端对接文档」

AI 会读取 `SKILL.md` 的流程：先 `--dry-run` 给你看变更清单 → 你确认 → 真正同步并生成文档。

### 方式二：一键脚本（已处理中文编码）

```bash
# Windows（cmd / Git Bash / PowerShell）
~/.claude/skills/yapi-sync/scripts/sync.bat D:/projects/your-project --dry-run

# macOS / Linux（首次可能需要 chmod +x scripts/sync.sh）
~/.claude/skills/yapi-sync/scripts/sync.sh ~/projects/your-project --doc --doc-name="商品推荐配置"
```

### 方式三：直接调用 Python

```bash
# 需手动设置编码环境变量，否则 Windows 下中文可能乱码
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python ~/.claude/skills/yapi-sync/scripts/yapi_sync.py <项目路径> [选项]
```

### 选项

| 选项 | 说明 |
|------|------|
| `--dry-run` | 只预览，不实际修改 YApi |
| `--doc` | 同步后生成前端对接文档 |
| `--doc-name="名称"` | 文档文件名（支持中文，默认「接口变更」） |
| `--module=member-service` | 只同步指定模块 |
| `--base=master` | 与指定分支对比差异（默认只看未提交的变更） |
| `--config=xxx.yml` | 指定配置文件（默认 `<项目路径>/.easy.api.yml`） |

### 典型流程

```bash
# 1. 先预览，确认要动哪些接口
sync.bat D:/projects/your-project --dry-run

# 2. 确认无误后实际同步 + 生成文档
sync.bat D:/projects/your-project --doc --doc-name="商品推荐配置"

# 3. 与 master 对比，同步本期全部改动
sync.bat D:/projects/your-project --base=master --doc --doc-name="V1版本接口"
```

脚本结束时输出中文摘要和 JSON 报告：

```json
{
  "new": 3,
  "updated": 2,
  "skipped": 154,
  "errors": 0
}
```

生成的前端文档输出到 `<项目路径>/docs/frontend-api/<文档名>.md`。

## 目录结构

```
yapi-sync/
├── SKILL.md                      # 技能定义（AI 触发规则与执行流程）
├── README.md
├── LICENSE                       # MIT
├── requirements.txt              # Python 依赖
├── .easy.api.yml.example         # 配置示例
├── .gitattributes                # 统一换行符（.sh 用 LF，.bat 用 CRLF）
├── templates/
│   └── frontend-api-doc-template.md
└── scripts/
    ├── sync.sh / sync.bat        # 一键启动（自动处理中文编码）
    ├── yapi_sync.py              # 主流程：git diff → 解析 → 比对 → 同步 → 生成文档
    ├── java_parser.py            # Java 源码解析
    ├── yapi_client.py            # YApi Open API 封装
    ├── config_reader.py          # 读取配置与路径前缀常量
    └── doc_generator.py          # 前端对接文档生成
```

## 项目约定（重要）

脚本默认按我所在项目的约定解析。**你的项目结构不同时，改对应位置即可**：

| 约定 | 位置 | 说明 |
|------|------|------|
| 统一响应包装类 `WrapperResp<T>` | `java_parser.py` 顶部 `WRAPPER_RESP_TYPES` | 自动解包取 `data` |
| 分页包装类 `PageDataResp<T>` | `java_parser.py` 顶部 `PAGE_RESP_TYPES` | 自动解包取列表 |
| 路径前缀常量 `ServiceModuleConstant` | `config_reader.py` 顶部 `SERVICE_MODULE_CONSTANT_PATH` | 找不到时会自动全项目兜底搜索 |
| 字符常量 `CharPool` | `config_reader.py` 的 `charpool` | 按需补充 |
| 模块名以 `-service` 结尾 | `yapi_sync.py` 的 `get_module_name` | 模块命名不同时改这里 |
| 只同步 `controller/web/`、`controller/mobile/`，跳过 `feign/` | `yapi_sync.py` 的 `is_web_or_mobile` | 目录约定不同时改这里 |

## 注意事项

1. **编码**：用 `sync.bat` / `sync.sh` 启动会自动设置 UTF-8；直接用 Python 时需自行设置 `PYTHONUTF8=1`。
2. **先在 git 仓库内使用**：接口识别依赖 `git diff`，目标项目必须是 git 仓库。
3. **先 dry-run 再同步**：同步会真实写入 YApi，建议先预览确认。
4. **生成文档需要真实同步**：文档中的 YApi 链接依赖接口 ID，`--dry-run` 模式不会生成文档。
5. **大项目分页**：脚本会自动翻页拉取 YApi 全部接口（几百个也没问题）。

## 许可证

[MIT](LICENSE)
