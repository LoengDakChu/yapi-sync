#!/usr/bin/env python3
"""
java_parser.py - Parse Java Controller source files to extract API definitions.

Extracts from Controller files:
  - Class-level @RequestMapping (base path, with constant resolution)
  - Method-level mapping annotations (@GetMapping, @PostMapping, etc.)
  - Parameters: @PathVariable, @RequestParam, @RequestBody, @Valid
  - Return type (for response body resolution)
  - Javadoc comments (for API title and description)

Extracts from DTO/VO classes:
  - Field name, type, validation annotations
  - Javadoc comments (for field descriptions)
  - Nested type resolution (recursive)
"""

import re
import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── 项目约定（不同项目可在此修改）───────────────────────────────
# 统一响应包装类 / 分页包装类，出现在返回值泛型里时会被自动解包
WRAPPER_RESP_TYPES = ("WrapperResp",)
PAGE_RESP_TYPES = ("PageDataResp",)


@dataclass
class ApiParam:
    """Query parameter"""
    name: str = ""
    required: int = 0  # 1=required, 0=optional
    desc: str = ""


@dataclass
class ApiPathParam:
    """Path parameter"""
    name: str = ""
    desc: str = ""


@dataclass
class ApiField:
    """A field in a DTO/VO class"""
    name: str = ""
    java_type: str = ""
    desc: str = ""
    required: bool = False
    children: list = field(default_factory=list)  # For nested objects


@dataclass
class ApiInterface:
    """A complete API interface definition"""
    title: str = ""
    method: str = ""  # GET, POST, PUT, DELETE, PATCH
    path: str = ""  # Full path e.g. /member/ability/info/page
    desc: str = ""
    req_query: list = field(default_factory=list)  # List[ApiParam]
    req_params: list = field(default_factory=list)  # List[ApiPathParam] - path params
    req_body_type: str = ""  # "json" or ""
    req_body_other: str = ""  # JSON Schema string
    res_body_type: str = "json"
    res_body: str = ""  # JSON Schema string
    controller_file: str = ""
    method_name: str = ""  # Java method name
    java_return_type: str = ""  # Raw return type string


class JavaParser:
    # HTTP method mapping from annotation names
    METHOD_MAP = {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "DeleteMapping": "DELETE",
        "PatchMapping": "PATCH",
        "RequestMapping": None,  # Need to check method attribute
    }

    # Java type -> JSON Schema type mapping
    TYPE_MAP = {
        "String": "string",
        "string": "string",
        "Long": "integer",
        "long": "integer",
        "Integer": "integer",
        "int": "integer",
        "Boolean": "boolean",
        "boolean": "boolean",
        "Double": "number",
        "double": "number",
        "Float": "number",
        "float": "number",
        "BigDecimal": "number",
        "BigInteger": "integer",
        "Short": "integer",
        "short": "integer",
        "Byte": "integer",
        "byte": "integer",
        "char": "string",
        "Character": "string",
        "Date": "string",
        "LocalDate": "string",
        "LocalDateTime": "string",
        "LocalTime": "string",
        "Timestamp": "string",
        "ZonedDateTime": "string",
        "OffsetDateTime": "string",
        "Instant": "string",
        "Duration": "string",
        "Period": "string",
        "UUID": "string",
        "Object": "object",
        "void": "",
        "Void": "",
        "MultipartFile": "file",
    }

    FORMAT_MAP = {
        "Long": "int64",
        "long": "int64",
        "Integer": "int32",
        "int": "int32",
        "BigDecimal": "double",
        "Double": "double",
        "Date": "date-time",
        "LocalDateTime": "date-time",
        "LocalDate": "date",
        "LocalTime": "time",
    }

    def __init__(self, project_path: str, config_reader=None):
        self.project_path = Path(project_path)
        self.config = config_reader
        self._dto_cache = {}  # className -> schema dict (prevent infinite recursion)
        self._file_cache = {}  # file path -> content
        self._import_cache = {}  # (module_src_path, class_name) -> file path

    def _read_file(self, file_path: Path) -> str:
        key = str(file_path)
        if key not in self._file_cache:
            if file_path.exists():
                self._file_cache[key] = file_path.read_text(encoding="utf-8", errors="replace")
            else:
                self._file_cache[key] = ""
        return self._file_cache[key]

    def _extract_javadoc_above(self, content: str, position: int) -> str:
        """Extract Javadoc comment that appears before the given position."""
        # Search backwards for */ 
        before = content[:position].rstrip()
        if not before.endswith("*/"):
            return ""
        # Find the matching /**
        start = before.rfind("/**")
        if start == -1:
            return ""
        doc = content[start:position]
        return self._clean_javadoc(doc)

    def _clean_javadoc(self, doc: str) -> str:
        """Clean a Javadoc comment: remove /**, */, *, @param, @return, etc."""
        # Remove /** and */
        doc = re.sub(r'^/\*\*', '', doc)
        doc = re.sub(r'\*/$', '', doc)
        # Remove leading * from each line
        lines = doc.split("\n")
        cleaned = []
        for line in lines:
            line = re.sub(r'^\s*\*\s?', '', line)
            if line.strip():
                cleaned.append(line.strip())
        # Take first non-empty line as title, rest as description
        if not cleaned:
            return ""
        return cleaned[0] if len(cleaned) == 1 else cleaned[0]

    def _extract_javadoc_first_line(self, content: str, position: int) -> str:
        """Extract the first line of Javadoc above a position."""
        doc = self._extract_javadoc_above(content, position)
        if not doc:
            return ""
        # For method titles, take the first sentence
        return doc.split("\n")[0].split("。")[0].strip()

    def _extract_javadoc_field_desc(self, content: str, field_pos: int) -> str:
        """Extract field description from Javadoc above a field."""
        doc = self._extract_javadoc_above(content, field_pos)
        if not doc:
            return ""
        return doc

    def parse_controller(self, file_path: str) -> list:
        """
        Parse a Controller file and return a list of ApiInterface objects.
        """
        file_path = Path(file_path)
        content = self._read_file(file_path)
        if not content:
            return []

        interfaces = []

        # Extract package and imports for DTO resolution
        pkg_match = re.search(r'^package\s+([\w.]+);', content, re.MULTILINE)
        package = pkg_match.group(1) if pkg_match else ""
        imports = self._extract_imports(content)
        module_src = self._get_module_src_path(file_path)

        # Find class-level @RequestMapping
        class_base_path = self._extract_class_path(content)

        # Find the class declaration line - only scan for methods AFTER it
        class_decl_match = re.search(r'\b(?:public\s+)?class\s+\w+', content)
        class_decl_line_idx = 0
        if class_decl_match:
            class_decl_line_idx = content[:class_decl_match.start()].count("\n")

        # Scan lines after class declaration for method-level mapping annotations
        lines = content.split("\n")
        i = class_decl_line_idx + 1
        while i < len(lines):
            line = lines[i]
            # Check if this line has a method-level mapping annotation
            # Skip @RequestMapping if it's at class level (already handled)
            mapping_match = re.search(
                r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b(.*)',
                line
            )
            # Also check @RequestMapping but only if it looks like a method annotation
            # (not the class-level one which is before the class declaration)
            if not mapping_match:
                req_mapping_match = re.search(
                    r'@(RequestMapping)\b(.*)',
                    line
                )
                if req_mapping_match and i > class_decl_line_idx:
                    mapping_match = req_mapping_match
            if mapping_match:
                annotation_name = mapping_match.group(1)
                rest_of_line = mapping_match.group(2)

                # Extract path from annotation
                method_path = self._extract_annotation_path(rest_of_line)
                if method_path is None:
                    # Multi-line annotation, look at next lines
                    full_annotation = line
                    j = i + 1
                    while j < len(lines) and ")" not in full_annotation:
                        full_annotation += "\n" + lines[j]
                        j += 1
                    method_path = self._extract_annotation_path(
                        full_annotation[full_annotation.index("("):] if "(" in full_annotation else ""
                    )
                    if method_path is None:
                        method_path = ""

                # Extract HTTP method
                http_method = self._get_http_method(annotation_name, rest_of_line, lines, i)

                # Find the method signature (return type + name + params)
                # Look forward from current position
                sig_start = i
                # Skip annotation lines and find the actual method declaration
                method_decl_line = i
                while method_decl_line < len(lines):
                    decl_line = lines[method_decl_line]
                    # Look for the method signature pattern: returnType methodName(
                    # Skip annotation lines
                    if decl_line.strip().startswith("@"):
                        method_decl_line += 1
                        continue
                    # Check if this line has a method declaration
                    sig_match = re.match(
                        r'\s*(?:public\s+)?([\w<>.,\s\[\]?!]+?)\s+(\w+)\s*\(',
                        decl_line
                    )
                    if sig_match and "class " not in decl_line and not decl_line.strip().startswith("if ") and not decl_line.strip().startswith("for ") and not decl_line.strip().startswith("while ") and not decl_line.strip().startswith("return ") and not decl_line.strip().startswith("new "):
                        return_type = sig_match.group(1).strip()
                        method_name = sig_match.group(2).strip()
                        # Find the full method (parameters might span multiple lines)
                        full_method = ""
                        paren_depth = 0
                        for ml in range(method_decl_line, min(method_decl_line + 30, len(lines))):
                            full_method += lines[ml] + "\n"
                            paren_depth += lines[ml].count("(") - lines[ml].count(")")
                            if paren_depth <= 0 and "(" in full_method:
                                break

                        # Extract Javadoc for this method
                        # Search backwards through annotation lines to find the Javadoc
                        javadoc = ""
                        for dp in range(i - 1, -1, -1):
                            stripped = lines[dp].strip()
                            if stripped == "" or stripped.startswith("@") or stripped.startswith("//"):
                                continue
                            if stripped.endswith("*/"):
                                # Found Javadoc end - extract it
                                doc_char_pos = sum(len(l) + 1 for l in lines[:dp + 1])
                                javadoc = self._extract_javadoc_first_line(content, doc_char_pos)
                                break
                            # Not a javadoc, stop searching
                            break

                        # Parse parameters
                        params_str = full_method[full_method.index("(") + 1:]
                        if params_str.rfind(")") != -1:
                            params_str = params_str[:params_str.rfind(")")]
                        char_pos = sum(len(l) + 1 for l in lines[:i])
                        params = self._parse_method_params(params_str, content, char_pos, imports, module_src, package)

                        # Resolve full path
                        full_path = self._resolve_full_path(class_base_path, method_path)

                        # Resolve return type to JSON Schema
                        res_body_schema = self._resolve_return_type(return_type, imports, module_src)

                        # Build interface
                        iface = ApiInterface(
                            title=javadoc or method_name,
                            method=http_method,
                            path=full_path,
                            desc=javadoc,
                            req_query=params["query"],
                            req_params=params["path"],
                            req_body_type="json" if params["body"] else "",
                            req_body_other=json.dumps(params["body"], ensure_ascii=False) if params["body"] else "",
                            res_body_type="json" if res_body_schema else "",
                            res_body=json.dumps(res_body_schema, ensure_ascii=False) if res_body_schema else "",
                            controller_file=str(file_path),
                            method_name=method_name,
                            java_return_type=return_type,
                        )
                        interfaces.append(iface)
                        break
                    method_decl_line += 1
            i += 1

        return interfaces

    def _extract_imports(self, content: str) -> dict:
        """Extract import statements. Returns {ClassName: full.package.ClassName}"""
        imports = {}
        for m in re.finditer(r'^import\s+([\w.]+);', content, re.MULTILINE):
            full = m.group(1)
            cls = full.split(".")[-1]
            imports[cls] = full
        return imports

    def _get_module_src_path(self, file_path: Path) -> Path:
        """Get the src/main/java path for the module containing this file."""
        # file_path like: .../member-service/src/main/java/com/ssy/lingxi/member/controller/web/XxxController.java
        parts = file_path.parts
        for i, part in enumerate(parts):
            if part == "src" and i + 2 < len(parts) and parts[i + 1] == "main" and parts[i + 2] == "java":
                return Path(*parts[:i + 3])
        return file_path.parent

    def _extract_superclass(self, content: str) -> Optional[str]:
        """提取类声明的父类名，无父类时返回 None"""
        m = re.search(r'(?:public\s+)?(?:abstract\s+)?class\s+\w+\s+extends\s+([\w.]+)', content)
        if not m:
            return None
        return m.group(1).split(".")[-1]

    def _extract_class_path(self, content: str) -> str:
        """Extract class-level @RequestMapping path."""
        # Find @RequestMapping before class declaration
        # Pattern: @RequestMapping(value) or @RequestMapping("path" + CONST)
        pattern = re.compile(
            r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?(.*?)(?:\)|,)',
            re.DOTALL
        )
        # Find position of class declaration
        class_match = re.search(r'public\s+class\s+\w+', content)
        if not class_match:
            return ""
        before_class = content[:class_match.start()]
        m = pattern.search(before_class)
        if not m:
            return ""
        expr = m.group(1).strip()
        # Remove quotes and resolve constants
        if expr.startswith('"') and expr.endswith('"'):
            expr = expr[1:-1]
        # Resolve ServiceModuleConstant references
        if self.config:
            return self.config.resolve_path_prefix(expr)
        return expr

    def _extract_annotation_path(self, annotation_content: str) -> Optional[str]:
        """Extract path from mapping annotation content like ("path") or (value="path")."""
        if not annotation_content or "(" not in annotation_content:
            return ""
        # Extract content inside parentheses
        paren_start = annotation_content.index("(")
        # Find matching close paren
        depth = 0
        paren_end = -1
        for idx, ch in enumerate(annotation_content[paren_start:], paren_start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    paren_end = idx
                    break
        if paren_end == -1:
            inner = annotation_content[paren_start + 1:]
        else:
            inner = annotation_content[paren_start + 1:paren_end]

        inner = inner.strip()

        if not inner:
            return ""

        # Try to extract path string
        # Pattern: "path" or value = "path" or path = "path"
        str_match = re.search(r'"([^"]*)"', inner)
        if str_match:
            return str_match.group(1)

        # Pattern with constant: ServiceModuleConstant.XXX + "/path"
        if "ServiceModuleConstant" in inner:
            if self.config:
                return self.config.resolve_path_prefix(inner)

        return ""

    def _get_http_method(self, annotation_name: str, content: str, lines: list, line_idx: int) -> str:
        """Determine HTTP method from annotation name."""
        direct = self.METHOD_MAP.get(annotation_name)
        if direct:
            return direct
        # For @RequestMapping, check method attribute
        method_match = re.search(r'method\s*=\s*RequestMethod\.(\w+)', content)
        if method_match:
            return method_match.group(1).upper()
        # @RequestMapping 未指定 method：根据方法参数是否含 @RequestBody 推断
        # 带 @RequestBody 的接口实际为 POST 语义（GET 请求通常不带 body），否则默认 GET
        for j in range(line_idx, min(line_idx + 8, len(lines))):
            line = lines[j]
            if "@RequestBody" in line:
                return "POST"
            # 已扫到方法体开括号，参数扫描结束，停止
            if "{" in line and ("(" in line or "public" in line):
                break
        return "GET"

    def _resolve_full_path(self, base_path: str, method_path: str) -> str:
        """Combine class base path and method path."""
        base = base_path.rstrip("/")
        method = method_path.lstrip("/")
        if not method:
            return base
        return f"{base}/{method}"

    def _parse_method_params(self, params_str: str, content: str, method_pos: int,
                            imports: dict, module_src: Path, package: str) -> dict:
        """Parse method parameters into query params, path params, and request body."""
        result = {"query": [], "path": [], "body": None}
        if not params_str.strip():
            return result

        # Split parameters by comma (but not inside generics like List<X, Y>)
        params = self._split_params(params_str)

        for param in params:
            param = param.strip()
            if not param:
                continue

            # Skip framework parameters
            if any(skip in param for skip in ["HttpHeaders", "HttpServletResponse",
                                                "HttpServletRequest", "BindingResult",
                                                "MultipartFile", "Principal"]):
                continue

            # Check for @PathVariable
            if "@PathVariable" in param:
                name = self._extract_param_name(param)
                desc = self._extract_param_javadoc(content, method_pos, name)
                result["path"].append(ApiPathParam(name=name, desc=desc))
                continue

            # Check for @RequestParam
            if "@RequestParam" in param:
                name = self._extract_param_name(param)
                required = self._is_param_required(param)
                desc = self._extract_param_javadoc(content, method_pos, name)
                result["query"].append(ApiParam(name=name, required=1 if required else 0, desc=desc))
                continue

            # Check for @RequestBody
            if "@RequestBody" in param:
                # Extract the DTO type
                type_match = re.search(r'@RequestBody\s+(?:@\w+\s+)*([\w<>]+)\s+(\w+)', param)
                if type_match:
                    dto_type = type_match.group(1)
                    dto_name = type_match.group(2)
                    body_schema = self._resolve_dto_to_schema(dto_type, imports, module_src, depth=0)
                    if body_schema:
                        result["body"] = body_schema
                continue

            # Check for @Valid (query object binding, no @RequestBody)
            if "@Valid" in param or "@Validated" in param:
                # Extract the DTO type
                type_match = re.search(r'(?:@\w+\s+)*([\w<>]+)\s+(\w+)\s*$', param)
                if type_match:
                    dto_type = type_match.group(1)
                    dto_name = type_match.group(2)
                    # This is a query object - expand its fields as query params
                    query_fields = self._resolve_dto_to_query_params(dto_type, imports, module_src)
                    if query_fields:
                        result["query"].extend(query_fields)
                    continue

            # Simple parameter (no annotation, like Long memberId)
            type_match = re.search(r'([\w<>]+)\s+(\w+)\s*$', param)
            if type_match:
                java_type = type_match.group(1)
                name = type_match.group(2)
                # Skip non-model types
                if java_type in ("String", "Long", "long", "Integer", "int", "Boolean", "boolean"):
                    desc = self._extract_param_javadoc(content, method_pos, name)
                    result["query"].append(ApiParam(name=name, required=0, desc=desc))

        return result

    def _split_params(self, params_str: str) -> list:
        """Split parameters by comma, respecting generics."""
        params = []
        depth = 0
        current = ""
        for ch in params_str:
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            if ch == "," and depth == 0:
                params.append(current)
                current = ""
            else:
                current += ch
        if current.strip():
            params.append(current)
        return params

    def _extract_param_name(self, param: str) -> str:
        """Extract parameter name from a parameter declaration."""
        # Try @RequestParam("name") first
        m = re.search(r'@RequestParam\s*\(\s*"([^"]*)"', param)
        if m:
            return m.group(1)
        m = re.search(r'@PathVariable\s*\(\s*"([^"]*)"', param)
        if m:
            return m.group(1)
        # Fall back to variable name
        m = re.search(r'(\w+)\s*$', param.strip())
        return m.group(1) if m else ""

    def _is_param_required(self, param: str) -> bool:
        """Check if @RequestParam is required."""
        if "required = false" in param or "required=false" in param:
            return False
        return True

    def _extract_param_javadoc(self, content: str, method_pos: int, param_name: str) -> str:
        """Extract @param description from Javadoc."""
        # Find the Javadoc before the method
        before = content[:method_pos]
        doc_end = before.rfind("*/")
        if doc_end == -1:
            return ""
        doc_start = before.rfind("/**", 0, doc_end)
        if doc_start == -1:
            return ""
        doc = content[doc_start:doc_end + 2]
        # Search for @param name description
        m = re.search(r'@param\s+' + re.escape(param_name) + r'\s+(.+?)(?:\n|\*\/)', doc)
        return m.group(1).strip() if m else ""

    def _resolve_return_type(self, return_type: str, imports: dict, module_src: Path) -> dict:
        """Resolve return type to JSON Schema."""
        return_type = return_type.strip()

        # Unwrap WrapperResp<T> (以及 WRAPPER_RESP_TYPES 里配置的其它包装类)
        wrapper_match = re.match(r'([\w.]+)\s*<\s*(.+?)\s*>$', return_type)
        if wrapper_match and wrapper_match.group(1).split(".")[-1] in WRAPPER_RESP_TYPES:
            inner = wrapper_match.group(2).strip()
            inner_schema = self._resolve_type_to_schema(inner, imports, module_src, depth=0)

            # Decide what `data` field should be:
            # - None / empty {}  -> void or unresolved DTO -> mark as "no data" but keep the property
            # - real schema      -> use it
            if not inner_schema:
                data_field = {"type": "object", "description": "无返回数据（或 DTO 解析失败，请检查 Service 返回类型）"}
            else:
                data_field = inner_schema

            schema = {
                "type": "object",
                "title": "WrapperResp",
                "properties": {
                    "code": {"type": "integer", "description": "状态码"},
                    "message": {"type": "string", "description": "提示信息"},
                    "data": data_field,
                    "time": {"type": "integer", "description": "响应时间戳"},
                },
                "required": ["code", "message"]
            }
            return schema

        # Direct type (no wrapper)
        schema = self._resolve_type_to_schema(return_type, imports, module_src, depth=0)
        return schema if schema else {}

    def _resolve_type_to_schema(self, java_type: str, imports: dict, module_src: Path, depth: int = 0) -> dict:
        """Convert a Java type to JSON Schema."""
        if depth > 5:
            return {"type": "object", "description": "递归深度超限"}

        java_type = java_type.strip()

        # void/Void -> return SENTINEL so callers can distinguish "no data" from "empty object"
        if java_type in ("void", "Void"):
            return None

        # PageDataResp<T> (以及 PAGE_RESP_TYPES 里配置的其它分页包装类)
        page_match = re.match(r'([\w.]+)\s*<\s*(.+?)\s*>$', java_type)
        if page_match and page_match.group(1).split(".")[-1] in PAGE_RESP_TYPES:
            inner_type = page_match.group(2).strip()
            item_schema = self._resolve_type_to_schema(inner_type, imports, module_src, depth)
            item_field = item_schema if item_schema else {"type": "object", "description": "未解析到具体类型"}
            return {
                "type": "object",
                "title": "PageDataResp",
                "properties": {
                    "totalCount": {"type": "integer", "description": "记录总条数"},
                    "data": {
                        "type": "array",
                        "items": item_field,
                        "description": "数据体"
                    }
                }
            }

        # List<T>
        list_match = re.match(r'List\s*<\s*(.+?)\s*>$', java_type)
        if list_match:
            inner_type = list_match.group(1).strip()
            item_schema = self._resolve_type_to_schema(inner_type, imports, module_src, depth)
            item_field = item_schema if item_schema else {"type": "object", "description": "未解析到具体类型"}
            return {
                "type": "array",
                "items": item_field
            }

        # Map<K, V>
        map_match = re.match(r'Map\s*<.*>$', java_type)
        if map_match:
            return {"type": "object", "description": "Map"}

        # Set<T>
        set_match = re.match(r'Set\s*<\s*(.+?)\s*>$', java_type)
        if set_match:
            inner_type = set_match.group(1).strip()
            item_schema = self._resolve_type_to_schema(inner_type, imports, module_src, depth)
            item_field = item_schema if item_schema else {"type": "object", "description": "未解析到具体类型"}
            return {
                "type": "array",
                "items": item_field
            }

        # Primitive/wrapper types
        if java_type in self.TYPE_MAP:
            schema = {"type": self.TYPE_MAP[java_type]}
            if java_type in self.FORMAT_MAP:
                schema["format"] = self.FORMAT_MAP[java_type]
            return schema

        # Custom DTO/VO class -> resolve fields
        result = self._resolve_dto_class(java_type, imports, module_src, depth)
        # If DTO resolution failed (returned empty or generic), keep None so caller can warn
        if not result or (result.get("type") == "object" and not result.get("properties") and not result.get("description")):
            return None
        return result

    def _resolve_dto_class(self, class_name: str, imports: dict, module_src: Path, depth: int) -> dict:
        """Find and parse a DTO class, returning JSON Schema."""
        if depth > 5:
            return {"type": "object", "description": "递归深度超限"}

        # Check cache
        if class_name in self._dto_cache:
            cached = self._dto_cache[class_name]
            if cached is not None:
                return dict(cached)
            return {"type": "object"}

        # Mark as being resolved (prevent infinite recursion)
        self._dto_cache[class_name] = None

        # Find the class file
        file_path = self._find_class_file(class_name, imports, module_src)
        if not file_path:
            self._dto_cache[class_name] = {"type": "object", "description": class_name}
            return self._dto_cache[class_name]

        content = self._read_file(file_path)
        if not content:
            self._dto_cache[class_name] = {"type": "object", "description": class_name}
            return self._dto_cache[class_name]

        # Parse the DTO class fields
        fields = self._parse_dto_fields(content, imports, module_src, depth)

        properties = {}
        required = []
        for f in fields:
            if not f.name:
                continue
            prop_schema = self._field_to_schema(f, imports, module_src, depth)
            properties[f.name] = prop_schema
            if f.required:
                required.append(f.name)

        # 继承支持：递归解析父类字段并合并，子类同名字段优先
        parent_name = self._extract_superclass(content)
        if parent_name:
            file_imports = self._extract_imports(content)
            merged_imports = {**imports, **file_imports}
            parent_schema = self._resolve_dto_class(parent_name, merged_imports, module_src, depth + 1)
            merged_properties = dict(parent_schema.get("properties") or {})
            merged_properties.update(properties)
            properties = merged_properties
            parent_required = parent_schema.get("required") or []
            required = [n for n in parent_required if n not in required] + required

        schema = {"type": "object", "title": class_name}
        if properties:
            schema["properties"] = properties
        if required:
            schema["required"] = required

        self._dto_cache[class_name] = schema
        return schema

    def _find_class_file(self, class_name: str, imports: dict, module_src: Path) -> Optional[Path]:
        """Find a Java class file by class name, using imports."""
        # Check if we have a cached location
        cache_key = (str(module_src), class_name)
        if cache_key in self._import_cache:
            return self._import_cache[cache_key] or None

        # Try import-based lookup
        full_pkg = imports.get(class_name, "")
        if full_pkg:
            # Convert package to path: com.ssy.lingxi.member.model.req.info.XxxReq
            # -> module_src/com/ssy/lingxi/member/model/req/info/XxxReq.java
            rel_path = full_pkg.replace(".", "/") + ".java"
            # module_src is like .../member-service/src/main/java
            candidate = module_src / rel_path
            if candidate.exists():
                self._import_cache[cache_key] = candidate
                return candidate
            # Try in -api module
            # module_src: .../member-service/src/main/java
            # 嵌套布局：.../member-service/member-service-api/src/main/java
            # 平铺布局：.../member-service-api/src/main/java（与 member-service 同级）
            service_root = module_src.parents[2] if len(module_src.parents) > 2 else module_src.parent
            api_name = service_root.name + "-api"
            for api_root in (service_root, service_root.parent):
                api_candidate = api_root / api_name / "src" / "main" / "java" / rel_path
                if api_candidate.exists():
                    self._import_cache[cache_key] = api_candidate
                    return api_candidate
            # Try in common module
            common_candidate = self.project_path / "common" / "src" / "main" / "java" / rel_path
            if common_candidate.exists():
                self._import_cache[cache_key] = common_candidate
                return common_candidate
            # Try in component modules
            comp_base = self.project_path / "component" / "base-spring-boot-starter" / "src" / "main" / "java"
            comp_candidate = comp_base / rel_path
            if comp_candidate.exists():
                self._import_cache[cache_key] = comp_candidate
                return comp_candidate

        # Fallback: search by class name in the project
        # This is slow but comprehensive - search in module and common
        search_dirs = [module_src, self.project_path / "common" / "src" / "main" / "java"]
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for root, dirs, files in os.walk(search_dir):
                if f"{class_name}.java" in files:
                    found = Path(root) / f"{class_name}.java"
                    self._import_cache[cache_key] = found
                    return found

        self._import_cache[cache_key] = None
        return None

    def _parse_dto_fields(self, content: str, imports: dict, module_src: Path, depth: int) -> list:
        """Parse fields from a DTO class file."""
        fields = []

        # Update imports for this file
        file_imports = self._extract_imports(content)
        merged_imports = {**imports, **file_imports}

        # Find class body
        class_match = re.search(r'(?:public\s+)?class\s+\w+', content)
        if not class_match:
            return fields

        # Find fields: [annotations] [modifiers] type name;
        # Pattern: optional @annotations, then type + name + ;
        field_pattern = re.compile(
            r'((?:@\w+[^\n]*\n\s*)*)'  # Annotations (possibly multi-line)
            r'(?:private|protected|public)\s+'
            r'([\w<>]+)\s+'  # Type
            r'(\w+)\s*;'  # Name
        )

        for m in field_pattern.finditer(content):
            annotations_block = m.group(1) or ""
            field_type = m.group(2)
            field_name = m.group(3)

            # Skip serialVersionUID
            if field_name == "serialVersionUID":
                continue
            # Skip static fields
            if "static" in annotations_block:
                continue

            # Check if required
            required = bool(re.search(r'@(NotNull|NotBlank|NotEmpty|Positive)\b', annotations_block))

            # Extract Javadoc description
            field_pos = m.start()
            desc = self._extract_javadoc_field_desc(content, field_pos)

            # Resolve nested type
            field_schema_type = self._resolve_type_to_schema(field_type, merged_imports, module_src, depth + 1)

            api_field = ApiField(
                name=field_name,
                java_type=field_type,
                desc=desc,
                required=required,
                children=field_schema_type,
            )
            fields.append(api_field)

        return fields

    def _field_to_schema(self, f: ApiField, imports: dict, module_src: Path, depth: int) -> dict:
        """Convert an ApiField to a JSON Schema property."""
        schema = f.children if isinstance(f.children, dict) else {}
        if not schema:
            # Fallback to type mapping
            schema = self._resolve_type_to_schema(f.java_type, imports, module_src, depth + 1)
        if f.desc:
            schema["description"] = f.desc
        return schema

    def _resolve_dto_to_schema(self, dto_type: str, imports: dict, module_src: Path, depth: int = 0) -> dict:
        """Resolve a DTO type to JSON Schema (for request body)."""
        return self._resolve_type_to_schema(dto_type, imports, module_src, depth)

    def _resolve_dto_to_query_params(self, dto_type: str, imports: dict, module_src: Path) -> list:
        """Resolve a DTO type to a list of query parameters (for GET request object binding)."""
        file_path = self._find_class_file(dto_type, imports, module_src)
        if not file_path:
            return []

        content = self._read_file(file_path)
        if not content:
            return []

        file_imports = self._extract_imports(content)
        merged_imports = {**imports, **file_imports}
        fields = self._parse_dto_fields(content, merged_imports, module_src, 0)

        params = []
        for f in fields:
            if not f.name:
                continue
            params.append(ApiParam(
                name=f.name,
                required=1 if f.required else 0,
                desc=f.desc
            ))
        return params
