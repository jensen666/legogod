# -*- coding: utf-8 -*-
"""公开夹具清单加载器（单一事实源）。

公开语料的消费方（测试与工具）统一经本模块取路径与内容：
- 清单 `test/fixtures/public-fixtures.json` 是唯一索引，禁止 glob 或硬编码夹具路径；
- 清单缺失、条目缺失、文件大小或 SHA-256 不符一律抛 AssertionError（测试即硬失败），
  不允许 skip / continue / 空集合通过；
- 只读 `test/fixtures/public/` 下的已登记夹具，不读取 `artifacts/` 真实运行产物。

字段与判定口径见 docs/开源整改/02-语料审计.md 第 7.2 节：
`id/path/type/size/sha256/source/license/consumers/required`，`type` 取
`design-plan` / `model` / `solution` / `baseline`。
"""
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "test", "fixtures", "public-fixtures.json")
PUBLIC_ROOT = os.path.join(ROOT, "test", "fixtures", "public")
REQUIRED_KEYS = ("id", "path", "type", "size", "sha256", "source", "license",
                 "consumers", "required")
FIXTURE_TYPES = ("design-plan", "model", "solution", "baseline", "history-corpus")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail(message):
    """统一硬失败出口：清单/夹具问题必须让调用方失败，不能被跳过。"""
    raise AssertionError(message)


def sha256_file(path):
    """返回文件字节的 SHA-256（十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_path(rel_path):
    """把清单中的仓库相对路径解析为绝对路径，并阻断越出公开夹具目录的路径。"""
    rel = str(rel_path or "").replace("\\", "/")
    if not rel.startswith("test/fixtures/public/") or ".." in rel.split("/"):
        _fail("清单路径必须位于 test/fixtures/public/ 下：%r" % (rel_path,))
    abs_path = os.path.normpath(os.path.join(ROOT, *rel.split("/")))
    root_norm = os.path.normpath(PUBLIC_ROOT) + os.sep
    if not abs_path.startswith(root_norm):
        _fail("清单路径越出公开夹具目录：%r" % (rel_path,))
    return abs_path


def load_manifest():
    """读取并校验清单结构，返回 {schemaVersion, note, entries, ...}。

    任何结构问题直接 AssertionError；清单条目本身在这里不做文件校验，
    由 verify_entry / verify_all 完成。
    """
    if not os.path.isfile(MANIFEST):
        _fail("公开夹具清单缺失：%s" % os.path.relpath(MANIFEST, ROOT))
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        _fail("公开夹具清单不是合法 JSON：%s" % e)
    if not isinstance(data, dict):
        _fail("公开夹具清单顶层必须是对象")
    if data.get("schemaVersion") != 1:
        _fail("公开夹具清单 schemaVersion 必须为 1")
    if not isinstance(data.get("note"), str) or not data["note"].strip():
        _fail("公开夹具清单缺少 note 来源/处理说明")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        _fail("公开夹具清单 entries 缺失或为空（禁止空集通过）")
    seen_ids, seen_paths = set(), set()
    for index, entry in enumerate(entries):
        where = "entries[%d]" % index
        if not isinstance(entry, dict):
            _fail("%s 必须是对象" % where)
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        if missing:
            _fail("%s 缺少字段：%s" % (where, ", ".join(missing)))
        fixture_id = entry["id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            _fail("%s.id 必须是非空字符串" % where)
        if fixture_id in seen_ids:
            _fail("清单 id 重复：%s" % fixture_id)
        seen_ids.add(fixture_id)
        path_key = str(entry["path"]).replace("\\", "/")
        if path_key in seen_paths:
            _fail("清单 path 重复：%s" % entry["path"])
        seen_paths.add(path_key)
        if entry["type"] not in FIXTURE_TYPES:
            _fail("%s.type 非法：%r" % (where, entry["type"]))
        if not isinstance(entry["size"], int) or entry["size"] <= 0:
            _fail("%s.size 必须是正整数" % where)
        if not isinstance(entry["sha256"], str) or not _SHA256_RE.match(entry["sha256"]):
            _fail("%s.sha256 必须是 64 位小写十六进制" % where)
        if not isinstance(entry["required"], bool):
            _fail("%s.required 必须是布尔值" % where)
        if not isinstance(entry["consumers"], list) or not entry["consumers"]:
            _fail("%s.consumers 必须是非空列表" % where)
        public_path(entry["path"])  # 只做路径合法性校验
    return data


def all_entries():
    """返回全部清单条目（已通过清单结构校验）。"""
    return list(load_manifest()["entries"])


def fixture_entries(type=None, required_only=True, consumer=None):
    """按类型/必需性/消费方筛出条目；不存在的组合返回空列表由调用方硬断言。"""
    out = []
    for entry in all_entries():
        if type is not None and entry["type"] != type:
            continue
        if required_only and not entry["required"]:
            continue
        if consumer is not None and consumer not in entry["consumers"]:
            continue
        out.append(entry)
    return out


def verify_entry(entry):
    """校验单个清单条目：文件存在、大小一致、SHA-256 一致；返回绝对路径。"""
    abs_path = public_path(entry["path"])
    if not os.path.isfile(abs_path):
        _fail("公开夹具缺失：%s" % entry["path"])
    size = os.path.getsize(abs_path)
    if size != entry["size"]:
        _fail("公开夹具大小不符：%s（清单 %d，实际 %d）"
              % (entry["path"], entry["size"], size))
    actual = sha256_file(abs_path)
    if actual != entry["sha256"]:
        _fail("公开夹具 SHA-256 不符：%s（清单 %s，实际 %s）"
              % (entry["path"], entry["sha256"], actual))
    return abs_path


def verify_all():
    """校验全部条目；返回 (entries, paths)。"""
    entries = all_entries()
    return entries, [verify_entry(entry) for entry in entries]


def get_fixture(fixture_id):
    """按 id 取单个条目并完成文件校验；不存在即硬失败。"""
    for entry in all_entries():
        if entry["id"] == fixture_id:
            verify_entry(entry)
            return entry
    _fail("清单中不存在夹具 id：%s" % fixture_id)


def read_json(entry):
    """读取清单条目对应的 JSON；解析失败即硬失败（不允许静默跳过）。"""
    abs_path = verify_entry(entry)
    try:
        with open(abs_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        _fail("公开夹具不是合法 JSON：%s（%s）" % (entry["path"], e))


def manifest_note():
    """返回清单 note（供日志/文档引用来源与处理口径）。"""
    return load_manifest()["note"]
