#!/usr/bin/env python3
"""
yapi_sync.py - Main YApi sync orchestrator

Usage:
  python yapi_sync.py <project_path> [--dry-run] [--module=member-service] [--base=master]

Workflow:
  1. Read .easy.api.yml for YApi server and module tokens
  2. Git status to find changed (uncommitted) Controller files
  3. Filter to web/ and mobile/ controllers (skip feign/)
  4. Group by module, parse each Controller to extract API definitions
  5. Compare with YApi existing interfaces (by method + path)
  6. Create new / Update changed / Skip unchanged
  7. Print sync report
"""

import sys
import os
import subprocess
import json
import argparse
from pathlib import Path
from dataclasses import asdict

# 编码兜底：Python 3.7+ 下把 stdout 切成 UTF-8，避免中文乱码/报错
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 依赖自检：缺依赖时给出明确安装提示，而不是一堆 traceback
try:
    import yaml  # noqa: F401  (config_reader 依赖)
    import requests  # noqa: F401  (yapi_client 依赖)
except ImportError as e:
    sys.stderr.write(
        "\n[缺少依赖] 请先安装 Python 依赖：\n"
        "    pip install -r requirements.txt\n"
        f"错误信息：{e}\n\n"
    )
    sys.exit(1)

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from config_reader import ConfigReader
from java_parser import JavaParser, ApiInterface
from yapi_client import YApiClient


def get_changed_files(project_path: str, base_branch: str = None) -> list:
    """
    Get all changed files (uncommitted).
    If base_branch is provided, compares against that branch.
    Otherwise, gets all uncommitted changes (staged + unstaged + untracked).
    """
    changed = set()

    if base_branch:
        # Compare against a branch
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
            capture_output=True, text=True,
            cwd=project_path
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    changed.add(line.strip())

        # Also get uncommitted changes on top of HEAD
        result2 = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True,
            cwd=project_path
        )
        if result2.returncode == 0:
            for line in result2.stdout.strip().split("\n"):
                if line.strip():
                    changed.add(line.strip())
    else:
        # All uncommitted changes (staged + unstaged vs HEAD)
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True,
            cwd=project_path
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    changed.add(line.strip())

        # Also get staged-only changes
        result_staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True,
            cwd=project_path
        )
        if result_staged.returncode == 0:
            for line in result_staged.stdout.strip().split("\n"):
                if line.strip():
                    changed.add(line.strip())

    # Get untracked files (new files not yet added)
    result_untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
        cwd=project_path
    )
    if result_untracked.returncode == 0:
        for line in result_untracked.stdout.strip().split("\n"):
            if line.strip():
                changed.add(line.strip())

    return sorted(changed)


def is_controller(file_path: str) -> bool:
    """Check if a file is a Controller file."""
    return file_path.endswith("Controller.java") or file_path.endswith("Controller2.java")


def is_web_or_mobile(file_path: str) -> bool:
    """Check if a controller is in web/ or mobile/ directory (not feign/)."""
    parts = file_path.replace("\\", "/").split("/")
    for part in parts:
        if part == "feign":
            return False
    # Check if it's in controller/web/ or controller/mobile/
    return "/controller/web/" in file_path.replace("\\", "/") or \
           "/controller/mobile/" in file_path.replace("\\", "/") or \
           ("/controller/" in file_path.replace("\\", "/") and "feign" not in file_path.replace("\\", "/").lower())


def get_module_name(file_path: str) -> str:
    """Extract module name from file path.
    e.g., member-service/src/.../XxxController.java -> member-service
    """
    parts = file_path.replace("\\", "/").split("/")
    for part in parts:
        if part.endswith("-service"):
            return part
    return ""


def find_interface_match(iface: dict, existing: list) -> dict:
    """Find a matching interface in YApi by (method, path)."""
    method = iface.get("method", "").upper()
    path = iface.get("path", "")
    for ex in existing:
        if ex.get("method", "").upper() == method and ex.get("path", "") == path:
            return ex
    return None


def interface_needs_update(new_iface: dict, existing_detail: dict) -> bool:
    """Check if an existing interface needs updating."""
    # Compare key fields
    if new_iface.get("title", "") != existing_detail.get("title", ""):
        return True
    new_body = new_iface.get("req_body_other", "")
    old_body = existing_detail.get("req_body_other", "") or ""
    if new_body and new_body != old_body:
        return True
    new_res = new_iface.get("res_body", "")
    old_res = existing_detail.get("res_body", "") or ""
    if new_res and new_res != old_res:
        return True
    # GET 接口的 query 参数（历史遗漏了 req_query 的 diff，导致入参变化不同步）
    if _normalize_query(new_iface.get("req_query", [])) != _normalize_query(existing_detail.get("req_query", []) or []):
        return True
    return False


def _normalize_query(query: list) -> list:
    """将 YApi/脚本的 req_query 归一化为可比较的 (name, desc) 列表，忽略 YApi 额外字段。"""
    result = []
    for q in query or []:
        name = q.get("name", "") or ""
        desc = q.get("desc", "") or ""
        result.append((name, desc))
    return result


def serialize_iface(iface: ApiInterface) -> dict:
    """Convert ApiInterface dataclass to dict for YApi API."""
    return {
        "method": iface.method,
        "title": iface.title,
        "path": iface.path,
        "desc": iface.desc,
        "req_query": [asdict(q) for q in iface.req_query],
        "req_params": [asdict(p) for p in iface.req_params],
        "req_body_other": iface.req_body_other,
        "req_body_type": iface.req_body_type,
        "res_body": iface.res_body,
        "res_body_type": iface.res_body_type,
    }


def sync_module(config: ConfigReader, parser: JavaParser, module_name: str,
                controller_files: list, dry_run: bool = False) -> dict:
    """Sync one module's controllers to YApi.

    Returns report dict with:
      - new/updated/skipped/errors counts
      - project_id (YApi project ID)
      - interfaces: list of entries with action, iface, yapi_id, old_detail, etc.
    """
    token = config.get_token(module_name)
    if not token:
        return {"error": f"No YApi token for module: {module_name}"}

    print(f"\n{'='*60}")
    print(f"Module: {module_name}")
    print(f"Controllers changed: {len(controller_files)}")
    print(f"{'='*60}")

    # Parse all changed controllers
    all_interfaces = []
    for file_rel in controller_files:
        file_path = Path(config.project_path) / file_rel
        if not file_path.exists():
            print(f"  Skip (not found): {file_rel}")
            continue
        print(f"  Parsing: {file_rel}")
        interfaces = parser.parse_controller(str(file_path))
        for iface in interfaces:
            print(f"    Found: {iface.method} {iface.path} - {iface.title}")
        all_interfaces.extend(interfaces)

    if not all_interfaces:
        print("  No interfaces found in changed controllers.")
        return {"new": 0, "updated": 0, "skipped": 0, "errors": 0,
                "project_id": 0, "interfaces": []}

    # Connect to YApi
    print(f"\n  Connecting to YApi ({config.server})...")
    client = YApiClient(config.server, token)
    existing = client.list_interfaces()
    project_id = client.project_id or 0
    print(f"  YApi project_id={project_id}, {len(existing)} existing interfaces")

    # Sync
    report = {
        "new": 0, "updated": 0, "skipped": 0, "errors": 0,
        "project_id": project_id,
        "interfaces": [],
    }

    for iface in all_interfaces:
        iface_dict = serialize_iface(iface)
        match = find_interface_match(iface_dict, existing)

        # Common entry fields
        entry = {
            "action": None,
            "method": iface.method,
            "path": iface.path,
            "title": iface.title,
            "file": iface.controller_file,
            "iface": iface,
            "yapi_id": None,
            "project_id": project_id,
            "module": module_name,
            "old_detail": None,
        }

        if match is None:
            # New interface
            if dry_run:
                print(f"  [DRY-RUN] NEW: {iface.method} {iface.path} - {iface.title}")
                report["new"] += 1
                entry["action"] = "new"
            else:
                result = client.add_interface(iface_dict)
                if result.get("errcode") == 0:
                    data = result.get("data", {})
                    yapi_id = data.get("_id") or data.get("id")
                    entry["yapi_id"] = yapi_id
                    print(f"  + NEW: {iface.method} {iface.path} - {iface.title} (id={yapi_id})")
                    report["new"] += 1
                    entry["action"] = "new"
                else:
                    print(f"  ! ERROR (add): {iface.method} {iface.path} - {result.get('errmsg', 'unknown')}")
                    report["errors"] += 1
                    entry["action"] = "error"
        else:
            # Existing - check if needs update
            entry["yapi_id"] = match.get("_id")
            if dry_run:
                print(f"  [DRY-RUN] EXISTS: {iface.method} {iface.path} - {iface.title}")
                report["skipped"] += 1
                entry["action"] = "skipped"
            else:
                # Get details to compare
                detail = client.get_interface_detail(match["_id"])
                if detail.get("errcode") == 0:
                    detail_data = detail.get("data", {})
                    entry["old_detail"] = detail_data
                    if interface_needs_update(iface_dict, detail_data):
                        iface_dict["catid"] = match.get("catid", 0)
                        result = client.save_interface(match["_id"], iface_dict)
                        if result.get("errcode") == 0:
                            print(f"  ~ UPD: {iface.method} {iface.path} - {iface.title}")
                            report["updated"] += 1
                            entry["action"] = "updated"
                        else:
                            print(f"  ! ERROR (save): {iface.method} {iface.path} - {result.get('errmsg', 'unknown')}")
                            report["errors"] += 1
                            entry["action"] = "error"
                    else:
                        print(f"  = SKIP: {iface.method} {iface.path} - {iface.title}")
                        report["skipped"] += 1
                        entry["action"] = "skipped"
                else:
                    print(f"  ! ERROR (get): {iface.method} {iface.path}")
                    report["errors"] += 1
                    entry["action"] = "error"

        report["interfaces"].append(entry)

    return report


def main():
    parser = argparse.ArgumentParser(description="Sync changed Java Controller interfaces to YApi")
    parser.add_argument("project_path", help="Path to the project root")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be synced without making changes")
    parser.add_argument("--module", default=None, help="Only sync a specific module (e.g., member-service)")
    parser.add_argument("--base", default=None, help="Base branch for git diff (default: uncommitted changes)")
    parser.add_argument("--doc", action="store_true", help="Generate frontend API doc after sync")
    parser.add_argument("--doc-name", default=None, help="Document name (filename without extension)")
    parser.add_argument("--config", default=None, help="Path to .easy.api.yml (default: <project_path>/.easy.api.yml)")
    args = parser.parse_args()

    project_path = os.path.abspath(args.project_path)
    print(f"Project: {project_path}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'SYNC'}")
    if args.base:
        print(f"Base branch: {args.base}")
    else:
        print("Base: uncommitted changes (staged + unstaged + untracked)")
    if args.doc:
        print("Doc generation: ENABLED")

    # 1. Read config
    print("\n--- Reading .easy.api.yml ---")
    config = ConfigReader(project_path, config_file=args.config)
    print(f"YApi server: {config.server}")
    print(f"Modules with tokens: {len(config.module_tokens)}")

    # 2. Get changed files
    print("\n--- Finding changed Controller files ---")
    changed_files = get_changed_files(project_path, args.base)
    controller_files = [f for f in changed_files if is_controller(f)]
    controller_files = [f for f in controller_files if is_web_or_mobile(f)]

    if args.module:
        controller_files = [f for f in controller_files if get_module_name(f) == args.module]

    if not controller_files:
        print("No changed Controller files found.")
        print("\nHint: Make sure you have uncommitted changes to Controller files in web/ or mobile/ directories.")
        return

    print(f"Found {len(controller_files)} changed Controller file(s):")
    for f in controller_files:
        print(f"  - {f}")

    # 3. Group by module
    modules = {}
    for f in controller_files:
        mod = get_module_name(f)
        if mod:
            if mod not in modules:
                modules[mod] = []
            modules[mod].append(f)

    # 4. Sync each module
    parser_instance = JavaParser(project_path, config)
    total_report = {"new": 0, "updated": 0, "skipped": 0, "errors": 0, "modules": {}}

    for module_name, files in modules.items():
        report = sync_module(config, parser_instance, module_name, files, args.dry_run)
        total_report["new"] += report.get("new", 0)
        total_report["updated"] += report.get("updated", 0)
        total_report["skipped"] += report.get("skipped", 0)
        total_report["errors"] += report.get("errors", 0)
        total_report["modules"][module_name] = report

    # 5. Print summary
    print(f"\n{'='*60}")
    print("SYNC SUMMARY")
    print(f"{'='*60}")
    print(f"  New:      {total_report['new']}")
    print(f"  Updated:  {total_report['updated']}")
    print(f"  Skipped:  {total_report['skipped']}")
    print(f"  Errors:   {total_report['errors']}")
    if config.server:
        print(f"\nYApi: {config.server}")

    # 6. Generate frontend API doc (if requested)
    if args.doc and not args.dry_run:
        print("\n--- Generating Frontend API Doc ---")
        try:
            from doc_generator import DocGenerator
            doc_gen = DocGenerator(config.server)

            # Collect all new + updated interfaces across modules
            all_doc_interfaces = []
            for mod_name, mod_report in total_report["modules"].items():
                if isinstance(mod_report, dict):
                    for entry in mod_report.get("interfaces", []):
                        if entry.get("action") in ("new", "updated"):
                            all_doc_interfaces.append(entry)

            if all_doc_interfaces:
                output_dir = Path(project_path) / "docs" / "frontend-api"
                doc_name = args.doc_name or "接口变更"
                filepath = doc_gen.generate(
                    interfaces=all_doc_interfaces,
                    output_dir=output_dir,
                    doc_name=doc_name,
                )
                print(f"  Document generated: {filepath}")
            else:
                print("  No new/updated interfaces to document.")
        except Exception as e:
            print(f"  Doc generation failed: {e}")

    # Output JSON for programmatic use (strip non-serializable fields)
    print("\n--- JSON Report ---")
    json_report = _make_json_serializable(total_report)
    print(json.dumps(json_report, ensure_ascii=False, indent=2))


def _make_json_serializable(obj):
    """Recursively convert a report dict to JSON-serializable form."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "iface":
                # Replace full ApiInterface with summary
                if hasattr(v, "method"):
                    result[k] = {
                        "method": v.method,
                        "path": v.path,
                        "title": v.title,
                        "req_body_type": v.req_body_type,
                        "res_body_type": v.res_body_type,
                    }
                else:
                    result[k] = str(v)
            elif k == "old_detail":
                result[k] = "(detail data)"  # Omit large detail from JSON
            else:
                result[k] = _make_json_serializable(v)
        return result
    elif isinstance(obj, list):
        return [_make_json_serializable(item) for item in obj]
    else:
        return obj


if __name__ == "__main__":
    main()
