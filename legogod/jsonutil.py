"""JSON 可序列化转换：set/tuple 收成 list、非法字典键收成 JSON 文本，不改原对象。

从 workflow_artifacts 抽出（2026-11-15 架构升级）：任务存储 job_store 落盘需要同一套
序列化规则，但按依赖规则它不得反向 import 生成主链模块。workflow_artifacts
继续 import 本函数并保持同名导出，运行记录序列化语义不变。
"""
import json


def to_jsonable(value, set_hits=None, key_hits=None):
    """复制成 json.dumps 能写的结构，不改原对象（set/tuple 收成 list，非法键收成 JSON 文本）。"""
    set_hits = [] if set_hits is None else set_hits
    key_hits = [] if key_hits is None else key_hits
    if isinstance(value, set):
        set_hits.append(1)
        items = [to_jsonable(item, set_hits, key_hits) for item in value]
        try:
            return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            return items
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            safe_item = to_jsonable(item, set_hits, key_hits)
            if isinstance(key, (str, int, float)) or key is None:
                safe_key = key
            else:
                try:
                    safe_key = json.dumps(to_jsonable(key, set_hits, key_hits),
                                          ensure_ascii=False, sort_keys=True)
                except (TypeError, ValueError):
                    return value
                key_hits.append(1)
                if safe_key in out:
                    safe_key = f"{safe_key}#{len(out)}"
            out[safe_key] = safe_item
        return out
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item, set_hits, key_hits) for item in value]
    return value
