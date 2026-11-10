"""BSC 只读链上查询库。

只做 eth_call / eth_getCode / eth_getStorageAt / eth_blockNumber 这类读操作。
不签名、不授权、不发交易、不碰私钥。

RPC 多节点自动切换，带超时和重试。批量查询用线程池并行。
不依赖第三方库，keccak-256 用纯 Python 实现，用来算函数选择器。
"""

import json
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

# 公共节点轮换。实测：单个 mint 静态调用本身只要 0.8 秒，失败全是
# 节点限流（HTTP 403 或直接断开），所以靠多节点分摊 + 节流 + 轮换解决，
# 不要把失败节点长期冷却（公共节点本来就抖）。
RPC_ENDPOINTS = [
    "https://bsc-dataseed.binance.org/",
    "https://bsc.publicnode.com",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed2.binance.org/",
    "https://bsc-dataseed3.binance.org/",
    "https://bsc-dataseed4.binance.org/",
    "https://binance.llamarpc.com",
    "https://bsc.drpc.org",
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-dataseed1.binance.org",
    "https://bsc-dataseed-public.bnbchain.org",
    "https://bsc-rpc.publicnode.com",
]

DEFAULT_TIMEOUT = 5
MAX_WORKERS = 4

# 节流：两次 RPC 请求之间至少间隔这么久，避免并行突发被公共节点限流。
MIN_REQ_INTERVAL = 0.3

# EIP-1967 实现地址槽位和 beacon 槽位
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# ---------------------------------------------------------------- keccak-256
# 纯 Python 实现，只用来算 4 字节函数选择器。已用已知向量自测：
# keccak256("") = c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
# selector("totalSupply()") = 18160ddd，selector("token()") = fc0c546a

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_R = [
    [0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56], [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rotl(x, n):
    return ((x << n) | (x >> (64 - n))) & _MASK if n else x


def _keccak_f(state):
    for rnd in range(24):
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
             for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(state[x + 5 * y], _R[x][y])
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y])
        state[0] ^= _RC[rnd]
    return state


def keccak256(data: bytes) -> bytes:
    rate = 136  # keccak-256: rate 1088 bits
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0x00)
    padded.append(0x80)
    state = [0] * 25
    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(len(block) // 8):
            state[i] ^= int.from_bytes(block[i * 8:(i + 1) * 8], "little")
        state = _keccak_f(state)
    out = b""
    while len(out) < 32:
        for i in range(rate // 8):
            out += state[i].to_bytes(8, "little")
        if len(out) >= 32:
            break
        state = _keccak_f(state)
    return out[:32]


def selector(signature: str) -> str:
    """函数签名的 4 字节选择器，返回 8 位小写 hex，不带 0x。"""
    return keccak256(signature.encode()).hex()[:8]


# ---------------------------------------------------------------- RPC

_rr_cursor = 0
_req_lock = threading.Lock()
_last_req_at = 0.0


class RpcCallError(Exception):
    """节点明确返回的 JSON-RPC 错误，例如 execution reverted。

    这是节点给出的确定答案（调用执行了，被合约拒绝），不是节点故障，
    收到它不要换节点重试。
    """

    def __init__(self, error):
        self.error = error
        super().__init__(str(error))


def _rpc_once(endpoint, method, params, timeout):
    global _last_req_at
    with _req_lock:
        wait = MIN_REQ_INTERVAL - (time.time() - _last_req_at)
        if wait > 0:
            time.sleep(wait)
        _last_req_at = time.time()
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    if "error" in payload:
        raise RpcCallError(payload["error"])
    return payload.get("result")


def rpc(method, params, timeout=DEFAULT_TIMEOUT):
    """调一个 RPC 方法，多节点轮换，每个节点只试一次。

    每次调用换一个起点轮换，避免总打同一个节点把它打限流。
    单次调用最坏耗时约 len(RPC_ENDPOINTS) * timeout 秒。
    """
    global _rr_cursor
    start = _rr_cursor % len(RPC_ENDPOINTS)
    _rr_cursor += 1
    order = RPC_ENDPOINTS[start:] + RPC_ENDPOINTS[:start]
    last_err = None
    for endpoint in order:
        try:
            return _rpc_once(endpoint, method, params, timeout)
        except RpcCallError:
            raise  # 业务错误是确定答案，不换节点
        except Exception as exc:  # noqa: BLE001 - 传输故障才换节点
            last_err = exc
            continue
    raise RuntimeError(f"RPC {method} 全部节点失败: {last_err}")


def eth_call(to, data, from_addr=None, value=0, block="latest"):
    """静态调用。返回 (ok, result_hex_or_error)。

    ok 为 True：调用成功，第二项是返回数据。
    ok 为 False：第二项是错误文本，分两种：业务回退（execution reverted
    带原因数据）和节点故障（超时、限流、断开），调用方要区分对待。
    """
    tx = {"to": to, "data": data}
    if from_addr:
        tx["from"] = from_addr
    if value:
        tx["value"] = hex(value)
    try:
        result = rpc("eth_call", [tx, block])
        return True, result if isinstance(result, str) else ""
    except RpcCallError as exc:
        err = exc.error
        if isinstance(err, dict):
            msg = err.get("message", "") or ""
            data = err.get("data", "") or ""
            if data:
                return False, f"execution reverted: {data}"
            return False, msg or str(err)
        return False, str(err)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def eth_get_code(address):
    """读字节码。失败返回 ""（读失败）和 "0x"（确实无代码）要区分开。

    公共节点抖动时失败一次就睡 1 秒再试一次。
    """
    for attempt in range(2):
        try:
            result = rpc("eth_getCode", [address, "latest"])
            return result if isinstance(result, str) else "0x"
        except Exception:  # noqa: BLE001
            if attempt == 0:
                time.sleep(1)
    return ""


def eth_get_storage_at(address, slot):
    for attempt in range(2):
        try:
            result = rpc("eth_getStorageAt", [address, slot, "latest"])
            return result if isinstance(result, str) else "0x"
        except Exception:  # noqa: BLE001
            if attempt == 0:
                time.sleep(1)
    return ""


def eth_block_number():
    try:
        result = rpc("eth_blockNumber", [])
        return int(result, 16) if result else 0
    except Exception:  # noqa: BLE001
        return 0


def call_many(calls, max_workers=MAX_WORKERS):
    """并行发一批 eth_call。

    calls 是 (key, to, data, from_addr, value) 的列表。
    返回 {key: (ok, result)}。
    """
    def _one(call):
        key, to, data, from_addr, value = call
        return key, eth_call(to, data, from_addr=from_addr, value=value)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for key, value in pool.map(_one, calls):
            results[key] = value
    return results


# ---------------------------------------------------------------- ABI 解码

def u256(hexstr):
    """32 字节 word 解成整数，解不出返回 None。"""
    if not hexstr or not isinstance(hexstr, str) or not hexstr.startswith("0x"):
        return None
    body = hexstr[2:]
    if len(body) < 64:
        return None
    try:
        return int(body[:64], 16)
    except ValueError:
        return None


def decode_address(hexstr):
    """32 字节 word 解成地址，解不出返回 None。"""
    value = u256(hexstr)
    if value is None:
        return None
    addr = "0x" + format(value & ((1 << 160) - 1), "040x")
    return addr


def decode_string(hexstr):
    """ABI 编码的 string 解码，解不出返回 None。"""
    if not hexstr or not hexstr.startswith("0x"):
        return None
    try:
        raw = bytes.fromhex(hexstr[2:])
    except ValueError:
        return None
    if len(raw) < 64:
        return None
    try:
        length = int.from_bytes(raw[32:64], "big")
        text = raw[64:64 + length].decode("utf-8", "replace")
        return text
    except Exception:  # noqa: BLE001
        return None


def decode_revert(data):
    """把 eth_call 的 revert 数据解成人类可读原因，解不出返回原文本。"""
    if not data or not isinstance(data, str):
        return ""
    body = data[2:] if data.startswith("0x") else data
    if body.startswith("08c379a0"):  # Error(string)
        try:
            raw = bytes.fromhex(body[8:])
            length = int.from_bytes(raw[32:64], "big")
            return raw[64:64 + length].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return data
    if body.startswith("4e487b71"):  # Panic(uint256)
        try:
            code = int(body[8:72], 16)
            return f"Panic({code})"
        except Exception:  # noqa: BLE001
            return data
    if len(body) == 8:  # 自定义错误，只有 4 字节选择器
        return f"自定义错误 0x{body}（合约自定错误名，未解码）"
    if "revert" in data.lower():
        return data
    return data


def extract_push4_selectors(code_hex):
    """从合约字节码里提取所有 PUSH4 后面的 4 字节选择器。"""
    if not code_hex or not code_hex.startswith("0x"):
        return set()
    try:
        code = bytes.fromhex(code_hex[2:])
    except ValueError:
        return set()
    found = set()
    i = 0
    while i + 5 <= len(code):
        if code[i] == 0x63:  # PUSH4
            found.add(code[i + 1:i + 5].hex())
            i += 5
        else:
            i += 1
    return found


def is_proxy(code_hex, address):
    """读 EIP-1967 槽位，判断是不是代理合约。返回 (是否代理, 实现地址或 None)。"""
    if not code_hex or code_hex in ("0x", ""):
        return False, None
    slot = eth_get_storage_at(address, EIP1967_IMPL_SLOT)
    if slot and len(slot) >= 42:
        impl = "0x" + slot[-40:]
        if impl != ZERO_ADDRESS:
            return True, impl
    return False, None


# ---------------------------------------------------------------- 常用选择器

SEL = {
    "totalSupply()": "18160ddd",
    "decimals()": "313ce567",
    "symbol()": "95d89b41",
    "name()": "06fdde03",
    "balanceOf(address)": "70a08231",
    "totalMinted()": "a2309ff8",
    "token()": "fc0c546a",
    "mintedByWallet(address)": "0d758111",
    "mintFree()": "8ab53447",  # 运行时用 keccak 重算；注意 BROCCOLI 的免费铸造
    # 选择器 0xc4310955 对不上 mintFree() 等常见签名，历史库里按原始选择器存，不硬猜签名
    "mint(uint256)": "a0712d68",  # 运行时用 keccak 重算
}

# 运行时用 keccak 现算，覆盖上面可能记错的值
for _sig in list(SEL):
    SEL[_sig] = selector(_sig)

# 候选价格类只读函数，逐个试，看哪个有响应
PRICE_CANDIDATES = [
    "price()", "mintPrice()", "cost()", "getPrice()", "salePrice()",
    "PRICE()", "mintCost()",
]

# 候选状态类只读函数，逐个试
STATE_CANDIDATES = [
    "mintEnabled()", "launched()", "maxSupply()", "MAX_SUPPLY()",
    "maxPerWallet()", "startTime()", "endTime()", "maxMint()",
    "stats()", "saleStart()", "saleEnds()",
]

# 候选 mint 函数签名，用来反查字节码里的选择器对应哪个签名
MINT_SIGNATURES = [
    "mintFree()", "mintFree(address)",
    "mint(uint256)", "mint(uint256,address)", "mint(address,uint256)",
    "mint()", "buy(uint256)", "purchase(uint256)",
    "mintWithReferral(uint256,address)", "claim()",
]
