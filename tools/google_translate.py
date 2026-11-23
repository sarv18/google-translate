"""
Async Google Translate client that never fakes a result.

Why this exists: googletrans (3.x and 4.x) calls translate_a/single, which
Google rate-limits with HTTP 429, and on any non-200 it silently returns the
input text as the "translation" (its DUMMY_DATA fallback).  This client talks
to two endpoints that are still served, and either returns a real translation
or raises TranslationError.

Backends, in order:
  1. t    - clients5.google.com/translate_a/t (client=dict-chrome-ex).
            GET; returns [[translation, detected_source]].  Fast and handles
            concurrent requests well.
  2. rpc  - the batchexecute RPC behind the translate.google.com web UI.
            POST body (no URL-length limit); returns translation + detected
            source.  Slower under concurrency, so it is the fallback.

If a backend looks blocked (429/403/5xx or a network error) it is skipped for
PRIMARY_COOLDOWN_SECONDS so a blocked IP does not add a failed round-trip to
every request.  Per-text problems (e.g. a 400 for a bad language code) do not
trigger the cooldown.
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass

import httpx

from tools.google_languages import LANGUAGES

T_URL = "https://clients5.google.com/translate_a/t"
T_CLIENT = "dict-chrome-ex"

RPC_URL = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
RPC_ID = "MkEWBc"
RPC_PARAMS = {
    "rpcids": RPC_ID,
    "bl": "boq_translate-webserver_20201207.13_p0",
    "soc-app": "1",
    "soc-platform": "1",
    "soc-device": "1",
    "rt": "c",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PRIMARY_COOLDOWN_SECONDS = 60
# Google caps a single request at 5000 characters; longer texts are split at
# sentence boundaries into chunks of at most this many characters.
MAX_CHUNK_CHARS = 4000
BLOCKED_STATUS = {403, 429, 500, 502, 503, 504}

# Google expects these with this exact casing.
_LANG_ALIASES = {"zh-cn": "zh-CN", "zh-tw": "zh-TW", "zh_cn": "zh-CN", "zh_tw": "zh-TW"}


class TranslationError(Exception):
    """Raised when no backend could translate the text."""


class BackendUnavailable(TranslationError):
    """The backend itself is refusing or blocking us (429/403/5xx, network error)."""


@dataclass
class Translation:
    text: str
    src: str  # detected source language code (e.g. "kn"); "" if unknown


def split_text(text, limit=MAX_CHUNK_CHARS):
    """Split `text` into chunks of at most `limit` chars, preferring sentence ends."""
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?।\n])", text):  # keep the terminator with its sentence
        if not sentence:
            continue
        if len(current) + len(sentence) <= limit:
            current += sentence
            continue
        if current:
            chunks.append(current)
        while len(sentence) > limit:  # one very long sentence: cut at whitespace
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        current = sentence
    if current:
        chunks.append(current)
    return chunks


def normalize_lang(code, allow_auto=False):
    """Lower-case, alias, and validate a language code. Raises TranslationError if unknown."""
    code = (code or "").strip().lower().replace("_", "-")
    if allow_auto and code in ("", "auto"):
        return "auto"
    if code not in LANGUAGES:
        raise TranslationError(f"invalid language code: {code!r}")
    return _LANG_ALIASES.get(code, code)


class GoogleTranslateClient:
    def __init__(self, timeout=15.0, logger=None):
        self._client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=timeout)
        self._logger = logger
        self._primary_down_until = 0.0
        # Instance attributes so tests can point a backend at a dead host.
        self.t_url = T_URL
        self.rpc_url = RPC_URL

    async def aclose(self):
        await self._client.aclose()

    # ------------------------------------------------------------------ public

    async def translate(self, text, dest, src="auto"):
        """Translate `text` into `dest`. Returns Translation or raises TranslationError."""
        if not text or not text.strip():
            return Translation(text=text, src="")
        dest, src = normalize_lang(dest), normalize_lang(src, allow_auto=True)
        if len(text) <= MAX_CHUNK_CHARS:
            return await self._with_fallback(text, dest, src)
        parts = await asyncio.gather(*(self._with_fallback(c, dest, src) for c in split_text(text)))
        return Translation(text=" ".join(p.text.strip() for p in parts), src=parts[0].src)

    async def detect(self, text):
        """Return the detected language code of `text` ("" for empty input)."""
        if not text or not text.strip():
            return ""
        # The cheapest call that reports the detected source is a translation to English.
        # The first chunk is plenty for detection.
        return (await self._with_fallback(text[:MAX_CHUNK_CHARS], "en", "auto")).src

    # ----------------------------------------------------------- backend chain

    async def _with_fallback(self, text, dest, src):
        errors = []
        if time.monotonic() >= self._primary_down_until:
            try:
                return await self._t_translate(text, dest, src)
            except BackendUnavailable as e:
                self._primary_down_until = time.monotonic() + PRIMARY_COOLDOWN_SECONDS
                self._warn(f"primary backend (translate_a/t) unavailable: {e}; "
                           f"using rpc backend for the next {PRIMARY_COOLDOWN_SECONDS}s")
                errors.append(f"t: {e}")
            except Exception as e:  # noqa: BLE001 - per-text failure, try the other backend
                errors.append(f"t: {e}")
        else:
            errors.append("t: skipped (on cooldown after a recent failure)")
        try:
            return await self._rpc_translate(text, dest, src)
        except Exception as e:  # noqa: BLE001
            errors.append(f"rpc: {e}")
        raise TranslationError("all translation backends failed: " + "; ".join(errors))

    async def _request(self, method, url, **kwargs):
        try:
            r = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise BackendUnavailable(f"{type(e).__name__}: {e}") from e
        if r.status_code in BLOCKED_STATUS:
            raise BackendUnavailable(f"HTTP {r.status_code} from {url}")
        if r.status_code != 200:
            raise TranslationError(f"HTTP {r.status_code} from {url}")
        return r

    # --------------------------------------------------------------- backends

    async def _t_translate(self, text, dest, src):
        r = await self._request(
            "GET", self.t_url, params={"client": T_CLIENT, "sl": src, "tl": dest, "q": text}
        )
        data = r.json()
        # [[translation, detected]] when sl=auto, [translation] when sl is fixed.
        item = data[0] if isinstance(data, list) and data else None
        if isinstance(item, list) and item and isinstance(item[0], str):
            translated = item[0]
            detected = item[1] if len(item) > 1 and isinstance(item[1], str) else ""
        elif isinstance(item, str):
            translated, detected = item, ""
        else:
            raise TranslationError(f"unexpected translate_a/t payload: {r.text[:120]!r}")
        return Translation(text=translated, src=detected or (src if src != "auto" else ""))

    async def _rpc_translate(self, text, dest, src):
        inner = json.dumps([[text, src, dest, True], [None]])
        f_req = json.dumps([[[RPC_ID, inner, None, "generic"]]])
        r = await self._request(
            "POST",
            self.rpc_url,
            params=RPC_PARAMS,
            data={"f.req": f_req},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )
        return self._parse_rpc(r.text, src)

    @staticmethod
    def _parse_rpc(body, src):
        # Body: ")]}'\n\n<len>\n[["wrb.fr","MkEWBc","<json payload>",...]]\n<len>\n[[...]]"
        # Decode each top-level array with raw_decode so brackets inside the
        # translated text cannot confuse the parser.
        decoder = json.JSONDecoder()
        payload = None
        idx = body.find("[[")
        while idx != -1 and payload is None:
            try:
                envelope, end = decoder.raw_decode(body, idx)
            except ValueError:
                idx = body.find("[[", idx + 2)
                continue
            for item in envelope:
                if isinstance(item, list) and len(item) > 2 and item[1] == RPC_ID and item[2]:
                    payload = json.loads(item[2])
                    break
            idx = body.find("[[", end)
        if payload is None:
            raise TranslationError(f"no {RPC_ID} payload in batchexecute response: {body[:120]!r}")

        try:
            sentence = payload[1][0][0]
            parts = sentence[5]
            spacing = sentence[3]
        except (IndexError, TypeError) as e:
            raise TranslationError(f"unexpected batchexecute payload shape: {e!r}") from e
        translated = (" " if spacing else "").join(p[0] for p in parts if p and p[0])
        if not translated:
            raise TranslationError("empty translation in batchexecute payload")

        detected = src
        if src == "auto":
            detected = ""
            for candidate in (payload[2] if len(payload) > 2 else None,
                              payload[0][2] if payload[0] and len(payload[0]) > 2 else None):
                if isinstance(candidate, str) and candidate:
                    detected = candidate
                    break
        return Translation(text=translated, src=detected)

    # ---------------------------------------------------------------- logging

    def _warn(self, message):
        if self._logger is not None:
            self._logger.warning(f"{__name__}: {message}")
        else:
            print(f"WARNING {__name__}: {message}")