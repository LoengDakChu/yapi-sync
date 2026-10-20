#!/usr/bin/env python3
"""
yapi_client.py - YApi Open API client

Endpoints:
  - GET  /api/interface/list?token=xxx&project_id=xxx&page=1&pagesize=100
  - POST /api/interface/add?token=xxx
  - POST /api/interface/save?token=xxx
  - GET  /api/interface/get?id=xxx&token=xxx
"""

import requests
import json
import time
from typing import Optional


class YApiClient:
    def __init__(self, server: str, token: str, project_id: int = None):
        self.server = server.rstrip("/")
        self.token = token
        self.project_id = project_id
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._retry_count = 3
        self._retry_delay = 1.0

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.server}{path}"
        params = params or {}
        params["token"] = self.token
        for attempt in range(self._retry_count):
            try:
                resp = self.session.get(url, params=params, timeout=30, verify=True)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < self._retry_count - 1:
                    time.sleep(self._retry_delay)
                else:
                    return {"errcode": -1, "errmsg": str(e)}

    def _post(self, path: str, data: dict = None) -> dict:
        url = f"{self.server}{path}"
        params = {"token": self.token}
        for attempt in range(self._retry_count):
            try:
                resp = self.session.post(url, params=params, json=data, timeout=30, verify=True)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < self._retry_count - 1:
                    time.sleep(self._retry_delay)
                else:
                    return {"errcode": -1, "errmsg": str(e)}

    def list_interfaces(self, page_size: int = 20) -> list:
        """List all interfaces in the project, handling pagination."""
        all_interfaces = []
        page = 1
        while True:
            params = {"page": page, "pagesize": page_size}
            if self.project_id:
                params["project_id"] = self.project_id
            result = self._get("/api/interface/list", params)
            if result.get("errcode") != 0:
                print(f"  Error listing interfaces: {result.get('errmsg', 'unknown')}")
                break
            data = result.get("data", {})
            interfaces = data.get("list", [])
            # count = total interfaces, total = total pages
            count = data.get("count", 0)

            if not self.project_id and interfaces:
                self.project_id = interfaces[0].get("project_id")

            all_interfaces.extend(interfaces)

            if len(all_interfaces) >= count or len(interfaces) == 0:
                break
            page += 1

        return all_interfaces

    def get_interface_detail(self, interface_id: int) -> dict:
        """Get detailed info for a single interface."""
        return self._get("/api/interface/get", {"id": interface_id})

    def add_interface(self, interface_data: dict) -> dict:
        """Create a new interface."""
        req_body_other = interface_data.get("req_body_other") or ""
        res_body = interface_data.get("res_body", "")
        data = {
            "method": interface_data.get("method", "GET"),
            "catid": interface_data.get("catid", 0),
            "title": interface_data.get("title", ""),
            "path": interface_data.get("path", ""),
            "project_id": interface_data.get("project_id", self.project_id),
            "status": "done",
            "desc": interface_data.get("desc", ""),
            "req_query": interface_data.get("req_query", []),
            "req_headers": interface_data.get("req_headers", []),
            "req_params": interface_data.get("req_params", []),
            "req_body_other": req_body_other or None,
            "req_body_type": interface_data.get("req_body_type") or "json",
            "req_body_is_json_schema": interface_data.get("req_body_is_json_schema", bool(req_body_other)),
            "res_body": res_body,
            "res_body_type": interface_data.get("res_body_type", "json"),
            "res_body_is_json_schema": interface_data.get("res_body_is_json_schema", bool(res_body)),
        }
        return self._post("/api/interface/add", data)

    def save_interface(self, interface_id: int, interface_data: dict) -> dict:
        """Update an existing interface.

        必须带上 project_id 与 res_body_is_json_schema / req_body_is_json_schema：
        - 缺 project_id 会让 YApi 保存成功但 res_body 实际未落库（静默失败）；
        - 缺 schema 标记会让 YApi 把 res_body/req_body_other 当原始示例而非 JSON Schema 解析。
        """
        req_body_other = interface_data.get("req_body_other") or ""
        res_body = interface_data.get("res_body", "")
        data = {
            "id": interface_id,
            "method": interface_data.get("method", "GET"),
            "catid": interface_data.get("catid", 0),
            "title": interface_data.get("title", ""),
            "path": interface_data.get("path", ""),
            "project_id": interface_data.get("project_id", self.project_id),
            "status": "done",
            "desc": interface_data.get("desc", ""),
            "req_query": interface_data.get("req_query", []),
            "req_headers": interface_data.get("req_headers", []),
            "req_params": interface_data.get("req_params", []),
            "req_body_other": req_body_other or None,
            "req_body_type": interface_data.get("req_body_type") or "json",
            "req_body_is_json_schema": interface_data.get("req_body_is_json_schema", bool(req_body_other)),
            "res_body": res_body,
            "res_body_type": interface_data.get("res_body_type", "json"),
            "res_body_is_json_schema": interface_data.get("res_body_is_json_schema", bool(res_body)),
        }
        return self._post("/api/interface/save", data)

    def get_project_info(self) -> dict:
        """Get project info including categories."""
        if not self.project_id:
            return {}
        return self._get("/api/project/get", {"id": self.project_id})

    def get_categories(self) -> list:
        """Get project categories (menu groups)."""
        info = self.get_project_info()
        if info.get("errcode") == 0:
            return info.get("data", {}).get("cat", [])
        return []
