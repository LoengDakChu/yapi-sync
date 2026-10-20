#!/usr/bin/env python3
"""
config_reader.py - Read .easy.api.yml and ServiceModuleConstant.java

Provides:
  - YApi server URL
  - Module -> token mapping
  - Module -> project_id mapping (fetched from YApi)
  - Path prefix constant resolution (ServiceModuleConstant.XXX_PATH_PREFIX -> "/member")
"""

import os
import re
import yaml
from pathlib import Path

# 项目约定：ServiceModuleConstant.java 的默认相对路径（不同项目可改这里）
SERVICE_MODULE_CONSTANT_PATH = (
    Path("common") / "src" / "main" / "java" / "com" / "ssy" / "lingxi"
    / "common" / "constant" / "ServiceModuleConstant.java"
)


class ConfigReader:
    def __init__(self, project_path: str, config_file: str = None):
        self.project_path = Path(project_path)
        self.config_file = Path(config_file) if config_file else (self.project_path / ".easy.api.yml")
        self.server = None
        self.module_tokens = {}  # "member-service" -> "3ec05fe..."
        self.path_prefixes = {}  # "MEMBER_PATH_PREFIX" -> "/member"
        self.charpool = {
            "SLASH": "/",
            "DASHED": "-",
            "UNDERLINE": "_",
            "DOT": ".",
            "COMMA": ",",
            "LEFT_BRACES": "{",
            "RIGHT_BRACES": "}",
            "LEFT_BRACKETS": "[",
            "RIGHT_BRACKETS": "]",
            "COLON": ":",
            "AT": "@",
            "SHARP": "#",
            "DOLLAR": "$",
            "ASTERISK": "*",
            "QUESTION": "?",
            "EXCLAMATION": "!",
            "SPACE": " ",
            "TAB": "\t",
            "BACKSLASH": "\\",
            "DOUBLE_QUOTES": '"',
            "SINGLE_QUOTES": "'",
            "AMP": "&",
            "NUM": "#",
        }
        self._load_config()
        self._load_path_prefixes()

    def _load_config(self):
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")
        with open(self.config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        yapi_cfg = data.get("yapi", {})
        self.server = yapi_cfg.get("server", "").rstrip("/")
        tokens = yapi_cfg.get("token", {})
        for key, token in tokens.items():
            # key 格式示例：
            #   "micro-services.member-service.main"
            #   "micro-services.services.member-service.main"
            # 以 -service 结尾的段即模块名，兼容不同层级结构
            parts = key.split(".")
            module = next((p for p in parts if p.endswith("-service")), None)
            if module:
                self.module_tokens[module] = token

    def _load_path_prefixes(self):
        """Parse ServiceModuleConstant.java to build constant -> value mapping."""
        # Find the file
        constant_file = self.project_path / SERVICE_MODULE_CONSTANT_PATH
        if not constant_file.exists():
            # 兜底搜索：只扫源码，跳过 .git/build/target 等重目录
            for root, dirs, files in os.walk(self.project_path):
                dirs[:] = [d for d in dirs if d not in (".git", "build", "target", "node_modules", ".gradle", "out", "bin")]
                if "ServiceModuleConstant.java" in files:
                    constant_file = Path(root) / "ServiceModuleConstant.java"
                    break
        if not constant_file.exists():
            print("Warning: ServiceModuleConstant.java not found, path prefix resolution will be limited")
            return

        content = constant_file.read_text(encoding="utf-8")

        # First pass: extract all simple string constants
        # Pattern: public static final String XXX = "value";
        const_pattern = re.compile(
            r'public\s+static\s+final\s+String\s+(\w+)\s*=\s*"([^"]*)"\s*;'
        )
        simple_consts = {}
        for m in const_pattern.finditer(content):
            name = m.group(1)
            value = m.group(2)
            simple_consts[name] = value

        # Second pass: extract composite constants (e.g., SLASH + MEMBER)
        # Pattern: public static final String XXX = CharPool.YYY + ZZZ;
        # or: public static final String XXX = CharPool.YYY + ZZZ + CharPool.WWW;
        composite_pattern = re.compile(
            r'public\s+static\s+final\s+String\s+(\w+)\s*=\s*([^;]+);'
        )
        for m in composite_pattern.finditer(content):
            name = m.group(1)
            expr = m.group(2).strip()
            # Skip if already resolved as simple constant
            if name in simple_consts:
                continue
            value = self._eval_const_expr(expr, simple_consts)
            if value is not None:
                simple_consts[name] = value

        # Filter to only PATH_PREFIX constants
        for name, value in simple_consts.items():
            if name.endswith("_PATH_PREFIX") or name.endswith("_PATH_PREFIX_"):
                self.path_prefixes[name] = value

        print(f"Loaded {len(self.path_prefixes)} path prefix constants from ServiceModuleConstant")

    def _eval_const_expr(self, expr: str, consts: dict) -> str:
        """Evaluate a constant expression like CharPool.SLASH + MEMBER."""
        # Split by +
        parts = re.split(r'\s*\+\s*', expr)
        result = ""
        for part in parts:
            part = part.strip().strip('"')
            if part.startswith("CharPool."):
                key = part[len("CharPool."):]
                result += self.charpool.get(key, "")
            elif part.startswith("ServiceModuleConstant."):
                key = part[len("ServiceModuleConstant."):]
                result += consts.get(key, "")
            elif part in consts:
                result += consts[part]
            else:
                # It's a literal string (already stripped of quotes) or unknown
                result += part
        return result

    def get_token(self, module_name: str) -> str:
        return self.module_tokens.get(module_name)

    def get_server(self) -> str:
        return self.server

    def resolve_path_prefix(self, expr: str) -> str:
        """
        Resolve an expression like:
          ServiceModuleConstant.MEMBER_PATH_PREFIX + "/ability/info"
        to: /member/ability/info
        """
        if not expr:
            return ""
        # Remove "ServiceModuleConstant." prefix references
        def replace_const(m):
            name = m.group(1)
            return f'"{self.path_prefixes.get(name, "")}"'

        expr = re.sub(r'ServiceModuleConstant\.(\w+)', replace_const, expr)

        # Now evaluate string concatenation: "xxx" + "yyy" -> xxxyyy
        parts = re.split(r'\s*\+\s*', expr)
        result = ""
        for part in parts:
            part = part.strip()
            if part.startswith('"') and part.endswith('"'):
                result += part[1:-1]
            else:
                result += part
        return result

    def get_all_modules(self) -> list:
        return list(self.module_tokens.keys())
