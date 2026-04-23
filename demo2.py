import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import requests

from kugou_client import (
    H5_SIGN_SECRET,
    PRIV_URL_API_URL,
    SEARCH_API_URL,
    WEB_SEARCH_API_URL,
    WEB_SEARCH_RETRY_API_URL,
    KugouApiError,
    KugouSearchClient,
    parse_json_or_jsonp,
)
from kugou_models import (
    DEFAULT_JSONP_CALLBACK,
    DEFAULT_PRIV_URL_QUALITIES,
    KugouPrivUrlOptions,
    KugouResolveResponse,
    KugouResolvedTrack,
    KugouSearchResponse,
    KugouWebSearchOptions,
    as_string_dict,
    choose_resolve_item,
    extract_play_urls,
    extract_resolve_items,
    extract_song_hash,
    extract_song_items,
    simplify_resolve_rows,
    simplify_song_rows,
)


DEFAULT_KEYWORD = "\u9648\u5955\u8fc5"
DEFAULT_DOWNLOAD_DIR = "music_mp3"
DEFAULT_METADATA_FILENAME = "metadata.json"
DEFAULT_LYRICS_FILENAME = "lyrics.txt"


def sign_kugou_web_search_params(params: Mapping[str, Any]) -> dict[str, str]:
    return KugouSearchClient.sign_web_params(params)


def build_web_search_params(
    keyword: str,
    *,
    page: int = 1,
    pagesize: int = 30,
    bitrate: int = 0,
    isfuzzy: int = 0,
    inputtype: int = 0,
    platform: str = "WebFilter",
    userid: str | int = "0",
    iscorrection: int = 1,
    privilege_filter: int = 0,
    search_filter: int = 10,
    token: str = "",
    appid: int = 1014,
    srcappid: int = 2919,
    clientver: int = 20000,
    clienttime: int | None = None,
    mid: str | None = None,
    uuid: str | None = None,
    dfid: str = "-",
    callback: str = DEFAULT_JSONP_CALLBACK,
) -> dict[str, str]:
    options = KugouWebSearchOptions(
        page=page,
        pagesize=pagesize,
        bitrate=bitrate,
        isfuzzy=isfuzzy,
        inputtype=inputtype,
        platform=platform,
        userid=userid,
        iscorrection=iscorrection,
        privilege_filter=privilege_filter,
        search_filter=search_filter,
        token=token,
        appid=appid,
        srcappid=srcappid,
        clientver=clientver,
        clienttime=clienttime,
        mid=mid,
        uuid=uuid,
        dfid=dfid,
        callback=callback,
    )
    return KugouSearchClient().build_search_params(keyword, options=options)


def build_keyword_search_request_url(
    keyword: str,
    *,
    base_url: str = WEB_SEARCH_API_URL,
    **kwargs: Any,
) -> str:
    client = KugouSearchClient()
    return client.build_search_url(keyword, base_url=base_url, **kwargs)


def build_signed_search_url(params: Mapping[str, Any], base_url: str = SEARCH_API_URL) -> str:
    return KugouSearchClient.build_signed_client_url(params, base_url=base_url)


def search_song_by_keyword(
    keyword: str,
    *,
    timeout: float = 15.0,
    retries: int = 2,
    retry_delay: float = 1.0,
    session: requests.Session | None = None,
    headers: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        web_timeout=timeout,
        web_headers=headers,
    )
    return client.search_payload(keyword, **kwargs)


def search_song_with_signed_url(
    signed_url: str,
    *,
    timeout: float = 20.0,
    retries: int = 2,
    retry_delay: float = 1.0,
    allow_tracker_fallback: bool = True,
    session: requests.Session | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        client_timeout=timeout,
        client_headers=headers,
    )
    return client.replay_signed_payload(
        signed_url,
        allow_tracker_fallback=allow_tracker_fallback,
    )


def resolve_song_by_hash(
    song_hash: str,
    *,
    timeout: float = 15.0,
    retries: int = 2,
    retry_delay: float = 1.0,
    session: requests.Session | None = None,
    headers: Mapping[str, str] | None = None,
    options: KugouPrivUrlOptions | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        resolve_timeout=timeout,
        resolve_headers=headers,
    )
    return client.resolve_song_payload(song_hash, options=options, **kwargs)


def search_and_resolve_first_song(
    keyword: str,
    *,
    search_index: int = 0,
    preferred_qualities: tuple[str, ...] | None = None,
    session: requests.Session | None = None,
    retries: int = 2,
    retry_delay: float = 1.0,
    search_timeout: float = 15.0,
    resolve_timeout: float = 15.0,
    search_options: KugouWebSearchOptions | None = None,
    resolve_options: KugouPrivUrlOptions | None = None,
    **search_overrides: Any,
) -> KugouResolvedTrack:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        web_timeout=search_timeout,
        resolve_timeout=resolve_timeout,
    )
    return client.search_and_resolve_first(
        keyword,
        search_index=search_index,
        preferred_qualities=preferred_qualities,
        search_options=search_options,
        resolve_options=resolve_options,
        **search_overrides,
    )


def search_all_pages_by_keyword(
    keyword: str,
    *,
    timeout: float = 15.0,
    retries: int = 2,
    retry_delay: float = 1.0,
    session: requests.Session | None = None,
    headers: Mapping[str, str] | None = None,
    search_options: KugouWebSearchOptions | None = None,
    **kwargs: Any,
) -> list[KugouSearchResponse]:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        web_timeout=timeout,
        web_headers=headers,
    )
    return client.search_all_pages(keyword, options=search_options, **kwargs)


def search_and_resolve_first_song_all_pages(
    keyword: str,
    *,
    search_index: int = 0,
    preferred_qualities: tuple[str, ...] | None = None,
    session: requests.Session | None = None,
    retries: int = 2,
    retry_delay: float = 1.0,
    search_timeout: float = 15.0,
    resolve_timeout: float = 15.0,
    search_options: KugouWebSearchOptions | None = None,
    resolve_options: KugouPrivUrlOptions | None = None,
    **search_overrides: Any,
) -> list[KugouResolvedTrack]:
    client = KugouSearchClient(
        session=session,
        retries=retries,
        retry_delay=retry_delay,
        web_timeout=search_timeout,
        resolve_timeout=resolve_timeout,
    )
    return client.search_and_resolve_first_all_pages(
        keyword,
        search_index=search_index,
        preferred_qualities=preferred_qualities,
        search_options=search_options,
        resolve_options=resolve_options,
        **search_overrides,
    )


def _print_search_result(result: KugouSearchResponse) -> None:
    print("status:", result.status)
    print("error_code:", result.error_code)
    print("message:", result.message)
    if result.total is not None:
        print("total:", result.total)
    print(
        json.dumps(
            {
                "result_count": len(result.items),
                "songs": result.simplify()[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _print_resolve_result(result: KugouResolveResponse) -> None:
    print("status:", result.status)
    print("error_code:", result.error_code)
    print("message:", result.message)
    print("best_url:", result.best_url())
    print(
        json.dumps(
            {
                "result_count": len(result.items),
                "qualities": result.simplify()[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _print_resolved_track(result: KugouResolvedTrack) -> None:
    print("search_status:", result.search_response.status)
    print("resolve_status:", result.resolve_response.status)
    print("selected_hash:", result.hash)
    print("selected_quality:", result.quality)
    print("play_url:", result.play_url)
    print(
        json.dumps(
            {
                "selected_song": result.simplify(),
                "search_preview": result.search_response.simplify()[:5],
                "resolve_preview": result.resolve_response.simplify()[:5],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _print_resolved_track_pages(results: list[KugouResolvedTrack], *, start_page: int) -> None:
    pages = []
    for offset, result in enumerate(results):
        pages.append(
            {
                "page": start_page + offset,
                "name": result.name,
                "singername": result.singername,
                "hash": result.hash,
                "quality": result.quality,
                "has_audio": bool(result.play_url),
                "play_url": result.play_url,
            }
        )

    print("page_count:", len(results))
    print(
        json.dumps(
            {
                "pages": pages,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _sanitize_filename_component(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", text.strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "kugou"


def _build_default_export_path(keyword: str) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_keyword = _sanitize_filename_component(keyword)
    return Path(f"kugou_export_{safe_keyword}_{timestamp}.json")


def _pick_item_id(search_row: Mapping[str, Any], *, page_no: int, item_index: int) -> str:
    raw_id = search_row.get("hash") or f"page{page_no}_{item_index}"
    return _sanitize_filename_component(str(raw_id))


def _build_lyric_keyword(search_row: Mapping[str, Any]) -> str:
    singer = str(search_row.get("singername") or "").strip()
    name = str(search_row.get("name") or "").strip()
    if singer and name:
        return f"{singer} - {name}"
    return name or singer


def _download_audio_file(
    client: KugouSearchClient,
    url: str,
    target_path: Path,
    *,
    timeout: float = 60.0,
) -> None:
    temp_path = target_path.with_suffix(target_path.suffix + ".part")
    response = client._request(
        "GET",
        url,
        headers={"User-Agent": client.client_headers.get("User-Agent", "Mozilla/5.0")},
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()
    with temp_path.open("wb") as file_obj:
        for chunk in response.iter_content(chunk_size=262_144):
            if chunk:
                file_obj.write(chunk)
    temp_path.replace(target_path)


def _collect_keyword_all_data(
    client: KugouSearchClient,
    keyword: str,
    *,
    search_options: KugouWebSearchOptions,
    resolve_options: KugouPrivUrlOptions | None = None,
) -> dict[str, Any]:
    search_responses = client.search_all_pages(keyword, options=search_options)
    total = search_responses[0].total if search_responses else 0
    page_count = len(search_responses)
    items: list[dict[str, Any]] = []
    audio_count = 0
    no_audio_count = 0

    for page_offset, search_response in enumerate(search_responses):
        page_no = search_options.page + page_offset
        print(f"processing page {page_no}/{search_options.page + page_count - 1} ...")
        for item_index, search_item in enumerate(search_response.items, start=1):
            song_hash = extract_song_hash(search_item)
            resolve_status = None
            resolve_error = None
            best_row: dict[str, Any] | None = None
            play_urls: list[str] = []
            play_url = None
            search_row = {
                "name": search_item.get("name") or search_item.get("SongName"),
                "singername": search_item.get("singername") or search_item.get("SingerName"),
                "albumname": search_item.get("albumname") or search_item.get("AlbumName"),
                "hash": song_hash,
                "album_audio_id": search_item.get("album_audio_id") or search_item.get("EMixSongID"),
                "duration": search_item.get("duration") or search_item.get("Duration"),
            }

            if song_hash:
                try:
                    resolve_response = client.resolve_song(song_hash, options=resolve_options)
                    resolve_status = resolve_response.status
                    best_row = next(
                        (row for row in resolve_response.simplify(include_related=True) if row.get("url")),
                        None,
                    )
                    play_urls = resolve_response.best_urls()
                    play_url = play_urls[0] if play_urls else None
                except Exception as exc:
                    resolve_error = str(exc)

            if play_url:
                audio_count += 1
            else:
                no_audio_count += 1

            items.append(
                {
                    "page": page_no,
                    "index_in_page": item_index,
                    **search_row,
                    "has_audio": bool(play_url),
                    "play_url": play_url,
                    "backup_urls": play_urls[1:],
                    "quality": best_row.get("quality") if best_row else None,
                    "bitrate": best_row.get("bitrate") if best_row else None,
                    "extname": best_row.get("extname") if best_row else None,
                    "tracker_type": best_row.get("tracker_type") if best_row else None,
                    "tracker_status": best_row.get("tracker_status") if best_row else None,
                    "resolve_status": resolve_status,
                    "resolve_error": resolve_error,
                }
            )

    return {
        "keyword": keyword,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "page_start": search_options.page,
        "page_count": page_count,
        "pagesize": search_options.pagesize,
        "total": total,
        "audio_count": audio_count,
        "no_audio_count": no_audio_count,
        "items": items,
    }


def _export_keyword_all_data(
    client: KugouSearchClient,
    keyword: str,
    *,
    search_options: KugouWebSearchOptions,
    resolve_options: KugouPrivUrlOptions | None = None,
    output_path: str = "",
) -> Path:
    export_data = _collect_keyword_all_data(
        client,
        keyword,
        search_options=search_options,
        resolve_options=resolve_options,
    )
    target_path = Path(output_path) if output_path else _build_default_export_path(keyword)
    target_path.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def _export_keyword_assets(
    client: KugouSearchClient,
    keyword: str,
    *,
    search_options: KugouWebSearchOptions,
    resolve_options: KugouPrivUrlOptions | None = None,
    output_dir: str = DEFAULT_DOWNLOAD_DIR,
    manifest_path: str = "",
    max_items: int | None = None,
) -> Path:
    root_dir = Path(output_dir or DEFAULT_DOWNLOAD_DIR)
    root_dir.mkdir(parents=True, exist_ok=True)

    search_responses = client.search_all_pages(keyword, options=search_options)
    total = search_responses[0].total if search_responses else 0
    page_count = len(search_responses)
    items: list[dict[str, Any]] = []
    audio_count = 0
    downloaded_count = 0
    failed_count = 0
    lyric_count = 0
    lyric_saved_count = 0
    lyric_failed_count = 0

    for page_offset, search_response in enumerate(search_responses):
        if max_items is not None and len(items) >= max_items:
            break
        page_no = search_options.page + page_offset
        print(f"processing page {page_no}/{search_options.page + page_count - 1} ...")
        for item_index, search_item in enumerate(search_response.items, start=1):
            if max_items is not None and len(items) >= max_items:
                break
            song_hash = extract_song_hash(search_item)
            resolve_status = None
            resolve_error = None
            best_row: dict[str, Any] | None = None
            play_urls: list[str] = []
            play_url = None
            search_row = {
                "name": search_item.get("name") or search_item.get("SongName"),
                "singername": search_item.get("singername") or search_item.get("SingerName"),
                "albumname": search_item.get("albumname") or search_item.get("AlbumName"),
                "hash": song_hash,
                "album_audio_id": search_item.get("album_audio_id") or search_item.get("EMixSongID"),
                "duration": search_item.get("duration") or search_item.get("Duration"),
            }

            if song_hash:
                try:
                    resolve_response = client.resolve_song(song_hash, options=resolve_options)
                    resolve_status = resolve_response.status
                    best_row = next(
                        (row for row in resolve_response.simplify(include_related=True) if row.get("url")),
                        None,
                    )
                    play_urls = resolve_response.best_urls()
                    play_url = play_urls[0] if play_urls else None
                except Exception as exc:
                    resolve_error = str(exc)

            item_id = _pick_item_id(search_row, page_no=page_no, item_index=item_index)
            item_dir = root_dir / item_id
            item_dir.mkdir(parents=True, exist_ok=True)
            mp3_path = item_dir / f"{item_id}.mp3"
            json_path = item_dir / DEFAULT_METADATA_FILENAME
            lyric_path = item_dir / DEFAULT_LYRICS_FILENAME
            download_status = "no_audio"
            download_error = None
            lyric_status = "not_requested"
            lyric_error = None
            lyric_text = None
            lyric_source = None
            lyric_format = None

            if play_url:
                audio_count += 1
                if mp3_path.exists():
                    download_status = "exists"
                else:
                    try:
                        _download_audio_file(client, play_url, mp3_path)
                        download_status = "downloaded"
                        downloaded_count += 1
                    except Exception as exc:
                        download_status = "download_failed"
                        download_error = str(exc)
                        failed_count += 1
            else:
                failed_count += 1

            if song_hash:
                try:
                    lyric_result = client.fetch_lyric(
                        song_hash,
                        keyword=_build_lyric_keyword(search_row),
                        duration_ms=search_row.get("duration"),
                    )
                    lyric_text = lyric_result.get("text")
                    lyric_source = lyric_result.get("source")
                    lyric_format = lyric_result.get("format")
                    if lyric_text:
                        lyric_count += 1
                        if lyric_path.exists():
                            lyric_status = "exists"
                        else:
                            lyric_path.write_text(str(lyric_text), encoding="utf-8")
                            lyric_status = "saved"
                            lyric_saved_count += 1
                    else:
                        lyric_status = "not_found"
                except Exception as exc:
                    lyric_status = "fetch_failed"
                    lyric_error = str(exc)
                    lyric_failed_count += 1

            metadata = {
                "id": item_id,
                "page": page_no,
                "index_in_page": item_index,
                **search_row,
                "has_audio": bool(play_url),
                "play_url": play_url,
                "backup_urls": play_urls[1:],
                "quality": best_row.get("quality") if best_row else None,
                "bitrate": best_row.get("bitrate") if best_row else None,
                "extname": best_row.get("extname") if best_row else None,
                "tracker_type": best_row.get("tracker_type") if best_row else None,
                "tracker_status": best_row.get("tracker_status") if best_row else None,
                "resolve_status": resolve_status,
                "resolve_error": resolve_error,
                "download_status": download_status,
                "download_error": download_error,
                "lyric_status": lyric_status,
                "lyric_error": lyric_error,
                "lyric_source": lyric_source,
                "lyric_format": lyric_format,
                "relative_dir": str(item_dir.relative_to(root_dir)),
                "relative_mp3_path": str(mp3_path.relative_to(root_dir)) if play_url else None,
                "relative_txt_path": str(lyric_path.relative_to(root_dir)) if lyric_text else None,
                "relative_json_path": str(json_path.relative_to(root_dir)),
                "mp3_file": mp3_path.name if play_url else None,
                "txt_file": lyric_path.name if lyric_text else None,
                "json_file": json_path.name,
            }
            json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            items.append(metadata)

    manifest = {
        "keyword": keyword,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root_dir": str(root_dir.resolve()),
        "page_start": search_options.page,
        "page_count": page_count,
        "pagesize": search_options.pagesize,
        "requested_limit": max_items,
        "total": total,
        "audio_count": audio_count,
        "downloaded_count": downloaded_count,
        "failed_count": failed_count,
        "lyric_count": lyric_count,
        "lyric_saved_count": lyric_saved_count,
        "lyric_failed_count": lyric_failed_count,
        "items": items,
    }
    target_manifest = Path(manifest_path) if manifest_path else root_dir / "index.json"
    target_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Kugou helper. Supports keyword search, signed client replay, "
            "direct priv_url resolution, and search-then-resolve."
        )
    )
    parser.add_argument(
        "keyword",
        nargs="?",
        default=DEFAULT_KEYWORD,
        help="Keyword for web search mode.",
    )
    parser.add_argument(
        "--url",
        default="",
        help="Replay a full client-signed search URL instead of using keyword search.",
    )
    parser.add_argument(
        "--hash",
        default="",
        help="Resolve a song hash through priv_url instead of doing search.",
    )
    parser.add_argument(
        "--resolve-first",
        action="store_true",
        help="After keyword search, resolve the first search result into a playable URL.",
    )
    parser.add_argument(
        "--all-pages",
        "--all-page",
        action="store_true",
        help="Run the keyword search across all pages starting from --page.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Save the all-pages manifest JSON to this path. Default: music_mp3/index.json",
    )
    parser.add_argument(
        "--download-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory used by --all-page to save mp3 files and per-song JSON metadata.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N songs when used with --all-page.",
    )
    parser.add_argument("--page", type=int, default=1, help="Search result page number.")
    parser.add_argument("--pagesize", type=int, default=30, help="Number of results per page.")
    parser.add_argument(
        "--show-url",
        action="store_true",
        help="Print the final request URL before sending it.",
    )
    args = parser.parse_args()

    client = KugouSearchClient()

    try:
        if args.url:
            if args.show_url:
                print("request_url:", args.url)
            _print_search_result(client.replay_signed_search(args.url))
            return

        if args.hash:
            if args.show_url:
                request_url, _, _ = client.build_resolve_request(args.hash)
                print("request_url:", request_url)
            _print_resolve_result(client.resolve_song(args.hash))
            return

        options = KugouWebSearchOptions(page=args.page, pagesize=args.pagesize)
        if args.show_url:
            print("request_url:", client.build_search_url(args.keyword, options=options))

        if args.all_pages and args.resolve_first:
            _print_resolved_track_pages(
                client.search_and_resolve_first_all_pages(args.keyword, search_options=options),
                start_page=options.page,
            )
            return

        if args.all_pages:
            saved_path = _export_keyword_assets(
                client,
                args.keyword,
                search_options=options,
                output_dir=args.download_dir,
                manifest_path=args.output,
                max_items=args.limit if args.limit > 0 else None,
            )
            print("saved_manifest:", saved_path.resolve())
            print("saved_dir:", Path(args.download_dir).resolve())
            return

        if args.resolve_first:
            _print_resolved_track(client.search_and_resolve_first(args.keyword, search_options=options))
            return

        _print_search_result(client.search(args.keyword, options=options))
    except Exception as exc:
        print("request failed:", exc)
        print(
            "tip: keyword-only mode uses the public web/H5 search path. "
            "If you specifically need the native PC client /v3/search/song "
            "request, you still need a fresh client-signed URL."
        )
        sys.exit(1)


__all__ = [
    "DEFAULT_JSONP_CALLBACK",
    "DEFAULT_KEYWORD",
    "DEFAULT_PRIV_URL_QUALITIES",
    "H5_SIGN_SECRET",
    "KugouApiError",
    "KugouPrivUrlOptions",
    "KugouResolveResponse",
    "KugouResolvedTrack",
    "KugouSearchClient",
    "KugouSearchResponse",
    "KugouWebSearchOptions",
    "PRIV_URL_API_URL",
    "SEARCH_API_URL",
    "WEB_SEARCH_API_URL",
    "WEB_SEARCH_RETRY_API_URL",
    "as_string_dict",
    "build_keyword_search_request_url",
    "build_signed_search_url",
    "build_web_search_params",
    "choose_resolve_item",
    "extract_play_urls",
    "extract_resolve_items",
    "extract_song_hash",
    "extract_song_items",
    "main",
    "parse_json_or_jsonp",
    "resolve_song_by_hash",
    "search_all_pages_by_keyword",
    "search_and_resolve_first_song",
    "search_and_resolve_first_song_all_pages",
    "search_song_by_keyword",
    "search_song_with_signed_url",
    "sign_kugou_web_search_params",
    "simplify_resolve_rows",
    "simplify_song_rows",
]


if __name__ == "__main__":
    main()
