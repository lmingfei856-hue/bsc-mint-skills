"""历史经验库：data/history.jsonl 的读写和匹配。

每行一个项目 JSON。匹配按三层算分：
1. 地址精确命中（给的 CA 或站内地址就是历史项目的合约）得满分。
2. 选择器集合重叠：合约字节码里的 PUSH4 选择器和历史项目已知选择器对比。
3. 结构特征：是否代理、有没有 totalMinted/token()、代币小数位。

匹配只决定复用什么识别方法，地址、价格、交易参数一律重新链上核对，
绝不抄历史值。
"""

import json
import os

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.jsonl")


def load_history(path=HISTORY_PATH):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def append_history(entry, path=HISTORY_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def _norm(addr):
    return (addr or "").lower()


def match_history(features, history):
    """features: {
        addresses: [合约地址小写],
        selectors: set(字节码里的选择器 hex, 不带 0x),
        is_proxy: bool,
        has_total_minted: bool,
        has_token_fn: bool,
        decimals: int|None,
        domain: str|None,
    }

    返回按分数排序的 [(score, entry, basis_list)]，score 0 到 1。
    """
    results = []
    addrs = {_norm(a) for a in features.get("addresses", [])}
    selectors = set(features.get("selectors", set()))
    for entry in history:
        basis = []
        score = 0.0

        # 1. 地址精确命中
        entry_addrs = {
            _norm(entry.get("sale_contract")),
            _norm(entry.get("token_contract")),
            _norm(entry.get("mint_contract")),
        } - {""}
        if addrs & entry_addrs:
            score = 1.0
            basis.append("地址精确命中：给的合约就是历史项目 %s 的合约" % entry.get("project"))
            results.append((score, entry, basis))
            continue

        # 域名命中（站内地址还没确认时，靠域名先认出来）
        domain = (features.get("domain") or "").lower()
        entry_domains = [d.lower() for d in entry.get("domains", [])]
        if domain and any(domain == d or domain.endswith("." + d) for d in entry_domains):
            score = max(score, 0.9)
            basis.append("域名命中：%s 是历史项目 %s 的站" % (domain, entry.get("project")))

        # 2. 选择器集合重叠
        known = set()
        for sel in (entry.get("selectors") or {}).values():
            if sel:
                known.add(sel.lower().replace("0x", ""))
        if known:
            shared = sorted(selectors & known)
            if shared:
                frac = len(shared) / len(known)
                score = max(score, 0.4 + 0.5 * frac)
                basis.append(
                    "共享选择器 %d/%d：%s" % (len(shared), len(known), ", ".join(shared)))

        # 3. 结构特征
        struct_hits = []
        if features.get("has_total_minted") and entry.get("has_total_minted"):
            struct_hits.append("totalMinted")
        if features.get("has_token_fn") and entry.get("has_token_fn"):
            struct_hits.append("token()")
        if features.get("is_proxy") == entry.get("is_proxy") and entry.get("is_proxy"):
            struct_hits.append("代理合约")
        if struct_hits:
            score = max(score, 0.35 + 0.1 * len(struct_hits))
            basis.append("结构相同：" + "、".join(struct_hits))

        if entry.get("decimals") is not None and features.get("decimals") is not None:
            if entry["decimals"] == features["decimals"]:
                score = max(score, min(score + 0.05, 0.95))
                basis.append("代币小数位相同（%d 位）" % entry["decimals"])

        if score > 0:
            results.append((score, entry, basis))

    results.sort(key=lambda x: x[0], reverse=True)
    return results


def new_entry_template(project, sale_contract=None, token_contract=None):
    """新项目追加进历史库时的空白模板，字段含义见 references/history-schema.md。"""
    return {
        "project": project,
        "date": "",
        "status": "checked",
        "sale_contract": sale_contract,
        "token_contract": token_contract,
        "token_decimals": None,
        "total_supply": None,
        "price_bnb": None,
        "per_lot": None,
        "total_lots": None,
        "free_lots": 0,
        "free_per_id": 0,
        "paid_cap_per_id": None,
        "requires_agent_id": None,
        "window_start": None,
        "window_end": None,
        "refund_rule": None,
        "sell_tax": None,
        "selectors": {},
        "has_total_minted": False,
        "has_token_fn": False,
        "is_proxy": False,
        "domains": [],
        "mint_method": None,
        "tx_params": None,
        "fail_reason": None,
        "anomalies": [],
        "notes": None,
    }
