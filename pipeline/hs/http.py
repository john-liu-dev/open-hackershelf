"""统一 HTTP 客户端：按域名限速、重试、磁盘缓存、User-Agent 带联系邮箱。

所有外部请求都走这里（CLAUDE.md 硬约束）。三种用法：
- `Http().get(url, params)`：小请求，默认写磁盘缓存（data/cache/http/<host>/...，zstd 压缩）。
- `Http().download(url, dest)`：大文件流式下载，断点续传，完成后原子改名。
- `Http().range_file(url)`：给 pyarrow 用的只读文件对象，按需发 Range 请求（只拉需要的列）。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import zstandard

from .config import PATHS, cfg, env

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class CachedResponse:
    url: str
    status_code: int
    headers: dict
    content: bytes
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} for {self.url}", request=None, response=None  # type: ignore[arg-type]
            )


@dataclass
class _HostLimiter:
    interval_s: float
    concurrency: int
    lock: threading.Lock = field(default_factory=threading.Lock)
    next_at: float = 0.0
    sem: threading.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.sem = threading.Semaphore(self.concurrency)

    def wait_turn(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval_s
        if delay > 0:
            time.sleep(delay)


def user_agent() -> str:
    ua = cfg()["http"]["user_agent"]
    email = env("CONTACT_EMAIL")
    return f"{ua[:-1]}; mailto:{email})" if email and ua.endswith(")") else ua


class Http:
    def __init__(self, cache_dir: Path | None = None) -> None:
        c = cfg()["http"]
        self.cache_dir = cache_dir or PATHS.cache / "http"
        self.max_retries = int(c["max_retries"])
        self._rates = c["rate"]
        self._limiters: dict[str, _HostLimiter] = {}
        self._lim_lock = threading.Lock()
        # 代理：显式用 HTTPS_PROXY（http 代理）。trust_env 会让 ALL_PROXY 的 socks5 生效，实测慢一半。
        # no_proxy_hosts 里的域名直连（例如国内镜像）。
        proxy = env("HTTPS_PROXY") or env("https_proxy") or env("HTTP_PROXY") or env("http_proxy") or None
        mounts = {f"all://{h}": httpx.HTTPTransport(retries=0) for h in c.get("no_proxy_hosts", [])}
        mounts["all://"] = httpx.HTTPTransport(proxy=proxy, retries=0) if proxy else httpx.HTTPTransport(retries=0)
        self.client = httpx.Client(
            headers={"User-Agent": user_agent()},
            timeout=httpx.Timeout(float(c["timeout_s"]), connect=20.0),
            follow_redirects=True,
            trust_env=False,
            mounts=mounts,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "bytes": 0}

    # ---------- 限速 ----------
    def limiter(self, host: str) -> _HostLimiter:
        # 没有 CONTACT_EMAIL 时 User-Agent 不带邮箱，所有域名的请求间隔加倍（docs/OVERNIGHT.md 规则）
        factor = 1.0 if env("CONTACT_EMAIL") else 2.0
        with self._lim_lock:
            if host not in self._limiters:
                r = self._rates.get(host) or self._rates["default"]
                self._limiters[host] = _HostLimiter(float(r["interval_s"]) * factor, int(r["concurrency"]))
            return self._limiters[host]

    def _send(self, method: str, url: str, *, headers: dict | None = None, stream: bool = False):
        """限速 + 重试。stream=True 时返回未读取 body 的 httpx.Response（调用方负责关闭）。"""
        lim = self.limiter(urlsplit(url).hostname or "")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            with lim.sem:
                lim.wait_turn()
                try:
                    req = self.client.build_request(method, url, headers=headers)
                    resp = self.client.send(req, stream=stream)
                    self.stats["requests"] += 1
                except httpx.TransportError as e:
                    last_exc = e
                    resp = None
            if resp is not None and resp.status_code not in RETRY_STATUS:
                return resp
            if attempt == self.max_retries:
                break
            self.stats["retries"] += 1
            wait = min(120.0, 2.0 ** attempt) + random.uniform(0, 1)
            if resp is not None:
                ra = resp.headers.get("retry-after")
                if ra and ra.isdigit():
                    wait = max(wait, float(ra))
                resp.close()
            time.sleep(wait)
        if last_exc:
            raise last_exc
        return resp  # 最后一次的 429/5xx，交给调用方处理

    # ---------- 带缓存的小请求 ----------
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        host = urlsplit(url).hostname or "unknown"
        return self.cache_dir / host / h[:2] / h

    def get(
        self,
        url: str,
        params: dict | None = None,
        *,
        cache: bool = True,
        ttl_s: float | None = None,
        cache_status: tuple[int, ...] = (200,),
        headers: dict | None = None,
        secret_params: dict | None = None,
    ) -> CachedResponse:
        """secret_params（如 API key）只拼进实际请求，不进缓存键、不写进缓存元数据。"""
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
        send_url = f"{url}{'&' if '?' in url else '?'}{urlencode(secret_params)}" if secret_params else url
        p = self._cache_path(url)
        meta_p, body_p = p.with_suffix(".json"), p.with_suffix(".zst")
        if cache and meta_p.exists() and body_p.exists():
            meta = json.loads(meta_p.read_text())
            if ttl_s is None or time.time() - meta["fetched_at"] < ttl_s:
                self.stats["cache_hits"] += 1
                body = zstandard.ZstdDecompressor().decompress(body_p.read_bytes())
                return CachedResponse(url, meta["status"], meta["headers"], body, from_cache=True)
        resp = self._send("GET", send_url, headers=headers)
        # x-ratelimit-*（OpenAlex 的额度余量和单次费用）也带上，调用方据此控制每日预算
        out = CachedResponse(url, resp.status_code, {k: v for k, v in resp.headers.items()
                                                     if k in ("content-type", "etag", "last-modified") or k.startswith("x-ratelimit-")}, resp.content)
        self.stats["bytes"] += len(resp.content)
        if cache and resp.status_code in cache_status:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = body_p.with_suffix(".zst.tmp")
            tmp.write_bytes(zstandard.ZstdCompressor(level=6).compress(resp.content))
            tmp.replace(body_p)
            meta_p.write_text(json.dumps({"url": url, "status": resp.status_code, "headers": out.headers, "fetched_at": time.time()}))
        return out

    # ---------- 大文件下载 ----------
    def download(self, url: str, dest: Path, *, chunk: int = 1 << 20) -> Path:
        """流式下载到 dest；中断后从 .part 续传；完成后原子改名。已存在则跳过。"""
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        for attempt in range(self.max_retries + 1):
            have = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else None
            try:
                resp = self._send("GET", url, headers=headers, stream=True)
                if resp.status_code == 416:  # 已下载完整
                    resp.close()
                    break
                if resp.status_code >= 400:
                    resp.close()
                    raise httpx.HTTPStatusError(f"{resp.status_code} for {url}", request=resp.request, response=resp)
                mode = "ab" if have and resp.status_code == 206 else "wb"
                with open(part, mode) as f:
                    for b in resp.iter_bytes(chunk):
                        f.write(b)
                        self.stats["bytes"] += len(b)
                resp.close()
                break
            except (httpx.TransportError, httpx.StreamError):
                if attempt == self.max_retries:
                    raise
                time.sleep(min(60.0, 2.0 ** attempt))
        part.replace(dest)
        return dest

    def download_segmented(
        self, url: str, dest: Path, *, size: int, sha256: str | None = None,
        seg: int = 8 << 20, workers: int = 6,
    ) -> Path:
        """大文件分段并发下载（每段一个 Range 请求），断点续传，可选 sha256 校验，完成后原子改名。

        进度记在 <dest>.part.done（已完成段号，一行一个）。sha256 不符时删掉 .part 并抛错。
        """
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        done_p = dest.with_name(dest.name + ".part.done")
        nseg = max(1, (size + seg - 1) // seg)
        done = set(int(x) for x in done_p.read_text().split()) if done_p.exists() and part.exists() else set()
        if not part.exists():
            with open(part, "wb") as f:
                f.truncate(size)
            done = set()
        todo = [i for i in range(nseg) if i not in done]
        lock = threading.Lock()
        fd = os.open(part, os.O_WRONLY)
        try:
            def fetch(i: int) -> None:
                start = i * seg
                end = min(size, start + seg) - 1
                data = self.read_range(url, start, end)
                os.pwrite(fd, data, start)
                with lock:
                    with open(done_p, "a") as f:
                        f.write(f"{i}\n")

            with ThreadPoolExecutor(workers) as ex:
                for fut in as_completed([ex.submit(fetch, i) for i in todo]):
                    fut.result()
        finally:
            os.close(fd)
        if sha256:
            h = hashlib.sha256()
            with open(part, "rb") as f:
                for b in iter(lambda: f.read(1 << 22), b""):
                    h.update(b)
            if h.hexdigest() != sha256:
                part.unlink(missing_ok=True)
                done_p.unlink(missing_ok=True)
                raise ValueError(f"sha256 不符：{url}")
        part.replace(dest)
        done_p.unlink(missing_ok=True)
        return dest

    # ---------- Range 读取（给 pyarrow 用） ----------
    def head_size(self, url: str) -> int:
        resp = self._send("GET", url, headers={"Range": "bytes=0-0"}, stream=True)
        resp.close()
        cr = resp.headers.get("content-range", "")
        if "/" not in cr:
            raise RuntimeError(f"服务器不支持 Range: {url} ({resp.status_code})")
        return int(cr.rsplit("/", 1)[1])

    def read_range(self, url: str, start: int, end_inclusive: int) -> bytes:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._send("GET", url, headers={"Range": f"bytes={start}-{end_inclusive}"})
                if resp.status_code != 206:
                    raise RuntimeError(f"Range 请求返回 {resp.status_code}: {url}")
                body = resp.content
                if len(body) != end_inclusive - start + 1:
                    raise httpx.StreamError("short read")
                self.stats["bytes"] += len(body)
                return body
            except (httpx.TransportError, httpx.StreamError):
                if attempt == self.max_retries:
                    raise
                time.sleep(min(60.0, 2.0 ** attempt))
        raise AssertionError("unreachable")

    def range_file(self, url: str) -> "RangeFile":
        return RangeFile(self, url)

    def close(self) -> None:
        self.client.close()


class RangeFile(io.RawIOBase):
    """只读、可 seek 的远程文件；每次 read 发一个 Range 请求，带一个小的尾部缓存。"""

    def __init__(self, http: Http, url: str, size: int | None = None) -> None:
        self.http, self.url = http, url
        self.size = size if size is not None else http.head_size(url)
        self.pos = 0
        self._tail: tuple[int, bytes] | None = None

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self.pos, 2: self.size}[whence]
        self.pos = max(0, min(self.size, base + offset))
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        if self._tail and self.pos >= self._tail[0]:
            off = self.pos - self._tail[0]
            data = self._tail[1][off : off + n]
            if len(data) == n:
                self.pos += n
                return data
        if self.size - self.pos <= 1 << 20 and n < 1 << 20:  # 文件尾（footer）一次拉 1MB
            start = max(0, self.size - (1 << 20))
            self._tail = (start, self.http.read_range(self.url, start, self.size - 1))
            return self.read(n)
        data = self.http.read_range(self.url, self.pos, self.pos + n - 1)
        self.pos += n
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)
