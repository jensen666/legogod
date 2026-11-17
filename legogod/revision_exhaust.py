# -*- coding: utf-8 -*-
"""结构修订额度用尽后的收尾策略（从 revision_policy.py 拆出，行为不变）。

拆分原因：revision_policy.py 曾因回滚版本修复超过 500 行上限。
revision_policy 重新导入本函数，保持
`revision_policy.solve_after_revision_exhausted` 对外路径不变。
"""
from . import tiler


def solve_after_revision_exhausted(chain, ex, failure_cls):
    """结构修订不能再改时：绑定和预检都过才最终求解，否则按这两类失败。"""
    from . import part_binding as pb
    from .agent import precheck_details

    reason = ex.reason
    chain.revision_incomplete = True
    chain.revision_incomplete_reason = reason
    chain.emit("info", f"{reason}：不再改稿，检查当前稿能否直接求解")
    bind_errs = []
    if chain.parts_norm is not None and chain.model is not None:
        bind_errs = list(pb.parts_binding_errors(chain.parts_norm, chain.model) or [])
    if chain.model is None:
        detail = {"errors": ["没有可求解的设计"], "kind": "parts"}
    else:
        detail = precheck_details(chain.model)
    if bind_errs or detail["errors"]:
        msg = bind_errs[0] if bind_errs else detail["errors"][0]
        kind = "parts" if bind_errs else (detail.get("kind") or "precheck")
        which = "部位绑定" if bind_errs else "预检"
        chain.emit("error", f"修订停止后当前稿未通过{which}：{msg[:200]}")
        info = {
            "revisionIncomplete": True, "revisionIncompleteReason": reason,
            "stoppedBecause": "binding" if bind_errs else "precheck",
        }
        # 预检的 error_cells 已是全量，不是截断提示。绑在失败对象上，供快照计算窗口。
        # 不把截断后的 cells 补成窗口。部位绑定失败没有格子，不编造。
        if not bind_errs and detail.get("kind") in ("support", "connectivity"):
            cells = list(detail.get("error_cells") or [])
            info["failure"] = {
                "kind": kind, "message": msg, "layer": None,
                "cells": cells, "window_cells": cells,
            }
        raise failure_cls(msg, kind=kind, stage="revise", info=info)
    chain.emit("info", "部位绑定与预检已通过，对当前稿做最终求解")
    sol, failure = chain._solve_current()
    if sol is not None:
        chain.emit("info", "最终求解成功，但修订未完成，按降级交付")
        return chain._finish_success(sol)
    kind = (failure or {}).get("kind") or "internal"
    msg = (failure or {}).get("message") or ""
    chain.emit("error", f"最终求解未铺通（{kind}），失败原因不是修订协议用尽")
    raise failure_cls(
        f"最终求解未通过（{kind}）：{msg[:300]}",
        kind=kind, stage="solve",
        info={"failure": tiler.public_failure(failure), "revisionIncomplete": True,
              "revisionIncompleteReason": reason, "stoppedBecause": "solve"},
    )
