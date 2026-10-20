#!/usr/bin/env python3
"""
doc_generator.py - Generate frontend API documentation from YApi sync results.

Follows the template in templates/frontend-api-doc-template.md:
  1. New interfaces: table (YApi URL, path, description) + calling timing + response fields
  2. Modified interfaces: table + incremental params/response fields (diff old vs new)
  3. Business flow overview (ASCII diagram)

Output: docs/frontend-api/<name>文档.md
"""

import json
from pathlib import Path
from datetime import datetime


class DocGenerator:
    def __init__(self, server: str):
        self.server = server.rstrip("/")

    def generate(self, interfaces: list, output_dir: Path,
                 doc_name: str = "接口变更") -> str:
        """
        Generate frontend API doc.

        Args:
            interfaces: list of dicts, each with:
                - action: "new" | "updated"
                - iface: ApiInterface dataclass
                - yapi_id: int (YApi interface ID)
                - project_id: int (YApi project ID)
                - module: str (module name)
                - old_detail: dict (old YApi interface detail, for updated)
            output_dir: Path to docs/frontend-api/
            doc_name: filename without extension

        Returns: path to generated file
        """
        new_ifaces = [i for i in interfaces if i["action"] == "new"]
        updated_ifaces = [i for i in interfaces if i["action"] == "updated"]

        lines = []

        # Header
        modules = sorted(set(i.get("module", "") for i in interfaces if i.get("module")))
        module_str = " / ".join(modules) if modules else ""

        lines.append(f"# {doc_name}前端对接文档")
        lines.append("")
        lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        if module_str:
            lines.append(f"> 涉及模块：{module_str}")
        lines.append("")

        # Section 1: New interfaces
        if new_ifaces:
            lines.append("## 一、新增接口")
            lines.append("")
            for item in new_ifaces:
                lines.extend(self._format_new_interface(item))
                lines.append("---")
                lines.append("")

        # Section 2: Modified interfaces
        if updated_ifaces:
            lines.append("## 二、修改接口")
            lines.append("")
            for item in updated_ifaces:
                lines.extend(self._format_updated_interface(item))
                lines.append("---")
                lines.append("")

        # Section 3: Business flow
        all_ifaces = new_ifaces + updated_ifaces
        if all_ifaces:
            lines.append("## 三、业务流程总览")
            lines.append("")
            lines.append("```")
            lines.extend(self._generate_flow_diagram(all_ifaces))
            lines.append("```")
            lines.append("")

        if not new_ifaces and not updated_ifaces:
            lines.append("本期无接口变更。")

        # Write file
        content = "\n".join(lines)
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / f"{doc_name}文档.md"
        filepath.write_text(content, encoding="utf-8")
        return str(filepath)

    # ── New interface section ──────────────────────────────────────

    def _format_new_interface(self, item: dict) -> list:
        """Format a new interface section per template."""
        iface = item["iface"]
        yapi_id = item.get("yapi_id", "")
        project_id = item.get("project_id", "")
        yapi_url = f"{self.server}/project/{project_id}/interface/api/{yapi_id}"

        lines = []
        lines.append(f"### {iface.title}")
        lines.append("")
        lines.append("| 项目 | 内容 |")
        lines.append("|------|------|")
        lines.append(f"| **YApi 地址** | `{yapi_url}` |")
        lines.append(f"| **接口路径** | `{iface.method} {iface.path}` |")
        lines.append(f"| **所属分类** | _（待补充）_ |")
        lines.append(f"| **接口说明** | {iface.title} |")
        lines.append("")
        lines.append("- **调用时机：** _（待补充：前端在什么场景下调这个接口）_")
        lines.append("- **前置条件：** _（可选，如是否需要登录）_")
        lines.append("")

        # Important response fields (unwrap WrapperResp, list top-level data fields)
        res_fields = self._extract_response_fields(iface)
        if res_fields:
            lines.append("**出参重要字段：**")
            lines.append("")
            lines.append("| 字段 | 类型 | 说明 |")
            lines.append("|------|------|------|")
            for f in res_fields:
                lines.append(f"| {f['name']} | {f['type']} | {f['desc']} |")
            lines.append("")
        else:
            lines.append("- **出参重要字段：** _（无特定字段或待补充）_")
            lines.append("")

        return lines

    # ── Updated interface section ─────────────────────────────────

    def _format_updated_interface(self, item: dict) -> list:
        """Format an updated interface section with incremental fields."""
        iface = item["iface"]
        yapi_id = item.get("yapi_id", "")
        project_id = item.get("project_id", "")
        yapi_url = f"{self.server}/project/{project_id}/interface/api/{yapi_id}"
        old_detail = item.get("old_detail") or {}

        lines = []
        lines.append(f"### {iface.title}")
        lines.append("")
        lines.append("| 项目 | 内容 |")
        lines.append("|------|------|")
        lines.append(f"| **YApi 地址** | `{yapi_url}` |")
        lines.append(f"| **接口路径** | `{iface.method} {iface.path}` |")
        lines.append("")

        has_increment = False

        # Incremental query params
        old_query = old_detail.get("req_query", [])
        new_query = iface.req_query
        q_diff = self._diff_query_params(old_query, new_query)
        if q_diff["added"] or q_diff["changed"]:
            has_increment = True
            lines.append("**增量入参（Query）：**")
            lines.append("")
            lines.append("| 字段 | 类型 | 必填 | 说明 |")
            lines.append("|------|------|------|------|")
            for f in q_diff["added"]:
                lines.append(f"| {f['name']} | {f['type']} | {'是' if f['required'] else '否'} | {f['desc']} |")
            for f in q_diff["changed"]:
                lines.append(f"| {f['name']} | {f['type']} | {'是' if f['required'] else '否'} | {f['desc']} |")
            lines.append("")

        # Incremental request body
        old_req = self._parse_json(old_detail.get("req_body_other", ""))
        new_req = self._parse_json(iface.req_body_other)
        rb_diff = self._diff_schema_properties(old_req, new_req)
        if rb_diff["added"] or rb_diff["changed"]:
            has_increment = True
            lines.append("**增量入参（Body）：**")
            lines.append("")
            lines.append("| 字段 | 类型 | 必填 | 说明 |")
            lines.append("|------|------|------|------|")
            for f in rb_diff["added"]:
                lines.append(f"| {f['name']} | {f['type']} | {'是' if f['required'] else '否'} | {f['desc']} |")
            for f in rb_diff["changed"]:
                lines.append(f"| {f['name']} | {f['type']} | {'是' if f['required'] else '否'} | {f['desc']} |")
            lines.append("")

        # Incremental response body
        old_res = self._parse_json(old_detail.get("res_body", ""))
        new_res = self._parse_json(iface.res_body)
        res_diff = self._diff_response_data(old_res, new_res)
        if res_diff["added"] or res_diff["changed"]:
            has_increment = True
            lines.append("**增量出参：**")
            lines.append("")
            lines.append("| 字段 | 类型 | 说明 |")
            lines.append("|------|------|------|")
            for f in res_diff["added"]:
                lines.append(f"| {f['name']} | {f['type']} | {f['desc']} |")
            for f in res_diff["changed"]:
                lines.append(f"| {f['name']} | {f['type']} | {f['desc']} |")
            lines.append("")

        if not has_increment:
            lines.append("_（入参出参结构无变化，仅标题/描述更新）_")
            lines.append("")

        # Behavior changes placeholder
        lines.append("**行为变化：** _（待补充：描述逻辑变化，入参出参不变但行为改变时使用）_")
        lines.append("")

        return lines

    # ── Response field extraction ──────────────────────────────────

    def _extract_response_fields(self, iface) -> list:
        """Extract top-level response fields from ApiInterface (unwrap WrapperResp)."""
        if not iface.res_body:
            return []
        schema = self._parse_json(iface.res_body)
        if not schema:
            return []

        # Unwrap WrapperResp -> data
        props = schema.get("properties", {})
        data = props.get("data", {})
        data_props = data.get("properties", {})

        fields = []
        for name, prop in data_props.items():
            field_type = self._schema_type_str(prop)
            desc = prop.get("description", "")
            fields.append({"name": name, "type": field_type, "desc": desc})

        return fields

    # ── Diff helpers ───────────────────────────────────────────────

    def _diff_query_params(self, old_query: list, new_query: list) -> dict:
        """Diff two query parameter lists."""
        old_map = {}
        for q in (old_query or []):
            if isinstance(q, dict):
                old_map[q.get("name", "")] = q

        new_map = {}
        for q in (new_query or []):
            if hasattr(q, "name"):
                new_map[q.name] = {"name": q.name, "required": q.required, "desc": q.desc}
            elif isinstance(q, dict):
                new_map[q.get("name", "")] = q

        added = []
        changed = []

        for name, nq in new_map.items():
            if name not in old_map:
                added.append(self._query_to_field(nq))
            else:
                oq = old_map[name]
                if str(oq.get("desc", "")) != str(nq.get("desc", "")) or \
                   str(oq.get("required", "0")) != str(nq.get("required", 0)):
                    changed.append(self._query_to_field(nq))

        return {"added": added, "changed": changed}

    def _diff_schema_properties(self, old_schema: dict, new_schema: dict) -> dict:
        """Diff two JSON schemas' top-level properties."""
        old_props = old_schema.get("properties", {}) if old_schema else {}
        new_props = new_schema.get("properties", {}) if new_schema else {}
        new_required = set(new_schema.get("required", [])) if new_schema else set()

        added = []
        changed = []

        for name, prop in new_props.items():
            if name not in old_props:
                added.append(self._prop_to_field(name, prop, name in new_required))
            elif self._prop_differs(prop, old_props[name]):
                changed.append(self._prop_to_field(name, prop, name in new_required))

        return {"added": added, "changed": changed}

    def _diff_response_data(self, old_res: dict, new_res: dict) -> dict:
        """Diff response schemas, unwrapping WrapperResp and PageDataResp."""
        old_data = self._unwrap_wrapper_resp(old_res)
        new_data = self._unwrap_wrapper_resp(new_res)

        # 1. Diff top-level properties of the data object (e.g. totalCount)
        result = self._diff_schema_properties(old_data, new_data)

        # 2. If data is PageDataResp, also diff array items' properties
        old_items = self._extract_array_items(old_data)
        new_items = self._extract_array_items(new_data)
        if old_items or new_items:
            item_diff = self._diff_schema_properties(old_items, new_items)
            result["added"].extend(item_diff["added"])
            result["changed"].extend(item_diff["changed"])

        return result

    def _unwrap_wrapper_resp(self, schema: dict) -> dict:
        """Unwrap WrapperResp to get the data schema."""
        if not schema:
            return {}
        props = schema.get("properties", {})
        if "data" in props:
            return props["data"]
        return schema

    def _extract_array_items(self, schema: dict) -> dict:
        """Extract array items schema from a PageDataResp-like structure.

        PageDataResp has: { properties: { totalCount: ..., data: { type: array, items: {...} } } }
        Returns the items schema, or empty dict if not found.
        """
        if not schema:
            return {}
        props = schema.get("properties", {})
        data_prop = props.get("data", {})
        if data_prop.get("type") == "array":
            return data_prop.get("items", {})
        return {}

    # ── Property/field helpers ─────────────────────────────────────

    def _query_to_field(self, q: dict) -> dict:
        """Convert a query param dict to a field dict."""
        req = q.get("required", 0)
        if isinstance(req, str):
            required = req in ("1", "true", "True")
        else:
            required = bool(req)
        return {
            "name": q.get("name", ""),
            "type": "string",
            "required": required,
            "desc": q.get("desc", ""),
        }

    def _prop_to_field(self, name: str, prop: dict, required: bool) -> dict:
        """Convert a JSON schema property to a field dict."""
        return {
            "name": name,
            "type": self._schema_type_str(prop),
            "desc": prop.get("description", ""),
            "required": required,
        }

    def _schema_type_str(self, prop: dict) -> str:
        """Get a human-readable type string from a JSON schema property."""
        if not prop:
            return "object"
        field_type = prop.get("type", "object")
        if field_type == "array":
            items = prop.get("items", {})
            inner = self._schema_type_str(items)
            field_type = f"array&lt;{inner}&gt;"
        elif prop.get("title") and prop["title"] != field_type:
            field_type = f"{field_type}({prop['title']})"
        elif field_type == "string" and prop.get("format"):
            field_type = f"string({prop['format']})"
        return field_type

    def _prop_differs(self, new_prop: dict, old_prop: dict) -> bool:
        """Check if a property has meaningfully changed."""
        if new_prop.get("type") != old_prop.get("type"):
            return True
        if new_prop.get("description", "") != old_prop.get("description", ""):
            return True
        if new_prop.get("format") != old_prop.get("format"):
            return True
        return False

    def _parse_json(self, json_str) -> dict:
        """Parse a JSON string, returning empty dict on failure."""
        if not json_str:
            return {}
        if isinstance(json_str, dict):
            return json_str
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    # ── Flow diagram ───────────────────────────────────────────────

    def _generate_flow_diagram(self, interfaces: list) -> list:
        """Generate a simple ASCII flow diagram."""
        lines = ["  前端"]
        for item in interfaces:
            iface = item["iface"]
            module = item.get("module", "")
            prefix = f"[{module}] " if module else ""
            lines.append("    │")
            lines.append(f"    ├──> {iface.method} {iface.path}")
            lines.append(f"    │    └── {prefix}{iface.title}")
        lines.append("    │")
        lines.append("    └──> 完成")
        return lines
