"""铸造站点抓取和解析。只读 GET，不点任何按钮，不连钱包。

抓首页 HTML，再抓同源的小 JS 文件（配置常写在 JS 里，例如
BROCCOLI 的 app.js），从中提取合约地址、价格、份数、免费额度、
窗口时间、Agent ID 要求、退款和税率信息。
"""

import gzip
import json
import re
import urllib.parse
import urllib.request
import urllib.error

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Encoding": "identity",
}

MAX_HTML_BYTES = 3_000_000
MAX_JS_BYTES = 2_000_000
MAX_JS_FILES = 6
# 超过这个大小的 JS 基本是第三方库（例如 ethers.umd.min.js），
# 里面的 0x 常量会污染地址提取，直接跳过
SKIP_JS_OVER_BYTES = 300_000
SKIP_JS_NAMES = ("ethers", "web3", "jquery", "react", "vue", "axios",
                 "lodash", "moment", "beacon", "chunk", "vendor")

ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}")
HEX40_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")


def fetch_text(url, timeout=15, max_bytes=MAX_HTML_BYTES):
    """GET 一个 URL，返回 (final_url, text, status)。失败返回 (url, '', 0)。"""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)[:max_bytes]
            if resp.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:  # noqa: BLE001
                    pass
            charset = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, "replace")
            return resp.geturl(), text, resp.status
    except Exception:  # noqa: BLE001
        return url, "", 0


def _looks_like_address(addr):
    """过滤掉 0x 常量：零地址、全同字符、低熵位掩码。

    混淆器或 JS 库里常有 0x000...0、0xffff...f、0x7ae96a... 这类
    40 位 hex，看着像地址其实是常量。
    """
    body = addr[2:].lower()
    if body == "0" * 40:
        return False
    if len(set(body)) == 1:
        return False
    if len(set(body)) < 4:
        return False
    return True


def extract_addresses(text):
    """按出现顺序去重提取 0x 地址，统一转小写，过掉常量。"""
    seen = set()
    out = []
    for m in ADDR_RE.finditer(text or ""):
        addr = m.group(0).lower()
        if addr not in seen and _looks_like_address(addr):
            seen.add(addr)
            out.append(addr)
    return out


def _first_num(patterns, text, cast=float, valid=None):
    """按顺序试一组正则，返回第一个通过 valid 校验的数字。

    valid 用来排除误抓，例如 TOTAL 模式抓到 JS 里的 total=0。
    没传 valid 时返回第一个能解析的数字。
    """
    for pat in patterns:
        for m in re.finditer(pat, text or "", re.IGNORECASE):
            try:
                value = cast(m.group(1).replace(",", ""))
            except (ValueError, IndexError):
                continue
            if valid is None or valid(value):
                return value
    return None


def _has(patterns, text):
    return any(re.search(p, text or "", re.IGNORECASE) for p in patterns)


def parse_config(text):
    """从页面或 JS 文本里提取铸造配置，返回 dict，未找到的字段为 None。"""
    cfg = {}

    cfg["price_bnb"] = _first_num([
        r"paidPriceBNB\s*[:=]\s*['\"]?([0-9]*\.?[0-9]+)",
        r"GENESIS[^;\n]{0,40}?([0-9]*\.[0-9]+)\s*BNB",
        r"PRICE\s*[:=]\s*['\"]?([0-9]*\.?[0-9]+)",
        r"每份\s*([0-9]*\.?[0-9]+)\s*BNB",
        r"单价\s*([0-9]*\.?[0-9]+)\s*BNB",
        r"([0-9]*\.?[0-9]+)\s*BNB\s*/\s*(?:份|lot|share)",
    ], text)
    # POST 开售阶梯价（例如 POST_START_PRICE 0.0025）不是创世价，
    # 上面的 paidPriceBNB / PRICE 模式优先，通用模式里不放纯数字加 BNB，
    # 避免抓到阶梯价
    if cfg["price_bnb"] is None:
        cfg["price_bnb"] = _first_num([
            r"id=\"cost\">([0-9]*\.?[0-9]+)\s*BNB",
            r"price\s*[:=]\s*['\"]?([0-9]*\.?[0-9]+)\s*BNB",
        ], text)
    if cfg["price_bnb"] is None:
        # 兜底：取页面上最小的合理 BNB 单价（0.0001 到 0.1），
        # 创世单价通常是页面上最小的 BNB 金额，总价和阶梯价都比它大
        found = []
        for m in re.finditer(r"([0-9]*\.[0-9]+)\s*BNB", text or ""):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if 0.0001 <= v <= 0.1:
                found.append(v)
        if found:
            cfg["price_bnb"] = min(found)

    cfg["per_lot"] = _first_num([
        r"perPaid\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"PER\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"id=\"tokens\">([0-9][0-9,]*)",
        r"units\s*\*\s*([0-9][0-9,]*)",
        r"每份得\s*([0-9][0-9,]*)",
        r"每份\s*([0-9][0-9,]*)\s*枚",
        r"获得代币?\s*[^0-9]{0,20}([0-9][0-9,]*)",
        r"([0-9][0-9,]*)\s*(?:枚|tokens?)\s*/\s*(?:份|lot|share)",
    ], text, cast=int)
    cfg["free_per_lot"] = _first_num([
        r"perFree\s*[:=]\s*['\"]?([0-9][0-9,]*)",
    ], text, cast=int)

    # 总份数至少是三位数，个位数一定是误抓（例如 “1 份起购”、
    # JS 里的 total=0）
    cfg["total_lots"] = _first_num([
        r"preCap\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"TOTAL\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"共\s*([0-9][0-9,]*)\s*份",
        r"总量\s*([0-9][0-9,]*)\s*份",
        r"([0-9][0-9,]*)\s*份",
    ], text, cast=int, valid=lambda v: v >= 100)

    free_lots = _first_num([
        r"freeCap\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"FREE_LOTS\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"免费\s*#1-#([0-9][0-9,]*)",
        r"免费\s*([0-9][0-9,]*)\s*份",
    ], text, cast=int)
    cfg["free_lots"] = free_lots

    cfg["cap_per_wallet"] = _first_num([
        r"perIdCap\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"QUOTA\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"MAX_TX\s*[:=]\s*['\"]?([0-9][0-9,]*)",
        r"每钱包上限\s*([0-9][0-9,]*)\s*份",
        r"每\s*(?:钱包|ID)\s*最多\s*([0-9][0-9,]*)\s*份",
        r"限额\s*([0-9][0-9,]*)\s*份",
        r"([0-9][0-9,]*)\s*份/钱包",
        r"上限\s*([0-9][0-9,]*)\s*份",
    ], text, cast=int)

    # 已铸进度：找 "9,729 / 10,000" 或 "已铸 1,085" 这类
    m = re.search(
        r"([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)", text or "")
    if m:
        try:
            minted = int(m.group(1).replace(",", ""))
            total = int(m.group(2).replace(",", ""))
            if total >= 100 and minted <= total:
                cfg["site_minted"] = minted
                cfg["site_total"] = total
        except ValueError:
            pass
    if cfg.get("site_minted") is None:
        cfg["site_minted"] = _first_num([
            r"已铸\s*([0-9][0-9,]*)",
            r"minted\s*[:=]?\s*['\"]?([0-9][0-9,]*)",
            r"totalMinted\s*[:=]?\s*['\"]?([0-9][0-9,]*)",
        ], text, cast=int)

    # 日期和 epoch 时间戳
    dates = re.findall(r"20\d\d-\d\d-\d\d(?:\s+\d\d:\d\d(?::\d\d)?)?", text or "")
    cfg["dates_found"] = sorted(set(dates))[:6]
    m = re.search(r"MINT_START\s*[:=]\s*['\"]?(\d{10,13})", text or "")
    cfg["mint_start_ms"] = int(m.group(1)) if m else None
    m = re.search(r"REFUND_DEADLINE\s*[:=]\s*['\"]?(\d{10,13})", text or "")
    cfg["refund_deadline_ms"] = int(m.group(1)) if m else None

    cfg["requires_agent_id"] = _has([
        r"Agent ID", r"\.ai\b", r"SPACE ID", r"agentId",
        r"持有\s*\.ai", r"Agent\s*ID\s*注册",
    ], text)
    cfg["mentions_refund"] = _has([r"refund", r"退款", r"autoRefund"], text)
    cfg["mentions_tax"] = _has([r"tax", r"买卖税", r"sell tax", r"buy tax"], text)
    cfg["mentions_free"] = _has([r"\bfree\b", r"免费"], text)
    cfg["mentions_audit"] = _has([r"audit", r"审计"], text)
    cfg["mentions_whitepaper"] = _has([r"whitepaper", r"白皮书"], text)

    # 税率数字：找 "3.5%" 附近带 tax 的片段
    taxes = re.findall(r"([0-9]*\.?[0-9]+)\s*%", text or "")
    cfg["percents_found"] = [float(x) for x in taxes[:8]]

    return cfg


def discover_site_apis(base_url, js_text):
    """从 JS 文本里找站内 API 路径并逐个探。

    铸造站常把实时数据放在同源 /api/... 接口里（例如 BABYDOGE 的
    api/chain/babydoge 和 api/mint/estimate/1），比解析 HTML 更准。
    只探名字里带 chain、status、mint、estimate、progress 的路径，
    返回 {路径: 解析到的 JSON}。
    """
    found = {}
    candidates = set()
    for m in re.findall(r"['\"`](api/[a-zA-Z0-9/_\-\.${}]+)['\"`]", js_text or ""):
        path = m.replace("${quantity}", "1").replace("${id}", "1")
        if "${" in path:
            continue
        low = path.lower()
        if any(k in low for k in ("chain", "status", "mint", "estimate", "progress")):
            candidates.add(path)
    origin = urllib.parse.urlparse(base_url)
    root = f"{origin.scheme}://{origin.netloc}"
    for path in sorted(candidates)[:8]:
        url = root + "/" + path.lstrip("/")
        _, text, status = fetch_text(url, timeout=6, max_bytes=500_000)
        if status == 200 and text.strip().startswith("{"):
            try:
                data = json.loads(text)
                if isinstance(data, dict) and data.get("ok") is not False:
                    found[path] = data
            except Exception:  # noqa: BLE001
                continue
    return found


def probe_status_api(base_url):
    """试几个常见的站内状态接口（AKITA 的 /api/?action=status 模式）。

    返回解析到的 JSON dict，拿不到返回 {}。
    """
    origin = urllib.parse.urlparse(base_url)
    root = f"{origin.scheme}://{origin.netloc}"
    candidates = [
        f"{root}/api/?action=status",
        f"{root}/api/status",
        f"{root}/api/mint/status",
    ]
    for url in candidates:
        _, text, status = fetch_text(url, timeout=6, max_bytes=200_000)
        if status == 200 and text.strip().startswith("{"):
            try:
                data = json.loads(text)
                if isinstance(data, dict) and data:
                    data["_probe_url"] = url
                    return data
            except Exception:  # noqa: BLE001
                continue
    return {}


def fetch_site(url):
    """抓一个铸造站：首页 + 同源 JS + 状态接口探针。

    返回 dict：final_url, html, js_text（拼起来的 JS 文本）,
    addresses（按出现顺序）, cfg（解析出的配置）, status_api。
    """
    final_url, html, status = fetch_text(url)
    js_texts = []
    if html:
        base = urllib.parse.urlparse(final_url)
        srcs = re.findall(
            r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', html,
            re.IGNORECASE)
        seen = set()
        js_urls = []
        for src in srcs:
            full = urllib.parse.urljoin(final_url, src)
            host = urllib.parse.urlparse(full).netloc
            if host != base.netloc or full in seen:
                continue
            seen.add(full)
            js_urls.append(full)
            if len(js_urls) >= MAX_JS_FILES:
                break
        if js_urls:
            from concurrent.futures import ThreadPoolExecutor

            def _get(u):
                base_name = u.rsplit("/", 1)[-1].lower()
                if any(k in base_name for k in SKIP_JS_NAMES):
                    return ""
                _, js, js_status = fetch_text(u, timeout=8, max_bytes=MAX_JS_BYTES)
                if js_status != 200 or not js:
                    return ""
                if len(js) > SKIP_JS_OVER_BYTES:
                    return ""
                return js
            with ThreadPoolExecutor(max_workers=4) as pool:
                js_texts = [t for t in pool.map(_get, js_urls) if t]
    combined = (html or "") + "\n" + "\n".join(js_texts)
    cfg = parse_config(combined)
    status_api = probe_status_api(final_url)
    site_apis = discover_site_apis(final_url, "\n".join(js_texts))
    # 站内 API 的数据比 HTML 解析更准，合并进 cfg
    for _path, data in site_apis.items():
        if isinstance(data, dict):
            if data.get("totalMinted") is not None:
                try:
                    cfg["site_minted"] = int(data["totalMinted"])
                except (ValueError, TypeError):
                    pass
            if data.get("maxShares") is not None:
                try:
                    cfg["total_lots"] = int(data["maxShares"])
                except (ValueError, TypeError):
                    pass
            if data.get("priceWei") is not None:
                try:
                    cfg["price_bnb"] = int(data["priceWei"]) / 10 ** 18
                except (ValueError, TypeError):
                    pass
            if data.get("costWei") is not None and cfg.get("price_bnb") is None:
                try:
                    cfg["price_bnb"] = int(data["costWei"]) / 10 ** 18
                except (ValueError, TypeError):
                    pass
            if data.get("tokensPerShareWei") is not None:
                cfg["per_lot_wei"] = data["tokensPerShareWei"]
            if data.get("walletBase") is not None:
                try:
                    cfg["cap_per_wallet"] = int(data["walletBase"])
                except (ValueError, TypeError):
                    pass
            if data.get("address"):
                addr = str(data["address"]).lower()
                if addr.startswith("0x") and len(addr) == 42:
                    cfg.setdefault("api_addresses", []).append(addr)
    if status_api:
        for key in ("totalMinted", "minted", "total_minted"):
            if isinstance(status_api.get(key), int) and cfg.get("site_minted") is None:
                cfg["site_minted"] = status_api[key]
    api_addrs = []
    if status_api:
        for key in ("contract", "sale", "mint", "token"):
            v = status_api.get(key)
            if isinstance(v, str) and v.lower().startswith("0x") and len(v) == 42:
                api_addrs.append(v.lower())
    cfg.setdefault("api_addresses", []).extend(api_addrs)
    all_addresses = extract_addresses(combined)
    for a in cfg.get("api_addresses", []):
        if a in all_addresses:
            all_addresses.remove(a)
        all_addresses.insert(0, a)
    return {
        "final_url": final_url,
        "http_status": status,
        "html": html or "",
        "js_text": "\n".join(js_texts),
        "addresses": all_addresses,
        "cfg": cfg,
        "status_api": status_api,
        "site_apis": site_apis,
    }
