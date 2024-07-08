import json
from datetime import datetime
from math import ceil
from os import getenv
from os.path import exists
from pathlib import Path
from traceback import format_exc
from typing import Dict, List

import requests

from config import (
    DATA_PATH,
    REQUESTS_DEFAULT_TIMEOUT,
    TITLES_FILE_NAME,
    Config,
    EnvKeys,
    ScrapeConfig,
)
from utilities import (
    VODStatus,
    do_log,
    duration_str_to_seconds,
    log_error,
    stream_time_to_timestamp,
)


def get_access_token(client_id: str, client_secret: str) -> str:
    """Gets an API token from Twitch and returns it in 'Bearer' format (`Bearer s0MeT0k3nV4luE`)"""

    secret_key_url = "https://id.twitch.tv/oauth2/token"  # nosec

    access_token_response = requests.post(
        secret_key_url,
        params={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=REQUESTS_DEFAULT_TIMEOUT,
    )

    if not access_token_response.ok:
        raise ValueError(
            f"Bad response code for access_token:\n{access_token_response.status_code}\n{access_token_response.text}"
        )

    access_token_data = access_token_response.json()
    auth_string = f"Bearer {access_token_data['access_token']}"
    return auth_string


def get_user_id_from_name(
    client_id: str, auth_string: str, twitch_channel_name: str
) -> str:
    """Returns an ID that can be used with the Twitch API, based on the channel's username (`twitch.tv/theusername`)"""

    user_id_url = "https://api.twitch.tv/helix/users"

    user_id_response = requests.get(
        user_id_url,
        params={"login": twitch_channel_name.lower()},
        headers={
            "Client-ID": client_id,
            "Authorization": auth_string,
        },
        timeout=REQUESTS_DEFAULT_TIMEOUT,
    )
    if not user_id_response.ok:
        raise ValueError(
            f"Bad response code for user_id:\n{user_id_response.status_code}\n{user_id_response.text}"
        )

    user_id = user_id_response.json().get("data", [None])[0].get("id")
    if not user_id:
        raise ValueError(f"User ID is not valid ({user_id})")

    return user_id


def get_active_streams(client_id: str, auth_string: str, user_id: str) -> List:
    """Returns a list of "stream" objects representing currently active live streams. Empty if not live."""

    get_streams_url = "https://api.twitch.tv/helix/streams"

    streams_response = requests.get(
        get_streams_url,
        params={"user_id": user_id},
        headers={
            "Client-ID": client_id,
            "Authorization": auth_string,
        },
        timeout=REQUESTS_DEFAULT_TIMEOUT,
    )

    if not streams_response.ok:
        raise ValueError(
            f"Bad response code for streams_response:\n{streams_response.status_code}\n{streams_response.text}"
        )

    streams_list = streams_response.json().get("data", [])
    return streams_list


def get_vod_list(twitch_channel_name: str, env_keys: EnvKeys, cfg: ScrapeConfig):
    client_id = getenv(env_keys.twitch_client)
    if not client_id:
        log_error(f"'{env_keys.twitch_client}' not found in .env file!")
        return

    client_secret = getenv(env_keys.twitch_client_secret)
    if not client_secret:
        log_error(f"'{env_keys.twitch_client_secret}' not found in .env file!")
        return

    # Get the required auth token to put in our header
    auth_string = get_access_token(client_id, client_secret)

    # Get the user ID based on the channel name
    user_id = get_user_id_from_name(client_id, auth_string, twitch_channel_name.lower())

    # Get list of currently active streams, to filter out live VODs
    streams_list = get_active_streams(client_id, auth_string, user_id)

    active_stream_ids = [stream["id"] for stream in streams_list]

    print(
        {
            "Client-ID": client_id,
            "Authorization": auth_string,
        }
    )
    # Decide if we can use a provided oauth for getting videos (Useful for private VODs)
    if env_keys.twitch_oauth:
        _token = getenv(env_keys.twitch_oauth, None)
        if not _token:
            raise ValueError(f"'{env_keys.twitch_oauth}' not found in .env file")

        _token = _token.replace("oauth:", "")  # Strip if prefix included
        _auth_string = f"OAuth {_token}"
        _client_oauth_validate = "https://id.twitch.tv/oauth2/validate"
        _client_oauth_response = requests.get(
            _client_oauth_validate,
            headers={"Authorization": _auth_string},
            timeout=REQUESTS_DEFAULT_TIMEOUT,
        )

        if not _client_oauth_response.ok:
            raise ValueError(
                f"Bad response code for client_oauth:\n{_client_oauth_response.status_code}"
                f"\n{_client_oauth_response.text}"
            )

        _response_data = _client_oauth_response.json()

        video_client_id = str(_response_data.get("client_id"))
        video_auth_string = f"Bearer {_token}"
    else:
        # Use default app auth
        video_client_id = client_id
        video_auth_string = auth_string

    # Request video clip data
    get_videos_url = "https://api.twitch.tv/helix/videos"
    print(
        {
            "Client-ID": video_client_id,
            "Authorization": video_auth_string,
        }
    )
    videos_response = requests.get(
        get_videos_url,
        params={"user_id": user_id},
        headers={
            "Client-ID": video_client_id,
            "Authorization": video_auth_string,
        },
        timeout=REQUESTS_DEFAULT_TIMEOUT,
    )
    if not videos_response.ok:
        raise ValueError(
            f"Bad response code for videos_response:\n{videos_response.status_code}\n{videos_response.text}"
        )
    print(videos_response.json())
    video_list = videos_response.json().get("data", [])

    day_segmented_vod_list: Dict[str, List[Dict]] = {}

    for vod in video_list:
        if vod.get("type") != "archive":
            # It's a highlight or something, skip.
            continue

        start_time = vod.get("created_at", "1970-01-01T00:00:00Z")
        start_timestamp = stream_time_to_timestamp(start_time)
        start_date_str = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")

        if vod["stream_id"] in active_stream_ids:
            # If its a live VOD, skip
            do_log(
                f"Skipping VOD started at {start_date_str} ({vod['duration']}), ongoing stream."
            )
            continue

        vod["unix_timestamp"] = start_timestamp
        vod["duration_seconds"] = duration_str_to_seconds(vod["duration"])
        vod["start_date_str"] = start_date_str

        if cfg.before_time is not None and start_timestamp > cfg.before_time:
            continue  # Skip if vod is before time specified in config
        if cfg.after_time is not None and start_timestamp < cfg.after_time:
            continue  # Skip if vod is after time specified in config

        if start_date_str not in day_segmented_vod_list:
            day_segmented_vod_list[start_date_str] = []

        vods_for_this_day = day_segmented_vod_list[start_date_str]
        vods_for_this_day.append(vod)

        if len(vods_for_this_day) > 1:
            # Oldest first, newest last
            # ORDER AFFECTS PART NUMBERING, if reversed the latest part will be "part 1" and vice versa
            vods_for_this_day = sorted(
                vods_for_this_day, key=lambda vod_data: vod_data["unix_timestamp"]
            )

        day_segmented_vod_list[start_date_str] = vods_for_this_day

    return day_segmented_vod_list


def scrape_vods(cfg: Config):
    scrape_cfg = cfg.scrape_cfg

    data_file_name = f"{cfg.twitch_channel_name}.json"
    data_file_path = Path(DATA_PATH, data_file_name)

    new_vods_data: Dict[str, Dict] = {}
    old_vods_data: Dict[str, Dict] = {}

    if exists(data_file_path):
        with open(data_file_path, "r") as json_file:
            old_vods_data = json.load(json_file)

    do_log(f'[Scraping VODs for "{cfg.twitch_channel_name}" channel]')
    try:
        vod_list = get_vod_list(cfg.twitch_channel_name, cfg.env_keys, scrape_cfg)
    except Exception:
        print(format_exc())
        print(f"ERROR IN PROCESSING CHANNEL '{cfg.twitch_channel_name}'")
        return

    for vod_date in vod_list:
        vods_on_date = vod_list[vod_date]
        for index, vod in enumerate(vods_on_date):
            vod_id = vod["id"]
            old_data = old_vods_data.get(vod_id)
            if old_data is not None:
                # Use old data, do not overwrite
                new_vods_data[vod_id] = old_data
                continue

            vod_sub_index = f"{index:03d}"  # If multiple in a day, 000, 001, etc.
            file_name = f"{vod['start_date_str']}_{vod_sub_index}"

            vod_duration = duration_str_to_seconds(vod["duration"])
            if vod_duration <= cfg.divide_time_seconds:
                expected_splits = []
            else:
                split_amount = ceil(vod_duration / cfg.divide_time_seconds)
                expected_splits = [
                    {
                        "name": f"{file_name}_{split:03}",
                        "duration": (
                            cfg.divide_time_seconds
                            if split != split_amount - 1
                            else (vod_duration % cfg.divide_time_seconds)
                        ),
                    }
                    for split in range(split_amount)
                ]

            new_vods_data[vod_id] = {
                "original_title": vod["title"],
                "url": vod["url"],
                "unix_timestamp": vod["unix_timestamp"],
                "date_str": vod["start_date_str"],
                "file_name": f"{file_name}",
                "status": VODStatus.NOT_DOWNLOADED,
                "duration_str": vod["duration"],
                "duration": vod_duration,
                "expected_splits": expected_splits,
            }

    # Cleanout old, uploaded data
    # FIXME: We never set status to uploaded because we dont auto-upload to YT or even check public videos.
    for vod_id, old_data in old_vods_data.items():
        if vod_id not in new_vods_data and old_data.get("status") == VODStatus.UPLOADED:
            do_log(f"Cleaning old VOD '{old_data['file_name']}' from datafile")
            continue
        new_vods_data[vod_id] = old_data

    # Write datafile
    with open(Path(DATA_PATH, data_file_name), "w") as json_file:
        json.dump(new_vods_data, json_file, indent=2)

    title_lines = []

    for vod_id, vod in new_vods_data.items():
        if vod["status"] == VODStatus.UPLOADED:
            continue

        file_name = vod["file_name"]

        if scrape_cfg.comment_titles:
            # Youtube doesnt allow angled brackets, replace it with similar-looking characters
            title_comment = vod["original_title"].replace("<", "＜").replace(">", "＞")
            title_lines.append(f"{title_comment}\n{file_name}")

    if title_lines:
        with open(
            Path(cfg.recording_path, TITLES_FILE_NAME), "w", encoding="utf-8"
        ) as titles_file:
            titles_file.write("\n\n".join(title_lines))
