from dataclasses import dataclass
from typing import Any, Mapping, Sequence


DEFAULT_JSONP_CALLBACK = "callback123"
DEFAULT_PRIV_URL_QUALITIES = (
    "128",
    "320",
    "flac",
    "high",
    "multitrack",
    "viper_atmos",
    "viper_tape",
    "viper_clear",
)


def as_string_dict(params: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): "" if value is None else str(value) for key, value in params.items()}


def extract_song_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize search results from either web `v2` or client `v3` payloads."""
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        lists = data.get("lists")
        if isinstance(lists, list):
            return [item for item in lists if isinstance(item, dict)]
    return []


def extract_resolve_items(
    payload: Mapping[str, Any],
    *,
    include_related: bool = False,
) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []

    items: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        items.append(item)
        if not include_related:
            continue
        for related_item in item.get("relate_goods", []):
            if isinstance(related_item, dict):
                items.append(related_item)
    return items


def extract_song_hash(item: Mapping[str, Any]) -> str | None:
    value = _pick_first(item, "hash", "Hash", "FileHash")
    if value in (None, ""):
        return None
    return str(value)


def extract_play_urls(item: Mapping[str, Any]) -> list[str]:
    info = item.get("info")
    if not isinstance(info, dict):
        return []

    climax_info = info.get("climax_info")
    if isinstance(climax_info, dict):
        urls = climax_info.get("url")
        if isinstance(urls, list):
            normalized = [str(url) for url in urls if url]
            if normalized:
                return normalized

    tracker_urls = info.get("tracker_url")
    if isinstance(tracker_urls, list):
        return [str(url) for url in tracker_urls if url]

    return []


def choose_resolve_item(
    items: Sequence[Mapping[str, Any]],
    *,
    preferred_qualities: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    candidates = [dict(item) for item in items if extract_play_urls(item)]
    if not candidates:
        return None

    if preferred_qualities:
        for quality in preferred_qualities:
            for item in candidates:
                if str(item.get("quality", "")).lower() == str(quality).lower():
                    return item

    return candidates[0]


def simplify_song_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in extract_song_items(payload):
        rows.append(
            {
                "name": _pick_first(item, "name", "SongName"),
                "singername": _pick_first(item, "singername", "SingerName"),
                "albumname": _pick_first(item, "albumname", "AlbumName"),
                "hash": extract_song_hash(item),
                "album_audio_id": _pick_first(item, "album_audio_id", "EMixSongID", "MixSongID"),
                "duration": _pick_first(item, "duration", "Duration"),
            }
        )
    return rows


def simplify_resolve_rows(
    payload: Mapping[str, Any],
    *,
    include_related: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in extract_resolve_items(payload, include_related=include_related):
        urls = extract_play_urls(item)
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        rows.append(
            {
                "name": _pick_first(item, "name", "SongName"),
                "singername": _pick_first(item, "singername", "SingerName"),
                "albumname": _pick_first(item, "albumname", "AlbumName"),
                "quality": item.get("quality"),
                "hash": extract_song_hash(item),
                "bitrate": info.get("bitrate"),
                "extname": info.get("extname"),
                "tracker_type": info.get("tracker_type"),
                "tracker_status": info.get("tracker_status"),
                "url_count": len(urls),
                "url": urls[0] if urls else None,
            }
        )
    return rows


def _pick_first(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


@dataclass(slots=True)
class KugouWebSearchOptions:
    page: int = 1
    pagesize: int = 30
    bitrate: int = 0
    isfuzzy: int = 0
    inputtype: int = 0
    platform: str = "WebFilter"
    userid: str | int = "0"
    iscorrection: int = 1
    privilege_filter: int = 0
    search_filter: int = 10
    token: str = ""
    appid: int = 1014
    srcappid: int = 2919
    clientver: int = 20000
    clienttime: int | None = None
    mid: str | None = None
    uuid: str | None = None
    dfid: str = "-"
    callback: str = DEFAULT_JSONP_CALLBACK

    def build_unsigned_params(self, keyword: str, *, clienttime_ms: int) -> dict[str, str]:
        cleaned_keyword = keyword.strip()
        if not cleaned_keyword:
            raise ValueError("keyword must not be empty")

        mid_value = str(self.mid if self.mid is not None else clienttime_ms)
        uuid_value = str(self.uuid if self.uuid is not None else mid_value)

        return as_string_dict(
            {
                "appid": self.appid,
                "bitrate": self.bitrate,
                "callback": self.callback,
                "clienttime": clienttime_ms,
                "clientver": self.clientver,
                "dfid": self.dfid,
                "filter": self.search_filter,
                "inputtype": self.inputtype,
                "iscorrection": self.iscorrection,
                "isfuzzy": self.isfuzzy,
                "keyword": cleaned_keyword,
                "mid": mid_value,
                "page": self.page,
                "pagesize": self.pagesize,
                "platform": self.platform,
                "privilege_filter": self.privilege_filter,
                "srcappid": self.srcappid,
                "token": self.token,
                "userid": self.userid,
                "uuid": uuid_value,
            }
        )


@dataclass(slots=True)
class KugouPrivUrlOptions:
    appid: str | int = "1005"
    clientver: str | int = "20489"
    mid: str = "a85ff95792620647a6fe8f22e7c0ebc6"
    dfid: str = "25uzzS4JG4la2uWMSN2kX8QG"
    userid: str | int = "0"
    token: str = ""
    uuid: str = "-"
    vip: int = 0
    area_code: str = "1"
    behavior: str = "play"
    qualities: tuple[str, ...] = DEFAULT_PRIV_URL_QUALITIES
    collect_list_id: str = "3"
    page_id: int = 1
    resource_type: str = "audio"
    all_m: int = 1
    auth: str = ""
    is_free_part: int = 0
    module_id: int = 0
    need_climax: int = 1
    need_xcdn: int = 1
    open_time: str = ""
    pid: str = "411"
    pidversion: str = "3001"
    priv_vip_type: str = "6"
    viptoken: str = ""

    def normalize_hash(self, song_hash: str) -> str:
        cleaned = song_hash.strip()
        if not cleaned:
            raise ValueError("song_hash must not be empty")
        return cleaned.lower()

    def build_query_params(self, *, clienttime: int) -> dict[str, str]:
        return as_string_dict(
            {
                "appid": self.appid,
                "clienttime": clienttime,
                "clientver": self.clientver,
                "dfid": self.dfid,
                "mid": self.mid,
                "token": self.token,
                "userid": self.userid,
                "uuid": self.uuid,
            }
        )

    def build_request_body(
        self,
        song_hash: str,
        *,
        clienttime_ms: int,
        tracker_key: str,
    ) -> dict[str, Any]:
        normalized_hash = self.normalize_hash(song_hash)
        return {
            "area_code": self.area_code,
            "behavior": self.behavior,
            "qualities": list(self.qualities),
            "resource": {
                "collect_list_id": self.collect_list_id,
                "collect_time": clienttime_ms,
                "hash": normalized_hash,
                "id": 0,
                "page_id": self.page_id,
                "type": self.resource_type,
            },
            "token": str(self.token),
            "tracker_param": {
                "all_m": self.all_m,
                "auth": self.auth,
                "is_free_part": self.is_free_part,
                "key": tracker_key,
                "module_id": self.module_id,
                "need_climax": self.need_climax,
                "need_xcdn": self.need_xcdn,
                "open_time": self.open_time,
                "pid": self.pid,
                "pidversion": self.pidversion,
                "priv_vip_type": self.priv_vip_type,
                "viptoken": self.viptoken,
            },
            "userid": str(self.userid),
            "vip": self.vip,
        }

    def build_headers(self, *, clienttime: int) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi",
            "dfid": self.dfid,
            "clienttime": str(clienttime),
            "mid": self.mid,
            "kg-rc": "1",
            "kg-thash": "5d816a0",
            "kg-rec": "1",
            "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
        }


@dataclass(slots=True)
class KugouPayloadResponse:
    payload: dict[str, Any]

    @property
    def status(self) -> Any:
        return self.payload.get("status")

    @property
    def error_code(self) -> Any:
        return self.payload.get("error_code")

    @property
    def message(self) -> Any:
        return self.payload.get("message") or self.payload.get("error_msg")


@dataclass(slots=True)
class KugouSearchResponse(KugouPayloadResponse):
    @property
    def total(self) -> Any:
        data = self.payload.get("data")
        if isinstance(data, dict):
            return data.get("total")
        return None

    @property
    def items(self) -> list[dict[str, Any]]:
        return extract_song_items(self.payload)

    def simplify(self) -> list[dict[str, Any]]:
        return simplify_song_rows(self.payload)


@dataclass(slots=True)
class KugouResolveResponse(KugouPayloadResponse):
    @property
    def items(self) -> list[dict[str, Any]]:
        return extract_resolve_items(self.payload)

    @property
    def all_items(self) -> list[dict[str, Any]]:
        return extract_resolve_items(self.payload, include_related=True)

    def simplify(self, *, include_related: bool = False) -> list[dict[str, Any]]:
        return simplify_resolve_rows(self.payload, include_related=include_related)

    def choose_item(self, *, preferred_qualities: Sequence[str] | None = None) -> dict[str, Any] | None:
        return choose_resolve_item(self.all_items, preferred_qualities=preferred_qualities)

    def best_urls(self, *, preferred_qualities: Sequence[str] | None = None) -> list[str]:
        item = self.choose_item(preferred_qualities=preferred_qualities)
        if not item:
            return []
        return extract_play_urls(item)

    def best_url(self, *, preferred_qualities: Sequence[str] | None = None) -> str | None:
        urls = self.best_urls(preferred_qualities=preferred_qualities)
        if not urls:
            return None
        return urls[0]


@dataclass(slots=True)
class KugouResolvedTrack:
    search_response: KugouSearchResponse
    search_item: dict[str, Any]
    resolve_response: KugouResolveResponse
    resolved_item: dict[str, Any] | None
    play_url: str | None

    @property
    def hash(self) -> str | None:
        return extract_song_hash(self.search_item)

    @property
    def name(self) -> Any:
        return _pick_first(self.search_item, "name", "SongName")

    @property
    def singername(self) -> Any:
        return _pick_first(self.search_item, "singername", "SingerName")

    @property
    def quality(self) -> Any:
        if not self.resolved_item:
            return None
        return self.resolved_item.get("quality")

    def simplify(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "singername": self.singername,
            "hash": self.hash,
            "quality": self.quality,
            "play_url": self.play_url,
        }


__all__ = [
    "DEFAULT_JSONP_CALLBACK",
    "DEFAULT_PRIV_URL_QUALITIES",
    "KugouPayloadResponse",
    "KugouPrivUrlOptions",
    "KugouResolveResponse",
    "KugouResolvedTrack",
    "KugouSearchResponse",
    "KugouWebSearchOptions",
    "as_string_dict",
    "choose_resolve_item",
    "extract_play_urls",
    "extract_resolve_items",
    "extract_song_hash",
    "extract_song_items",
    "simplify_resolve_rows",
    "simplify_song_rows",
]
