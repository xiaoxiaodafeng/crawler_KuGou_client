import hashlib
import json
import time

import requests


URL = "https://gateway.kugou.com/tracker/v6/priv_url"

# Use a public track here so the request can succeed without a login token.
# Replace HASH / MID / DFID with your own values if you already have them.
APPID = "1005"
CLIENTVER = "20489"
MID = "a85ff95792620647a6fe8f22e7c0ebc6"
DFID = "25uzzS4JG4la2uWMSN2kX8QG"
HASH = "45f763d7beb1fd000af890eb6c70b9a2"
USERID = "0"
TOKEN = ""
UUID = "-"

SIGN_SECRET = "OIlwieks28dk2k092lksi2UIkp"
TRACKER_KEY_SEED = "185672dd44712f60bb1736df5a377e82"


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def build_signature(params: dict, body: dict) -> str:
    # The server expects the exact JSON string form used in the signature.
    body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    params_string = "".join(f"{k}={params[k]}" for k in sorted(params))
    return md5_hex(f"{SIGN_SECRET}{params_string}{body_json}{SIGN_SECRET}")


def main() -> None:
    clienttime = str(int(time.time()))
    clienttime_ms = int(time.time() * 1000)

    params = {
        "appid": APPID,
        "clienttime": clienttime,
        "clientver": CLIENTVER,
        "dfid": DFID,
        "mid": MID,
        "token": TOKEN,
        "userid": USERID,
        "uuid": UUID,
    }

    body = {
        "area_code": "1",
        "behavior": "play",
        "qualities": [
            "128",
            "320",
            "flac",
            "high",
            "multitrack",
            "viper_atmos",
            "viper_tape",
            "viper_clear",
        ],
        "resource": {
            "collect_list_id": "3",
            "collect_time": clienttime_ms,
            "hash": HASH,
            "id": 0,
            "page_id": 1,
            "type": "audio",
        },
        "token": TOKEN,
        "tracker_param": {
            "all_m": 1,
            "auth": "",
            "is_free_part": 0,
            "key": md5_hex(
                f"{HASH}{TRACKER_KEY_SEED}{APPID}{MID}{USERID}"
            ),
            "module_id": 0,
            "need_climax": 1,
            "need_xcdn": 1,
            "open_time": "",
            "pid": "411",
            "pidversion": "3001",
            "priv_vip_type": "6",
            "viptoken": "",
        },
        "userid": USERID,
        "vip": 0,
    }

    params["signature"] = build_signature(params, body)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi",
        "dfid": DFID,
        "clienttime": clienttime,
        "mid": MID,
        "kg-rc": "1",
        "kg-thash": "5d816a0",
        "kg-rec": "1",
        "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
    }

    resp = requests.post(
        URL,
        params=params,
        data=json.dumps(body, separators=(",", ":"), ensure_ascii=False),
        headers=headers,
        timeout=15,
    )

    print("status:", resp.status_code)
    print("body:", resp.text)


if __name__ == "__main__":
    main()
