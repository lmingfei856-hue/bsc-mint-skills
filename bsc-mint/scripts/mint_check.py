"""BSC Mint 预检入口。

用法：
    python3 scripts/mint_check.py <网址或CA> [--wallet 0x...] [--append-history] [--json]

只读。自动识别 mint 合约、mint 函数、价格、钱包资格、剩余额度和开放状态，
匹配历史经验库，跑风险检查和静态交易模拟，最后输出中文预检报告，结论先行。

绝不签名、授权、付款、发交易，不碰钱包和私钥。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bsclib
import historylib
import siteparse

CA_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# 静态模拟用的调用方：先用销售合约自己，再用 WBNB 合约地址
# （WBNB 合约持有大量 BNB，余额校验一定能过）。
# 只做 eth_call 静态调用，不产生任何状态变化，不签名。
# 注意：不要用 PancakeSwap Router 地址做调用方，之前写的那个地址
# 少了一位 hex，节点会报 invalid argument。
SIM_FROM_FALLBACKS = ["0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"]
DUMMY_FROM = "0x0000000000000000000000000000000000000001"

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.jsonl")


def now_iso():
    import datetime
    cst = datetime.datetime.now(
        datetime.timezone.utc) + datetime.timedelta(hours=8)
    return cst.strftime("%Y-%m-%d %H:%M")


def wei_to_bnb(wei):
    return wei / 10 ** 18


def fmt_bnb(wei):
    if wei is None:
        return "未知"
    return "%.6g BNB" % wei_to_bnb(wei)


def extract_revert_hex(err_text):
    """从 RPC 错误文本里抠出 revert 数据，再解成原因。"""
    if not err_text:
        return ""
    m = re.search(r"0x[0-9a-fA-F]{8,}", err_text)
    if m:
        reason = bsclib.decode_revert(m.group(0))
        if reason and reason != m.group(0):
            return reason
    if "revert" in err_text.lower():
        if re.search(r"reverted:\s*0x['\"]?\s*($|[,}\]])", err_text):
            return "回退，无原因数据（execution reverted，data 为空）"
        m2 = re.search(r"[Rr]evert[^:]*:?\s*(.+)", err_text)
        if m2:
            return m2.group(1)[:200]
    return err_text[:200]


def bscscan_verified(address):
    """查 BscScan 合约是否验证。返回 True / False / None（未核实）。

    先试 BscScan API（无 key，限流时返回 None），再试页面抓取，
    抓不到就写未核实，不硬猜。
    """
    api_url = (
        "https://api.bscscan.com/api?module=contract&action=getsourcecode"
        f"&address={address}"
    )
    try:
        _, text, status = siteparse.fetch_text(api_url, timeout=8, max_bytes=200_000)
        if status == 200 and text.strip().startswith("{"):
            data = json.loads(text)
            results = data.get("result") or []
            if isinstance(results, list) and results:
                src = results[0].get("SourceCode") or ""
                abi = results[0].get("ABI") or ""
                if src and src not in ("", "0"):
                    return True
                if "not verified" in str(abi).lower():
                    return False
    except Exception:  # noqa: BLE001
        pass
    try:
        _, html, status = siteparse.fetch_text(
            f"https://bscscan.com/address/{address}", timeout=8)
        if status == 200 and html:
            if "Contract Source Code Verified" in html:
                return True
            if "Contract Source Code" in html and "not verified" in html.lower():
                return False
    except Exception:  # noqa: BLE001
        pass
    return None


def classify_contracts(addresses):
    """并行探测一批地址，判断每个是代币、销售/铸造合约、两者皆是，还是无代码。

    返回 {address: info}，info 含 role、code_len、selectors、is_proxy、
    impl、token_views、sale_views。
    """
    calls = []
    for addr in addresses:
        calls.append((f"{addr}|supply", addr, "0x" + bsclib.SEL["totalSupply()"], None, 0))
        calls.append((f"{addr}|decimals", addr, "0x" + bsclib.SEL["decimals()"], None, 0))
        calls.append((f"{addr}|symbol", addr, "0x" + bsclib.SEL["symbol()"], None, 0))
        calls.append((f"{addr}|name", addr, "0x" + bsclib.SEL["name()"], None, 0))
        calls.append((f"{addr}|minted", addr, "0x" + bsclib.SEL["totalMinted()"], None, 0))
        calls.append((f"{addr}|tokenfn", addr, "0x" + bsclib.SEL["token()"], None, 0))
    results = bsclib.call_many(calls)

    # 关键读数（总量、小数位、已铸数、token 地址）读不到时单独重试一次，
    # 公共节点抖动时一次重试往往就能拿到
    retry_calls = []
    for addr in addresses:
        for kind in ("supply", "decimals", "minted", "tokenfn"):
            ok, res = results.get(f"{addr}|{kind}", (False, ""))
            if not ok:
                sel = {"supply": "totalSupply()", "decimals": "decimals()",
                       "minted": "totalMinted()", "tokenfn": "token()"}[kind]
                retry_calls.append((f"{addr}|{kind}", addr,
                                    "0x" + bsclib.SEL[sel], None, 0))
    if retry_calls:
        time.sleep(1)
        retry_results = bsclib.call_many(retry_calls)
        results.update(retry_results)

    # 字节码和代理槽位也并行读
    def _code_of(addr):
        code = bsclib.eth_get_code(addr)
        proxy = bsclib.is_proxy(code, addr) if code and code != "0x" else (False, None)
        return addr, code, proxy

    from concurrent.futures import ThreadPoolExecutor
    code_map = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for addr, code, proxy in pool.map(_code_of, addresses):
            code_map[addr] = (code, proxy)

    infos = {}
    for addr in addresses:
        code, (is_proxy, impl) = code_map[addr]
        has_code = bool(code) and code != "0x"
        selectors = bsclib.extract_push4_selectors(code) if has_code else set()
        token_views = {}
        ok, res = results.get(f"{addr}|supply", (False, ""))
        token_views["total_supply"] = bsclib.u256(res) if ok else None
        ok, res = results.get(f"{addr}|decimals", (False, ""))
        token_views["decimals"] = bsclib.u256(res) if ok else None
        ok, res = results.get(f"{addr}|symbol", (False, ""))
        token_views["symbol"] = bsclib.decode_string(res) if ok else None
        ok, res = results.get(f"{addr}|name", (False, ""))
        token_views["name"] = bsclib.decode_string(res) if ok else None
        has_token = (
            token_views["total_supply"] is not None
            and token_views["decimals"] is not None
            and token_views["decimals"] <= 30
        )
        sale_views = {}
        ok, res = results.get(f"{addr}|minted", (False, ""))
        sale_views["total_minted"] = bsclib.u256(res) if ok else None
        ok, res = results.get(f"{addr}|tokenfn", (False, ""))
        sale_views["token"] = bsclib.decode_address(res) if ok else None
        has_sale = (
            sale_views["total_minted"] is not None
            or sale_views["token"] is not None
        )
        code_ok = code != ""
        # 角色先按视图函数定，字节码读失败也不影响角色判断
        if has_token and has_sale:
            role = "both"
        elif has_token:
            role = "token"
        elif has_sale:
            role = "sale"
        elif not code_ok:
            role = "code-unread"
        elif not has_code:
            role = "no-code"
        else:
            role = "unknown-contract"
        infos[addr] = {
            "role": role,
            "has_code": has_code,
            "code_ok": code_ok,
            "code_len": (len(code) - 2) // 2 if has_code else 0,
            "selectors": selectors,
            "is_proxy": is_proxy,
            "impl": impl,
            "token_views": token_views,
            "sale_views": sale_views,
        }
    return infos


def probe_price_and_state(sale_addr):
    """在销售合约上逐个试候选价格和状态函数，返回 (price_wei, state_dict)。"""
    calls = []
    for sig in bsclib.PRICE_CANDIDATES:
        calls.append((f"price|{sig}", sale_addr, "0x" + bsclib.selector(sig), None, 0))
    for sig in bsclib.STATE_CANDIDATES:
        calls.append((f"state|{sig}", sale_addr, "0x" + bsclib.selector(sig), None, 0))
    results = bsclib.call_many(calls)
    price_wei = None
    price_sig = None
    for sig in bsclib.PRICE_CANDIDATES:
        ok, res = results.get(f"price|{sig}", (False, ""))
        if not ok:
            continue
        value = bsclib.u256(res)
        # 价格按每份算，合理范围 0.0001 到 0.1 BNB
        if value is not None and 10 ** 14 <= value <= 10 ** 17:
            price_wei = value
            price_sig = sig
            break
    state = {}
    for sig in bsclib.STATE_CANDIDATES:
        ok, res = results.get(f"state|{sig}", (False, ""))
        if not ok:
            continue
        value = bsclib.u256(res)
        if value is not None:
            state[sig] = value
    return price_wei, price_sig, state


def encode_mint_args(signature):
    """按签名的参数类型编码一份默认参数：uint 类填 1，address 填零地址。

    返回 16 进制参数段（不带 0x），签名无参数时返回空串。
    """
    m = re.search(r"\((.*)\)", signature or "")
    if not m or not m.group(1).strip():
        return ""
    parts = []
    for param in m.group(1).split(","):
        param = param.strip()
        if param.startswith("uint") or param.startswith("int"):
            parts.append("00" * 31 + "01")
        elif param == "address":
            parts.append("00" * 32)
        elif param.startswith("bytes32"):
            parts.append("00" * 32)
        else:
            parts.append("00" * 32)
    return "".join(parts)


NON_MINT_SELECTOR_NAMES = {
    "totalminted", "mintedbywallet", "token", "totalsupply",
    # 只读状态函数也不模拟：KOMA 的 stats() 曾被当成 mint 函数模拟过
    "stats", "price", "priceinfo", "quote", "launched", "salestart",
    "saleinfo", "mintenabled", "remaining", "mintprice", "paused",
    "maxsupply", "owner",
}


def simulate_mint(sale_addr, selectors, price_wei):
    """静态模拟 mint 调用，只 eth_call，不发交易。

    selectors 是 {名字: 选择器 hex}，只模拟名字像铸造的，
    totalMinted、mintedByWallet 这类只读函数不模拟。
    每种函数只试最可能的一种参数形式，全部并行发。
    返回每项 {name, selector, variant, kind, ok, status, detail}，
    status 是 success、reverted 或 unfinished（节点超时或限流，未完成）。
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs = []
    for name, sel in selectors.items():
        sel = sel.lower().replace("0x", "")
        base = name.lower().replace("(", "").replace(")", "")
        if base in NON_MINT_SELECTOR_NAMES:
            continue
        is_free = "free" in name.lower() or sel == "c4310955"
        if is_free:
            jobs.append((name, sel, "免费", "0x" + sel, DUMMY_FROM, 0))
            args = encode_mint_args(name if "(" in name else "mintFree(address)")
            if args:
                jobs.append((name, sel, "免费", "0x" + sel + args, DUMMY_FROM, 0))
        else:
            args = encode_mint_args(name if "(" in name else "mint(uint256,address)")
            data = "0x" + sel + args
            value = price_wei or 0
            jobs.append((name, sel, "付费", data, sale_addr, value))

    if not jobs:
        return [{
            "name": "无", "selector": "", "variant": "",
            "kind": "", "ok": False, "status": "unfinished",
            "detail": "没找到已知 mint 选择器，无法模拟",
        }]

    def _run(job):
        name, sel, kind, data, from_addr, value = job
        tried = [from_addr] + [f for f in SIM_FROM_FALLBACKS if f != from_addr]
        last_err = ""
        for sender in tried:
            ok, res = bsclib.eth_call(
                sale_addr, data, from_addr=sender, value=value)
            if not ok and ("timed out" in res.lower() or "全部节点失败" in res):
                # 节点抖动造成的超时，睡 2 秒只重试这一次
                time.sleep(2)
                ok, res = bsclib.eth_call(
                    sale_addr, data, from_addr=sender, value=value)
            if ok:
                return {"name": name, "selector": sel,
                        "variant": "from=%s，value=%s" % (sender[:10] + "…", fmt_bnb(value)),
                        "kind": kind, "ok": True, "status": "success",
                        "detail": "静态调用成功（未发交易）"}
            if "insufficient funds" in res.lower():
                last_err = res
                continue
            if "timed out" in res.lower() or "全部节点失败" in res:
                last_err = res
                continue
            return {"name": name, "selector": sel,
                    "variant": "from=%s，value=%s" % (sender[:10] + "…", fmt_bnb(value)),
                    "kind": kind, "ok": False, "status": "reverted",
                    "detail": extract_revert_hex(res)}
        if "insufficient funds" in last_err.lower():
            detail = "模拟无法完成：候选调用方余额不足以覆盖付款（静态调用余额校验），未发交易"
        elif "timed out" in last_err.lower() or "全部节点失败" in last_err:
            detail = "模拟未完成：节点超时或限流，未发交易，不是 mint 本身失败"
        else:
            detail = extract_revert_hex(last_err)
        return {"name": name, "selector": sel,
                "variant": "value=%s" % fmt_bnb(value),
                "kind": kind, "ok": False, "status": "unfinished",
                "detail": detail}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_run, jobs))


def run(target, wallet=None, append_history=False):
    timings = {}
    report = {}
    anomalies = []
    t0 = time.perf_counter()

    # ---- 1. 输入解析 ----
    t = time.perf_counter()
    is_ca = bool(CA_RE.match(target.strip()))
    site = None
    site_cfg = {}
    site_minted = None
    domain = None
    if is_ca:
        input_kind = "CA"
        addresses = [target.strip().lower()]
    else:
        input_kind = "网址"
        url = target.strip()
        if not url.startswith("http"):
            url = "https://" + url
        domain = urllib.parse.urlparse(url).netloc.lower()
        site = siteparse.fetch_site(url)
        addresses = site["addresses"][:6]
        site_cfg = site["cfg"]
        site_minted = site_cfg.get("site_minted")
    timings["输入解析"] = round(time.perf_counter() - t, 2)

    # ---- 历史库先读出来，域名能直接认出老项目 ----
    history = historylib.load_history(HISTORY_PATH)

    # 先看输入是不是已开盘代币（地址命中历史 listed_token）：是的话
    # 后面不把它当销售合约，也不跑模拟
    is_listed_token = False
    for entry in history:
        if entry.get("kind") == "listed_token" and _norm(entry.get("token_contract")) in {_norm(a) for a in addresses}:
            is_listed_token = True
            break

    # 站点抓取失败时，靠域名从历史库找合约当候选（标明来源）
    history_fallback = False
    if not is_ca and not addresses and domain:
        for entry in history:
            if domain in [d.lower() for d in entry.get("domains", [])]:
                cand = [a for a in (
                    entry.get("sale_contract"), entry.get("token_contract"))
                    if a]
                if cand:
                    addresses = [a.lower() for a in cand]
                    history_fallback = True
                    anomalies.append(
                        "站点抓取失败（可能被 Cloudflare 拦），合约地址来自历史库 %s，需链上核对"
                        % entry.get("project"))
                    break
    timings["输入解析"] = round(time.perf_counter() - t0, 2)

    if not addresses:
        return {
            "conclusion": "信息不足：没拿到任何合约地址，无法预检",
            "input": target, "input_kind": input_kind,
            "anomalies": anomalies + ["站点抓不到地址，也没有历史库可匹配"],
            "timings": timings,
        }

    # ---- 2. 链上基础探测 ----
    t = time.perf_counter()
    infos = classify_contracts(addresses)
    timings["链上基础探测"] = round(time.perf_counter() - t, 2)

    # 定主角：销售合约和代币合约
    sale_addr = None
    token_addr = None
    for addr, info in infos.items():
        if info["role"] in ("sale", "both") and sale_addr is None and not is_listed_token:
            sale_addr = addr
        if info["role"] in ("token", "both") and token_addr is None:
            token_addr = addr
    if sale_addr and infos[sale_addr]["sale_views"].get("token"):
        linked = infos[sale_addr]["sale_views"]["token"].lower()
        if linked in infos:
            token_addr = linked
        elif linked != bsclib.ZERO_ADDRESS:
            token_addr = linked
            extra = classify_contracts([linked])
            infos.update(extra)
    # 输入是代币、历史库里有对应销售合约时补上
    if token_addr and not sale_addr:
        for entry in history:
            if _norm(entry.get("token_contract")) == token_addr and entry.get("sale_contract"):
                extra = classify_contracts([entry["sale_contract"].lower()])
                infos.update(extra)
                sale_addr = entry["sale_contract"].lower()
                break

    # ---- 3. 历史匹配 ----
    t = time.perf_counter()
    all_selectors = set()
    for info in infos.values():
        all_selectors |= info["selectors"]
    features = {
        "addresses": addresses,
        "selectors": all_selectors,
        "is_proxy": any(i["is_proxy"] for i in infos.values()),
        "has_total_minted": any(
            i["sale_views"].get("total_minted") is not None for i in infos.values()),
        "has_token_fn": any(
            i["sale_views"].get("token") is not None for i in infos.values()),
        "decimals": (
            infos[token_addr]["token_views"]["decimals"] if token_addr and token_addr in infos
            else None),
        "domain": domain,
    }
    matches = historylib.match_history(features, history)
    matched = matches[0] if matches else None
    timings["历史匹配"] = round(time.perf_counter() - t, 2)

    # ---- 4. 交易模拟（先模拟，节点还新鲜） ----
    t = time.perf_counter()
    sim_selectors = {}
    if matched and matched[0] >= 0.6:
        for name, sel in (matched[1].get("selectors") or {}).items():
            if sel:
                sim_selectors[name] = sel
    for sig in bsclib.MINT_SIGNATURES:
        sel = bsclib.selector(sig)
        if sel in all_selectors and sig not in sim_selectors:
            sim_selectors[sig] = sel
    sim_price_wei = None
    if site_cfg.get("price_bnb") is not None:
        sim_price_wei = int(site_cfg["price_bnb"] * 10 ** 18)
    sim_results = []
    if is_listed_token:
        sim_results = [{
            "name": "无", "selector": "", "variant": "",
            "kind": "", "ok": False, "status": "unfinished",
            "detail": "已开盘代币，无 mint 过程，不模拟",
        }]
    elif sale_addr and sim_selectors:
        sim_results = simulate_mint(sale_addr, sim_selectors, sim_price_wei)
    elif sale_addr:
        # 字节码没读到、没找到 mint 选择器时，用候选签名逐个试探：
        # 调 value=0，有业务 revert 说明函数存在，无返回则说明不存在
        probe_calls = []
        for sig in bsclib.MINT_SIGNATURES:
            probe_calls.append((sig, sale_addr,
                                "0x" + bsclib.selector(sig) +
                                encode_mint_args(sig), DUMMY_FROM, 0))
        probe_results = bsclib.call_many(probe_calls)
        found = []
        for sig, _a, _d, _f, _v in probe_calls:
            ok, res = probe_results.get(sig, (False, ""))
            if not ok:
                # 有业务 revert 说明函数存在；超时或限流说明节点问题，不算
                if "revert" in res.lower():
                    found.append((sig, extract_revert_hex(res)))
                continue
            if res and res != "0x":
                found.append((sig, "调用成功（有返回数据）"))
        if found:
            sim_results = [{
                "name": sig, "selector": bsclib.selector(sig),
                "variant": "试探（value=0）", "kind": "付费" if "free" not in sig.lower() else "免费",
                "ok": False, "status": "reverted",
                "detail": "函数存在，试探调用被拒：%s（字节码未读到，改用选择器试探，未发交易）" % reason,
            } for sig, reason in found]
            # 用试探到的选择器补跑一次正式模拟
            extra = {sig: bsclib.selector(sig) for sig, _ in found}
            sim_results += simulate_mint(sale_addr, extra, sim_price_wei)
        else:
            sim_results = [{
                "name": "无", "selector": "", "variant": "",
                "kind": "", "ok": False, "status": "unfinished",
                "detail": "字节码未读到，候选 mint 选择器试探均无业务回应，无法模拟",
            }]
    elif sale_addr:
        sim_results = [{"name": "无", "selector": "", "variant": "",
                        "kind": "", "ok": False,
                        "detail": "字节码里没找到已知 mint 选择器，无法模拟"}]
    timings["交易模拟"] = round(time.perf_counter() - t, 2)


    # ---- 5. 链上深度查询 ----
    t = time.perf_counter()
    price_wei = None
    price_source = None
    state = {}
    balances = {}
    wallet_minted = None
    if sale_addr:
        price_wei, price_sig, state = probe_price_and_state(sale_addr)
        if price_wei is not None:
            price_source = "链上 %s" % price_sig
    if token_addr and token_addr in infos:
        tv = infos[token_addr]["token_views"]
        total_supply = tv.get("total_supply")
        dec = tv.get("decimals") or 18
        calls = []
        if sale_addr:
            calls.append(("sale_bal", token_addr,
                          "0x" + bsclib.SEL["balanceOf(address)"] + "00" * 12 + sale_addr[2:], None, 0))
        calls.append(("self_bal", token_addr,
                      "0x" + bsclib.SEL["balanceOf(address)"] + "00" * 12 + token_addr[2:], None, 0))
        if wallet:
            calls.append(("wallet_minted", sale_addr,
                          "0x" + bsclib.SEL["mintedByWallet(address)"] + "00" * 12 + wallet[2:], None, 0))
        if calls:
            res = bsclib.call_many(calls)
            if "sale_bal" in res and res["sale_bal"][0]:
                balances["sale_contract"] = bsclib.u256(res["sale_bal"][1])
            if "self_bal" in res and res["self_bal"][0]:
                balances["token_contract_self"] = bsclib.u256(res["self_bal"][1])
            if "wallet_minted" in res and res["wallet_minted"][0]:
                wallet_minted = bsclib.u256(res["wallet_minted"][1])
        balances["total_supply_raw"] = total_supply
        balances["decimals"] = dec
    timings["链上深度查询"] = round(time.perf_counter() - t, 2)

    per_lot = site_cfg.get("per_lot")
    if per_lot is None and site_cfg.get("per_lot_wei") is not None:
        dec = None
        if token_addr and token_addr in infos:
            dec = infos[token_addr]["token_views"].get("decimals")
        if dec is not None:
            try:
                per_lot = int(site_cfg["per_lot_wei"]) // (10 ** dec)
            except (ValueError, TypeError):
                pass

    price_ref = None
    per_lot_ref = None
    if matched and matched[0] >= 0.9:
        price_ref = matched[1].get("price_bnb")
        per_lot_ref = matched[1].get("per_lot")

    # 价格：站内优先（和链上互相印证），链上没有再用站内
    site_price = site_cfg.get("price_bnb")
    price_bnb = None
    if price_wei is not None:
        price_bnb = round(wei_to_bnb(price_wei), 6)
    elif site_price is not None:
        price_bnb = site_price
        price_source = "站点配置"
        price_wei = int(site_price * 10 ** 18)
    if site_price is not None and price_wei is not None:
        chain_price = round(wei_to_bnb(price_wei), 6) if price_source and price_source.startswith("链上") else None
        if chain_price is not None and abs(chain_price - site_price) > 0.0001:
            anomalies.append("站内价格 %s BNB 与链上价格 %s BNB 对不上" % (site_price, chain_price))

    # 份数与剩余额度
    total_lots = site_cfg.get("total_lots") or site_cfg.get("site_total")
    total_lots_source = "站点" if total_lots is not None else None
    # 注意：maxSupply()/MAX_SUPPLY() 是代币总量（带小数位的大数），不是份数，
    # 绝不能当总份数用。份数只能来自站点、stats() 或同项目历史记录。
    if total_lots is not None and total_lots >= 10_000_000:
        total_lots = None
        total_lots_source = None
    if total_lots is None and matched and matched[0] >= 0.9:
        # 同项目地址命中：总量沿用历史记录，但已铸数是本次链上实测的，
        # 结论仍以链上为准，这里只标明来源
        total_lots = matched[1].get("total_lots")
        total_lots_source = "历史记录（同项目地址命中）" if total_lots else None
    total_minted = None
    total_minted_source = "链上 totalMinted()"
    if sale_addr and sale_addr in infos:
        total_minted = infos[sale_addr]["sale_views"].get("total_minted")
    if total_minted is None and state.get("stats()") is not None:
        total_minted = state["stats()"]
        total_minted_source = "链上 stats()（首字段 sold）"
    if total_minted is None and site and site.get("status_api"):
        for key in ("totalMinted", "minted", "total_minted"):
            if isinstance(site["status_api"].get(key), int):
                total_minted = site["status_api"][key]
                total_minted_source = "站点状态接口"
                break
    if total_minted is None and site_minted is not None:
        # 链上 totalMinted 本次未读到（节点抖动），用站点自己的链上 API 数据顶上，
        # 来源写清，不冒充链上直读
        total_minted = site_minted
        total_minted_source = "站点 API（链上 totalMinted 本次未读到）"
        anomalies.append("链上 totalMinted 本次未读到，已铸数取自站点 API（%d）" % site_minted)
    remaining = None
    if total_lots is not None and total_minted is not None:
        remaining = max(0, total_lots - total_minted)
    free_lots = site_cfg.get("free_lots")
    free_lots_source = "站点" if free_lots is not None else None
    if free_lots is None and matched and matched[0] >= 0.9:
        free_lots = matched[1].get("free_lots")
        free_lots_source = "历史记录（同项目地址命中）" if free_lots is not None else None
    free_remaining = None
    if free_lots and total_minted is not None:
        free_remaining = max(0, free_lots - total_minted)

    # 开放状态
    open_status = "未知"
    if total_lots is not None and total_minted is not None:
        open_status = "已铸满" if total_minted >= total_lots else "开放中"
    elif state.get("mintEnabled()") == 1 or state.get("launched()") == 1:
        open_status = "开放中"
    elif state.get("mintEnabled()") == 0 or state.get("paused()") == 1:
        open_status = "未开放"

    # 资格要求
    requires_agent = site_cfg.get("requires_agent_id")
    if requires_agent is None and matched and matched[0] >= 0.6:
        requires_agent = matched[1].get("requires_agent_id")

    # ---- 6. 风险检查 ----
    t = time.perf_counter()
    risks = []
    contract_addrs = [a for a, i in infos.items()
                      if i["role"] in ("sale", "token", "both", "unknown-contract", "code-unread")]
    for addr in contract_addrs:
        info = infos[addr]
        if not info.get("code_ok", True):
            risks.append({
                "item": "合约 %s 有代码" % addr[:10] + "…",
                "result": "未核实",
                "detail": "字节码没读到（节点失败），无法确认",
            })
        else:
            risks.append({
                "item": "合约 %s 有代码" % addr[:10] + "…",
                "result": "通过" if info["has_code"] else "异常",
                "detail": "字节码 %d 字节" % info["code_len"] if info["has_code"] else "无代码，可能是外部账户地址",
            })
        if info["has_code"]:
            risks.append({
                "item": "合约 %s 是否代理" % addr[:10] + "…",
                "result": "异常" if info["is_proxy"] else "通过",
                "detail": ("代理合约，实现地址 %s，可升级" % info["impl"]) if info["is_proxy"] else "非代理",
            })
    verified = {}
    from concurrent.futures import ThreadPoolExecutor as _Pool
    with _Pool(max_workers=4) as pool:
        for addr, v in zip(contract_addrs, pool.map(bscscan_verified, contract_addrs)):
            verified[addr] = v
    for addr, v in verified.items():
        risks.append({
            "item": "BscScan 验证 %s" % addr[:10] + "…",
            "result": "通过" if v is True else ("异常" if v is False else "未核实"),
            "detail": "已验证" if v is True else ("未验证" if v is False else "查不到（可能被限流或 Cloudflare 拦），不代表有问题"),
        })
    if total_lots is not None and total_minted is not None:
        risks.append({
            "item": "铸造是否已满",
            "result": "异常" if total_minted >= total_lots else "通过",
            "detail": "已铸 %d / %d" % (total_minted, total_lots),
        })
    if matched and matched[0] >= 0.6 and price_bnb is not None:
        hist_price = matched[1].get("price_bnb")
        if hist_price:
            if price_bnb > hist_price * 2 or price_bnb < hist_price * 0.5:
                anomalies.append("价格异常：当前 %s BNB，历史同类 %s 是 %s BNB" % (
                    price_bnb, matched[1].get("project"), hist_price))
                risks.append({"item": "价格与历史对比", "result": "异常",
                              "detail": "当前 %s BNB，历史 %s BNB" % (price_bnb, hist_price)})
            else:
                risks.append({"item": "价格与历史对比", "result": "通过",
                              "detail": "当前 %s BNB，历史 %s BNB，同一量级" % (price_bnb, hist_price)})
    if balances.get("total_supply_raw") and balances.get("sale_contract") is not None:
        frac = balances["sale_contract"] / balances["total_supply_raw"] if balances["total_supply_raw"] else 0
        risks.append({
            "item": "销售合约持仓占比",
            "result": "异常" if frac > 0.5 else "通过",
            "detail": "销售合约持有 %.1f%% 的代币" % (frac * 100),
        })
    # 站内计数器为 0 通常是静态 HTML 还没加载出数字，不算数，不对比
    if site_minted is not None and total_minted is not None and site_minted > 0:
        diff = abs(site_minted - total_minted)
        denom = max(total_minted, 1)
        if diff / denom > 0.02:
            anomalies.append("站内计数器与链上对不上：站内显示 %d，链上 totalMinted 是 %d" % (
                site_minted, total_minted))
            risks.append({"item": "站内计数器与链上一致性", "result": "异常",
                          "detail": "站内 %d，链上 %d" % (site_minted, total_minted)})
        else:
            risks.append({"item": "站内计数器与链上一致性", "result": "通过",
                          "detail": "站内 %d，链上 %d" % (site_minted, total_minted)})
    for key, addr in (("销售合约", sale_addr), ("代币合约", token_addr)):
        if addr and infos.get(addr, {}).get("role") == "no-code":
            anomalies.append("%s %s 没有代码，可能是外部账户地址，不是合约" % (key, addr))
    if matched and matched[0] >= 0.6:
        known_sels = {v.lower().replace("0x", "") for v in (matched[1].get("selectors") or {}).values() if v}
        sale_code_read = bool(sale_addr and infos.get(sale_addr, {}).get("code_ok"))
        if known_sels and sale_code_read and not (known_sels & all_selectors):
            anomalies.append("历史选择器无响应：历史项目 %s 的选择器在当前销售合约字节码里一个都找不到，模板可能换了" % matched[1].get("project"))
        elif known_sels and not sale_code_read:
            anomalies.append("销售合约字节码没读到，无法比对历史选择器")
    timings["风险检查"] = round(time.perf_counter() - t, 2)

    # ---- 结论 ----
    kind = matched[1].get("kind") if matched and matched[0] >= 0.9 else None
    if kind == "listed_token":
        conclusion = "已开盘代币，不是 mint 项目：%s" % matched[1].get("project")
    elif sale_addr is None and token_addr is not None:
        conclusion = "该地址是代币合约，未发现铸造合约，无法预检 mint"
    elif total_lots is not None and total_minted is not None and total_minted >= total_lots:
        conclusion = "已铸满，不可参与"
    elif free_remaining and free_remaining > 0:
        conclusion = "有免费额度，剩余 %d 份免费" % free_remaining
        if requires_agent:
            conclusion += "，需 .ai Agent ID"
    elif free_lots == 0 and price_bnb is not None:
        conclusion = "仅付费铸造，无免费额度，%s BNB/份" % price_bnb
    elif price_bnb is not None and open_status == "开放中":
        conclusion = "开放中，%s BNB/份" % price_bnb
    elif not addresses:
        conclusion = "信息不足，无法预检"
    else:
        conclusion = "信息不全：价格或剩余额度没拿到，需人工再看"
    if anomalies:
        conclusion += "；异常 %d 项，见异常提醒" % len(anomalies)

    timings["总计"] = round(time.perf_counter() - t0, 2)

    report = {
        "conclusion": conclusion,
        "input": target,
        "input_kind": input_kind,
        "checked_at": now_iso(),
        "sale_contract": sale_addr,
        "token_contract": token_addr,
        "contracts": {a: {"role": i["role"], "code_bytes": i["code_len"],
                          "is_proxy": i["is_proxy"], "impl": i["impl"]}
                      for a, i in infos.items()},
        "token": (infos[token_addr]["token_views"] if token_addr and token_addr in infos else None),
        "price_bnb": price_bnb,
        "price_source": price_source,
        "price_ref": price_ref,
        "per_lot": per_lot,
        "per_lot_ref": per_lot_ref,
        "total_lots_source": total_lots_source,
        "free_lots_source": free_lots_source,
        "total_lots": total_lots,
        "total_minted": total_minted,
        "total_minted_source": total_minted_source,
        "remaining": remaining,
        "free_lots": free_lots,
        "free_remaining": free_remaining,
        "cap_per_wallet": site_cfg.get("cap_per_wallet"),
        "wallet_minted": wallet_minted,
        "requires_agent_id": requires_agent,
        "open_status": open_status,
        "window_dates": site_cfg.get("dates_found"),
        "refund_mentioned": site_cfg.get("mentions_refund"),
        "audit_mentioned": site_cfg.get("mentions_audit"),
        "matches": [
            {"project": e.get("project"), "score": round(s, 2), "basis": b}
            for s, e, b in matches[:3]
        ],
        "matched_method_reused": (
            "复用 %s 的识别方法：%s" % (
                matched[1].get("project"),
                "、".join((matched[1].get("selectors") or {}).keys()) or "无已知选择器")
            if matched and matched[0] >= 0.6 else None),
        "risks": risks,
        "anomalies": anomalies,
        "simulation": sim_results,
        "site_http_status": site["http_status"] if site else None,
        "history_fallback": history_fallback,
        "timings": timings,
    }

    if append_history:
        entry = historylib.new_entry_template(
            project=(domain or (report["token"] or {}).get("symbol") or "unknown"),
            sale_contract=sale_addr, token_contract=token_addr)
        entry["date"] = time.strftime("%Y-%m-%d", time.localtime())
        entry["status"] = "checked"
        entry["token_decimals"] = (report["token"] or {}).get("decimals")
        entry["total_supply"] = (report["token"] or {}).get("total_supply")
        entry["price_bnb"] = price_bnb
        entry["per_lot"] = per_lot
        entry["total_lots"] = total_lots
        entry["free_lots"] = free_lots or 0
        entry["requires_agent_id"] = requires_agent
        entry["selectors"] = {k: v for k, v in sim_selectors.items()}
        entry["has_total_minted"] = total_minted is not None
        entry["anomalies"] = anomalies
        if domain:
            entry["domains"] = [domain]
        historylib.append_history(entry, HISTORY_PATH)
        report["history_appended"] = True

    return report


def _norm(addr):
    return (addr or "").lower()


def render(report):
    """中文预检报告，结论先行。"""
    lines = []
    lines.append("结论：%s" % report["conclusion"])
    lines.append("")
    lines.append("关键信息")
    lines.append("  检查时间：%s" % report["checked_at"])
    lines.append("  输入：%s（%s）" % (report["input"], report["input_kind"]))
    if report.get("sale_contract"):
        lines.append("  铸造/销售合约：%s" % report["sale_contract"])
    if report.get("token_contract"):
        lines.append("  代币合约：%s" % report["token_contract"])
    tok = report.get("token") or {}
    if tok.get("symbol"):
        lines.append("  代币：%s（%s），%s 位小数，总量 %s" % (
            tok.get("name") or "", tok.get("symbol") or "",
            tok.get("decimals"), tok.get("total_supply")))
    if report["price_bnb"] is not None:
        lines.append("  价格：%s BNB/份%s" % (
            report["price_bnb"],
            ("（来源：%s）" % report["price_source"]) if report.get("price_source") else ""))
    elif report.get("price_ref") is not None:
        lines.append("  价格：未知（历史记录 %s BNB/份，未重新核实）" % report["price_ref"])
    else:
        lines.append("  价格：未知 BNB/份")
    if report.get("per_lot"):
        lines.append("  每份量：%s 枚" % format(report["per_lot"], ","))
    elif report.get("per_lot_ref"):
        lines.append("  每份量：未知（历史记录 %s 枚，未重新核实）" % format(report["per_lot_ref"], ","))
    if report.get("total_lots") is not None:
        lines.append("  总份数：%s%s，已铸：%s，剩余：%s" % (
            format(report["total_lots"], ","),
            ("（来源：%s）" % report["total_lots_source"]) if report.get("total_lots_source") else "",
            (format(report["total_minted"], ",") + ("（来源：%s）" % report["total_minted_source"]) if report.get("total_minted_source") and report.get("total_minted_source") != "链上 totalMinted()" else format(report["total_minted"], ",")) if report.get("total_minted") is not None else "未知",
            format(report["remaining"], ",") if report.get("remaining") is not None else "未知"))
    if report.get("free_lots"):
        lines.append("  免费额度：共 %s 份，剩余 %s 份" % (
            format(report["free_lots"], ","),
            format(report["free_remaining"], ",") if report.get("free_remaining") is not None else "未知"))
    elif report.get("free_lots") == 0:
        lines.append("  免费额度：无")
    if report.get("cap_per_wallet"):
        lines.append("  每钱包上限：%s 份" % report["cap_per_wallet"])
    if report.get("wallet_minted") is not None:
        lines.append("  该钱包已铸：%s 份" % report["wallet_minted"])
    lines.append("  需 Agent ID：%s" % (
        "是" if report["requires_agent_id"] is True else (
            "否" if report["requires_agent_id"] is False else "未明确")))
    lines.append("  开放状态：%s" % report["open_status"])
    if report.get("window_dates"):
        lines.append("  站内日期：%s" % "、".join(report["window_dates"]))
    if report.get("refund_mentioned"):
        lines.append("  站内提到退款：是")
    if report.get("audit_mentioned"):
        lines.append("  站内提到审计：是")
    lines.append("")
    lines.append("历史匹配")
    if report.get("matches"):
        for m in report["matches"]:
            lines.append("  %s（相似度 %.2f）：%s" % (
                m["project"], m["score"], "；".join(m["basis"])))
        if report.get("matched_method_reused"):
            lines.append("  %s" % report["matched_method_reused"])
            lines.append("  地址、价格、交易参数已重新链上核对，未抄历史值。")
    else:
        lines.append("  无匹配：陌生合约，按通用方法探测。")
    lines.append("")
    lines.append("风险检查")
    if report.get("risks"):
        for r in report["risks"]:
            lines.append("  [%s] %s：%s" % (r["result"], r["item"], r["detail"]))
    else:
        lines.append("  未执行")
    lines.append("")
    lines.append("异常提醒")
    if report.get("anomalies"):
        for a in report["anomalies"]:
            lines.append("  ! %s" % a)
    else:
        lines.append("  无")
    lines.append("")
    lines.append("交易模拟（静态调用，不签名、不发交易）")
    if report.get("simulation"):
        for s in report["simulation"]:
            status = s.get("status", "success" if s["ok"] else "reverted")
            mark = {"success": "成功", "reverted": "失败", "unfinished": "未完成"}[status]
            lines.append("  [%s] %s %s %s：%s" % (
                mark, s["name"], s["variant"], s["kind"], s["detail"]))
    else:
        lines.append("  未执行")
    lines.append("")
    lines.append("耗时（秒）")
    for stage, sec in (report.get("timings") or {}).items():
        lines.append("  %s：%s" % (stage, sec))
    if report.get("history_fallback"):
        lines.append("")
        lines.append("提示：站点抓取失败，合约来自历史库，已链上核对。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BSC Mint 预检（只读）")
    parser.add_argument("target", help="铸造站网址或合约地址 CA")
    parser.add_argument("--wallet", help="要查个人已铸额度的钱包地址")
    parser.add_argument("--append-history", action="store_true",
                        help="把本次预检结果追加进历史库")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    report = run(args.target, wallet=args.wallet,
                 append_history=args.append_history)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))


if __name__ == "__main__":
    main()
