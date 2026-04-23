import base64
import hashlib
import json
import re
import time
import warnings
from dataclasses import replace
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
import urllib3

from kugou_models import (
    KugouPrivUrlOptions,
    KugouResolveResponse,
    KugouResolvedTrack,
    KugouSearchResponse,
    KugouWebSearchOptions,
    as_string_dict,
    extract_play_urls,
    extract_song_hash,
)


SEARCH_API_URL = "https://gateway.kugou.com/v3/search/song"
WEB_SEARCH_API_URL = "https://complexsearch.kugou.com/v2/search/song"
WEB_SEARCH_RETRY_API_URL = "https://complexsearchretry.kugou.com/v2/search/song"
PRIV_URL_API_URL = "https://gateway.kugou.com/tracker/v6/priv_url"
LYRIC_SEARCH_API_URL = "http://krcs.kugou.com/search"
LYRIC_DOWNLOAD_API_URL = "http://lyrics.kugou.com/download"
PLAY_DATA_API_URL = "https://www.kugou.com/yy/index.php?r=play/getdata"
H5_SIGN_SECRET = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
PRIV_URL_SIGN_SECRET = "OIlwieks28dk2k092lksi2UIkp"
TRACKER_KEY_SEED = "185672dd44712f60bb1736df5a377e82"
JSONP_PATTERN = re.compile(r"^\s*[$\w]+\((.*)\)\s*;?\s*$", re.S)


class KugouApiError(RuntimeError):
    """Raised when the Kugou gateway returns a business-level error."""


def _md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _normalize_duration_ms(duration: Any) -> int | None:
    if duration in (None, ""):
        return None
    try:
        value = int(float(duration))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 1000:
        return value * 1000
    return value


def _decode_lyric_bytes(data: bytes, charset: str = "utf8") -> str:
    encodings = [charset or "utf8", "utf-8-sig", "utf-8", "gb18030", "gbk"]
    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_lyric_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n") if line.strip()]
    return "\n".join(lines)


def _make_web_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.kugou.com/yy/html/search.html",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
    }


def _make_client_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "KuGou/20.1.11 (Windows NT 10.0; Win64; x64)",
    }


def parse_json_or_jsonp(raw_text: str) -> dict[str, Any]:
    """Parse either JSON or JSONP from Kugou search responses."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        match = JSONP_PATTERN.match(raw_text)
        if not match:
            raise ValueError("response is not valid JSON or JSONP") from None
        payload = json.loads(match.group(1))

    if not isinstance(payload, dict):
        raise ValueError("response payload is not a JSON object")
    return payload


class KugouSearchClient:
    """Reusable Kugou client for search, signed replay, and priv_url resolution."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        verify: bool | str = True,
        retries: int = 2,
        retry_delay: float = 1.0,
        web_timeout: float = 15.0,
        client_timeout: float = 20.0,
        resolve_timeout: float = 15.0,
        web_headers: Mapping[str, str] | None = None,
        client_headers: Mapping[str, str] | None = None,
        resolve_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.verify = verify
        self._ssl_fallback_used = False
        self.retries = retries
        self.retry_delay = retry_delay
        self.web_timeout = web_timeout
        self.client_timeout = client_timeout
        self.resolve_timeout = resolve_timeout
        self.web_headers = _make_web_headers()
        self.client_headers = _make_client_headers()
        self.resolve_headers = {}
        if web_headers:
            self.web_headers.update(dict(web_headers))
        if client_headers:
            self.client_headers.update(dict(client_headers))
        if resolve_headers:
            self.resolve_headers.update(dict(resolve_headers))
        if verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return self.session.request(method, url, verify=self.verify, **kwargs)
        except requests.exceptions.SSLError as exc:
            if self.verify is not True or "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
            if not self._ssl_fallback_used:
                warnings.warn(
                    "SSL certificate verification failed; falling back to verify=False for this session.",
                    RuntimeWarning,
                )
                self._ssl_fallback_used = True
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return self.session.request(method, url, verify=False, **kwargs)

    @staticmethod
    def sign_web_params(params: Mapping[str, Any]) -> dict[str, str]:
        """
        Sign web/H5 search params using the same rule as `window.infSign(..., useH5: true)`.

        Rule recovered from `infSign.min.js`:
        md5(secret + "key=valuekey=value..." + secret)
        """
        normalized = as_string_dict(params)
        sign_material = "".join(f"{key}={normalized[key]}" for key in sorted(normalized))
        signed = dict(normalized)
        signed["signature"] = _md5_hex(f"{H5_SIGN_SECRET}{sign_material}{H5_SIGN_SECRET}")
        return signed

    @staticmethod
    def sign_priv_url_params(params: Mapping[str, Any], body: Mapping[str, Any]) -> str:
        normalized = as_string_dict(params)
        params_string = "".join(f"{key}={normalized[key]}" for key in sorted(normalized))
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        return _md5_hex(f"{PRIV_URL_SIGN_SECRET}{params_string}{body_json}{PRIV_URL_SIGN_SECRET}")

    @staticmethod
    def build_priv_tracker_key(song_hash: str, options: KugouPrivUrlOptions) -> str:
        normalized_hash = options.normalize_hash(song_hash)
        return _md5_hex(
            f"{normalized_hash}{TRACKER_KEY_SEED}{options.appid}{options.mid}{options.userid}"
        )

    @staticmethod
    def build_signed_client_url(params: Mapping[str, Any], base_url: str = SEARCH_API_URL) -> str:
        normalized = as_string_dict(params)
        if not normalized.get("signature"):
            raise ValueError("params must include a valid client-generated signature")
        return f"{base_url}?{urlencode(normalized)}"

    @staticmethod
    def parse_response_text(raw_text: str) -> dict[str, Any]:
        return parse_json_or_jsonp(raw_text)

    def _resolve_search_options(
        self,
        options: KugouWebSearchOptions | None = None,
        **overrides: Any,
    ) -> KugouWebSearchOptions:
        resolved = options or KugouWebSearchOptions()
        if overrides:
            resolved = replace(resolved, **overrides)
        return resolved

    def _resolve_priv_options(
        self,
        options: KugouPrivUrlOptions | None = None,
        **overrides: Any,
    ) -> KugouPrivUrlOptions:
        resolved = options or KugouPrivUrlOptions()
        if overrides:
            resolved = replace(resolved, **overrides)
        return resolved

    def build_search_params(
        self,
        keyword: str,
        *,
        options: KugouWebSearchOptions | None = None,
        **overrides: Any,
    ) -> dict[str, str]:
        resolved = self._resolve_search_options(options, **overrides)
        now_ms = int(resolved.clienttime if resolved.clienttime is not None else time.time() * 1000)
        unsigned = resolved.build_unsigned_params(keyword, clienttime_ms=now_ms)
        return self.sign_web_params(unsigned)

    def build_search_url(
        self,
        keyword: str,
        *,
        base_url: str = WEB_SEARCH_API_URL,
        options: KugouWebSearchOptions | None = None,
        **overrides: Any,
    ) -> str:
        params = self.build_search_params(keyword, options=options, **overrides)
        return f"{base_url}?{urlencode(params)}"

    def build_resolve_request(
        self,
        song_hash: str,
        *,
        options: KugouPrivUrlOptions | None = None,
        **overrides: Any,
    ) -> tuple[str, dict[str, str], str]:
        resolved = self._resolve_priv_options(options, **overrides)
        now = time.time()
        clienttime = int(now)
        clienttime_ms = int(now * 1000)
        tracker_key = self.build_priv_tracker_key(song_hash, resolved)
        body = resolved.build_request_body(song_hash, clienttime_ms=clienttime_ms, tracker_key=tracker_key)
        params = resolved.build_query_params(clienttime=clienttime)
        params["signature"] = self.sign_priv_url_params(params, body)
        headers = resolved.build_headers(clienttime=clienttime)
        headers.update(self.resolve_headers)
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        request_url = f"{PRIV_URL_API_URL}?{urlencode(params)}"
        return request_url, headers, body_text

    def fetch_lyric(
        self,
        song_hash: str,
        *,
        keyword: str = "",
        duration_ms: int | None = None,
        fmt: str = "lrc",
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_hash = song_hash.strip()
        if not normalized_hash:
            raise ValueError("song_hash must not be empty")

        request_headers = dict(self.web_headers)
        if headers:
            request_headers.update(dict(headers))

        effective_timeout = self.web_timeout if timeout is None else timeout
        normalized_duration = _normalize_duration_ms(duration_ms)
        search_params = {
            "ver": 1,
            "man": "yes",
            "client": "mobi",
            "hash": normalized_hash,
        }
        if keyword:
            search_params["keyword"] = keyword
        if normalized_duration is not None:
            search_params["duration"] = normalized_duration

        search_response = self._request(
            "GET",
            LYRIC_SEARCH_API_URL,
            params=search_params,
            headers=request_headers,
            timeout=effective_timeout,
        )
        search_response.raise_for_status()
        search_payload = search_response.json()

        candidates = search_payload.get("candidates")
        if not isinstance(candidates, list):
            candidates = []
        lyric_candidates = [item for item in candidates if isinstance(item, dict)]
        if normalized_duration is not None and lyric_candidates:
            lyric_candidates.sort(
                key=lambda item: (
                    abs(int(item.get("duration") or 0) - normalized_duration),
                    -int(item.get("score") or 0),
                )
            )

        if lyric_candidates:
            candidate = lyric_candidates[0]
            download_params = {
                "ver": 1,
                "client": "pc",
                "id": candidate.get("id"),
                "accesskey": candidate.get("accesskey"),
                "fmt": fmt,
                "charset": "utf8",
            }
            download_response = self._request(
                "GET",
                LYRIC_DOWNLOAD_API_URL,
                params=download_params,
                headers=request_headers,
                timeout=effective_timeout,
            )
            download_response.raise_for_status()
            download_payload = download_response.json()
            content = download_payload.get("content")
            if content:
                lyric_bytes = base64.b64decode(str(content))
                lyric_text = _normalize_lyric_text(
                    _decode_lyric_bytes(lyric_bytes, str(download_payload.get("charset") or "utf8"))
                )
                return {
                    "text": lyric_text,
                    "source": "lyrics_download",
                    "format": download_payload.get("fmt") or fmt,
                    "search_status": search_payload.get("status"),
                    "download_status": download_payload.get("status"),
                    "candidate_id": candidate.get("id"),
                    "accesskey": candidate.get("accesskey"),
                }

        playdata_response = self._request(
            "GET",
            PLAY_DATA_API_URL,
            params={"hash": normalized_hash, "mid": str(int(time.time() * 1000))},
            headers=request_headers,
            timeout=effective_timeout,
        )
        playdata_response.raise_for_status()
        playdata_payload = playdata_response.json()
        playdata = playdata_payload.get("data")
        if isinstance(playdata, dict):
            lyrics = playdata.get("lyrics")
            if lyrics:
                return {
                    "text": _normalize_lyric_text(str(lyrics)),
                    "source": "play_getdata",
                    "format": "lrc",
                    "search_status": search_payload.get("status"),
                    "download_status": playdata_payload.get("status"),
                    "candidate_id": None,
                    "accesskey": None,
                }

        return {
            "text": None,
            "source": None,
            "format": fmt,
            "search_status": search_payload.get("status"),
            "download_status": None,
            "candidate_id": None,
            "accesskey": None,
        }

    def search(
        self,
        keyword: str,
        *,
        options: KugouWebSearchOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> KugouSearchResponse:
        signed_params = self.build_search_params(keyword, options=options, **overrides)
        request_headers = dict(self.web_headers)
        if headers:
            request_headers.update(dict(headers))

        errors: list[str] = []
        effective_timeout = self.web_timeout if timeout is None else timeout

        for url in (WEB_SEARCH_API_URL, WEB_SEARCH_RETRY_API_URL):
            for attempt in range(1, self.retries + 1):
                try:
                    response = self._request(
                        "GET",
                        url,
                        params=signed_params,
                        headers=request_headers,
                        timeout=effective_timeout,
                    )
                    response.raise_for_status()
                    payload = self.parse_response_text(response.text)
                    if payload.get("status") != 1:
                        raise KugouApiError(
                            f"Kugou business error: error_code={payload.get('error_code')} "
                            f"message={payload.get('message') or payload.get('error_msg')!r}"
                        )
                    return KugouSearchResponse(payload)
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "?"
                    errors.append(f"{url} -> HTTP {status_code}")
                    if attempt < self.retries:
                        time.sleep(self.retry_delay)
                        continue
                except (requests.RequestException, ValueError, KugouApiError) as exc:
                    errors.append(f"{url} -> {exc}")
                    break

        raise RuntimeError("request failed; attempts: " + " | ".join(errors))

    def search_payload(
        self,
        keyword: str,
        *,
        options: KugouWebSearchOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        return self.search(
            keyword,
            options=options,
            timeout=timeout,
            headers=headers,
            **overrides,
        ).payload

    def search_all_pages(
        self,
        keyword: str,
        *,
        options: KugouWebSearchOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> list[KugouSearchResponse]:
        resolved_options = self._resolve_search_options(options, **overrides)
        first_response = self.search(
            keyword,
            options=resolved_options,
            timeout=timeout,
            headers=headers,
        )
        responses = [first_response]

        total = first_response.total
        if total in (None, ""):
            return responses

        total_count = int(total)
        page_size = max(int(resolved_options.pagesize), 1)
        start_page = max(int(resolved_options.page), 1)
        total_pages = max((total_count + page_size - 1) // page_size, start_page)

        for page in range(start_page + 1, total_pages + 1):
            page_options = replace(resolved_options, page=page)
            responses.append(
                self.search(
                    keyword,
                    options=page_options,
                    timeout=timeout,
                    headers=headers,
                )
            )

        return responses

    def replay_signed_search(
        self,
        signed_url: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        allow_tracker_fallback: bool = True,
    ) -> KugouSearchResponse:
        parsed = urlsplit(signed_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("signed_url must be a full URL")

        request_headers = dict(self.client_headers)
        if headers:
            request_headers.update(dict(headers))

        errors: list[str] = []
        effective_timeout = self.client_timeout if timeout is None else timeout
        candidate_urls = [signed_url]
        if allow_tracker_fallback and parsed.path == "/v3/search/song":
            tracker_url = urlunsplit(
                (parsed.scheme, parsed.netloc, "/tracker/v3/search/song", parsed.query, parsed.fragment)
            )
            candidate_urls.append(tracker_url)

        for url in candidate_urls:
            for attempt in range(1, self.retries + 1):
                try:
                    response = self._request(
                        "GET",
                        url,
                        headers=request_headers,
                        timeout=effective_timeout,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("status") != 1:
                        raise KugouApiError(
                            f"Kugou business error: error_code={payload.get('error_code')} "
                            f"message={payload.get('message')!r}"
                        )
                    return KugouSearchResponse(payload)
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "?"
                    errors.append(f"{url} -> HTTP {status_code}")
                    if attempt < self.retries:
                        time.sleep(self.retry_delay)
                        continue
                except (requests.RequestException, ValueError, KugouApiError) as exc:
                    errors.append(f"{url} -> {exc}")
                    break

        raise RuntimeError("request failed; attempts: " + " | ".join(errors))

    def replay_signed_payload(
        self,
        signed_url: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        allow_tracker_fallback: bool = True,
    ) -> dict[str, Any]:
        return self.replay_signed_search(
            signed_url,
            timeout=timeout,
            headers=headers,
            allow_tracker_fallback=allow_tracker_fallback,
        ).payload

    def resolve_song(
        self,
        song_hash: str,
        *,
        options: KugouPrivUrlOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> KugouResolveResponse:
        request_url, request_headers, body_text = self.build_resolve_request(
            song_hash,
            options=options,
            **overrides,
        )
        if headers:
            request_headers.update(dict(headers))

        errors: list[str] = []
        effective_timeout = self.resolve_timeout if timeout is None else timeout

        for attempt in range(1, self.retries + 1):
            try:
                response = self._request(
                    "POST",
                    request_url,
                    data=body_text,
                    headers=request_headers,
                    timeout=effective_timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != 1:
                    raise KugouApiError(
                        f"Kugou business error: error_code={payload.get('error_code')} "
                        f"message={payload.get('message')!r}"
                    )
                return KugouResolveResponse(payload)
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else "?"
                errors.append(f"{PRIV_URL_API_URL} -> HTTP {status_code}")
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
                    continue
            except (requests.RequestException, ValueError, KugouApiError) as exc:
                errors.append(f"{PRIV_URL_API_URL} -> {exc}")
                break

        raise RuntimeError("request failed; attempts: " + " | ".join(errors))

    def resolve_song_payload(
        self,
        song_hash: str,
        *,
        options: KugouPrivUrlOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        return self.resolve_song(
            song_hash,
            options=options,
            timeout=timeout,
            headers=headers,
            **overrides,
        ).payload

    def resolve_from_search_item(
        self,
        item: Mapping[str, Any],
        *,
        options: KugouPrivUrlOptions | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> KugouResolveResponse:
        song_hash = extract_song_hash(item)
        if not song_hash:
            raise ValueError("search item does not contain a usable hash")
        return self.resolve_song(
            song_hash,
            options=options,
            timeout=timeout,
            headers=headers,
            **overrides,
        )

    def search_and_resolve_first(
        self,
        keyword: str,
        *,
        search_index: int = 0,
        preferred_qualities: Sequence[str] | None = None,
        search_options: KugouWebSearchOptions | None = None,
        resolve_options: KugouPrivUrlOptions | None = None,
        search_timeout: float | None = None,
        resolve_timeout: float | None = None,
        search_headers: Mapping[str, str] | None = None,
        resolve_headers: Mapping[str, str] | None = None,
        **search_overrides: Any,
    ) -> KugouResolvedTrack:
        search_response = self.search(
            keyword,
            options=search_options,
            timeout=search_timeout,
            headers=search_headers,
            **search_overrides,
        )
        if search_index < 0 or search_index >= len(search_response.items):
            raise IndexError(
                f"search_index={search_index} is out of range for {len(search_response.items)} search results"
            )

        search_item = search_response.items[search_index]
        resolve_response = self.resolve_from_search_item(
            search_item,
            options=resolve_options,
            timeout=resolve_timeout,
            headers=resolve_headers,
        )
        resolved_item = resolve_response.choose_item(preferred_qualities=preferred_qualities)
        play_url = None
        if resolved_item:
            urls = extract_play_urls(resolved_item)
            if urls:
                play_url = urls[0]

        return KugouResolvedTrack(
            search_response=search_response,
            search_item=dict(search_item),
            resolve_response=resolve_response,
            resolved_item=resolved_item,
            play_url=play_url,
        )

    def search_first_play_url(
        self,
        keyword: str,
        *,
        search_index: int = 0,
        preferred_qualities: Sequence[str] | None = None,
        search_options: KugouWebSearchOptions | None = None,
        resolve_options: KugouPrivUrlOptions | None = None,
        search_timeout: float | None = None,
        resolve_timeout: float | None = None,
        search_headers: Mapping[str, str] | None = None,
        resolve_headers: Mapping[str, str] | None = None,
        **search_overrides: Any,
    ) -> str | None:
        resolved = self.search_and_resolve_first(
            keyword,
            search_index=search_index,
            preferred_qualities=preferred_qualities,
            search_options=search_options,
            resolve_options=resolve_options,
            search_timeout=search_timeout,
            resolve_timeout=resolve_timeout,
            search_headers=search_headers,
            resolve_headers=resolve_headers,
            **search_overrides,
        )
        return resolved.play_url

    def search_and_resolve_first_all_pages(
        self,
        keyword: str,
        *,
        search_index: int = 0,
        preferred_qualities: Sequence[str] | None = None,
        search_options: KugouWebSearchOptions | None = None,
        resolve_options: KugouPrivUrlOptions | None = None,
        search_timeout: float | None = None,
        resolve_timeout: float | None = None,
        search_headers: Mapping[str, str] | None = None,
        resolve_headers: Mapping[str, str] | None = None,
        **search_overrides: Any,
    ) -> list[KugouResolvedTrack]:
        search_responses = self.search_all_pages(
            keyword,
            options=search_options,
            timeout=search_timeout,
            headers=search_headers,
            **search_overrides,
        )
        resolved_tracks: list[KugouResolvedTrack] = []

        for search_response in search_responses:
            if search_index < 0 or search_index >= len(search_response.items):
                raise IndexError(
                    f"search_index={search_index} is out of range for {len(search_response.items)} search results"
                )

            search_item = search_response.items[search_index]
            resolve_response = self.resolve_from_search_item(
                search_item,
                options=resolve_options,
                timeout=resolve_timeout,
                headers=resolve_headers,
            )
            resolved_item = resolve_response.choose_item(preferred_qualities=preferred_qualities)
            play_url = None
            if resolved_item:
                urls = extract_play_urls(resolved_item)
                if urls:
                    play_url = urls[0]

            resolved_tracks.append(
                KugouResolvedTrack(
                    search_response=search_response,
                    search_item=dict(search_item),
                    resolve_response=resolve_response,
                    resolved_item=resolved_item,
                    play_url=play_url,
                )
            )

        return resolved_tracks


__all__ = [
    "H5_SIGN_SECRET",
    "JSONP_PATTERN",
    "KugouApiError",
    "KugouSearchClient",
    "PRIV_URL_API_URL",
    "SEARCH_API_URL",
    "TRACKER_KEY_SEED",
    "WEB_SEARCH_API_URL",
    "WEB_SEARCH_RETRY_API_URL",
    "parse_json_or_jsonp",
]
