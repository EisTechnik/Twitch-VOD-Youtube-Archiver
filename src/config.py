from argparse import ArgumentParser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Union

from dotenv import load_dotenv

from utilities import do_log, hhmmss_to_seconds, json_load_eval

DATA_PATH = Path("data")
DATA_PATH.mkdir(parents=True, exist_ok=True)  # Create data folder if not exists

COOKIES_PATH = Path("cookies")
COOKIES_PATH.mkdir(parents=True, exist_ok=True)  # Create cookies folder if not exists

COMMANDS_FILE_NAME = "_commands.json"
TITLES_FILE_NAME = "_titles.txt"
UPLOAD_FOLDER_NAME = "upload"
DEFAULT_ENV_KEY_TWITCH_CLIENT_ID = "TWITCH_CLIENT_ID"
DEFAULT_ENV_KEY_TWITCH_CLIENT_SECRET = "TWITCH_CLIENT_SECRET"  # nosec B105
REQUESTS_DEFAULT_TIMEOUT = 10  # Default timeout for requests


@dataclass
class ScrapeConfig:
    """An object containing scrape-specific config data."""

    before_time: Union[float, None] = field(default=None)
    after_time: Union[float, None] = field(default=None)
    comment_titles: bool = field(default=True)


@dataclass
class DownloadConfig:
    """An object containing download-specific config data."""

    do_download: bool = field(default=True)
    download_commandline: str = field(
        default='yt-dlp {cookies_arg} --fixup never --retries "infinite" --file-access-retries "infinite" --fragment-retries "infinite" --concurrent-fragments 5 -o "{file_name}.%(ext)s" {vod_url}'  # noqa: E501
    )
    fixup_commandline: str = field(
        default='ffmpeg -y -hwaccel cuda -i "file:{file_name}.mp4" -map 0 -dn -ignore_unknown -c copy -f mp4 -bsf:a aac_adtstoasc -movflags faststart "file:{temp_file_name}.mp4"'  # noqa: E501
    )
    split_commandline: str = field(
        default='ffmpeg -hwaccel cuda -i "file:{input_file_name}.mp4" -map 0 -c copy -f segment -segment_time {segment_time} -reset_timestamps 1 "{output_file_name}_%03d.mp4"'  # noqa: E501
    )


@dataclass
class EnvKeys:
    """An object containing the NAME (not value) of keys to use from the .env file for a specific Twitch streamer."""

    twitch_client: str = field(default=DEFAULT_ENV_KEY_TWITCH_CLIENT_ID)
    twitch_client_secret: str = field(default=DEFAULT_ENV_KEY_TWITCH_CLIENT_SECRET)
    twitch_oauth: str = field(default="")


@dataclass
class Config:
    """An object containing all config data for a specific Twitch streamer."""

    recording_base_path: Path
    recording_path: Path
    twitch_channel_name: str
    scrape_cfg: ScrapeConfig
    download_cfg: DownloadConfig
    env_keys: EnvKeys
    divide_time: str = field(default="11:59:57")
    divide_time_seconds: int = field(default=43197)
    order_before_upload: bool = field(default=False)
    cookies_file_name: str = field(default="")


class ConfigManager:
    def __init__(self):
        load_dotenv(".env", verbose=True)
        self.configs: List[Config] = []
        self.load_config()

    def load_config(self):
        parser = ArgumentParser(description="Program arguments.")
        parser.add_argument(
            "--config", help="Filepath for the config JSON file", default="config.json"
        )
        args = parser.parse_args()
        try:
            with open(args.config, "r", encoding="utf-8") as config_file:
                loaded_configs = json_load_eval(config_file)
        except FileNotFoundError:
            raise FileNotFoundError(f"'{args.config}' not found.")

        for index, loaded_config in enumerate(loaded_configs):
            do_log(f"Loading config {index+1}/{len(loaded_configs)}")
            dataclass_constructor = {}
            for config_key in loaded_config:
                loaded_val = loaded_config[config_key]
                do_log(
                    f"Loaded config setting \n'{config_key}' ({type(loaded_val).__name__})\n{loaded_val}"
                )
            # Recording Base Path
            try:
                dataclass_constructor["recording_base_path"] = Path(
                    loaded_config.get("recording_path")
                )
            except Exception:
                do_log(
                    "[Config] Could not load path under 'recordings_path' config option. Exiting."
                )
                continue

            # Recording Path
            dataclass_constructor["twitch_channel_name"] = loaded_config.get(
                "twitch_channel_name"
            )
            if not dataclass_constructor["twitch_channel_name"]:
                do_log("[Channel name not specified, skipping]")
                continue

            dataclass_constructor["recording_path"] = Path(
                dataclass_constructor["recording_base_path"],
                dataclass_constructor["twitch_channel_name"],
            )
            dataclass_constructor["recording_path"].mkdir(
                parents=True, exist_ok=True
            )  # Create if not exists

            # Divide time
            divide_time = loaded_config.get("divide_time")
            if divide_time is not None:
                dataclass_constructor["divide_time_seconds"] = hhmmss_to_seconds(
                    divide_time
                )
                dataclass_constructor["divide_time"] = divide_time

            # Order before upload
            # This will turn ["000_000", "000_001", "001_000"] to ["000", "001", "002"]
            # Useful for human readibility, will prevent youtube uploads of "[xyz #2] [Part 1]" style
            # TODO: Handle subathon edge case, order_before_upload_if_split?
            order_before_upload = loaded_config.get("order_before_upload")
            if order_before_upload is not None:
                dataclass_constructor["order_before_upload"] = order_before_upload

            scrape_config = loaded_config.get("scrape_cfg", {})
            # Before/after time
            before_time = scrape_config.get("before_time")
            if before_time is not None:
                parsed_before_timestamp = datetime.strptime(
                    before_time, "%Y-%m-%d %H:%M:%S"
                ).timestamp()
                scrape_config["before_time"] = parsed_before_timestamp

            after_time = scrape_config.get("after_time")
            if after_time is not None:
                parsed_after_timestamp = datetime.strptime(
                    after_time, "%Y-%m-%d %H:%M:%S"
                ).timestamp()
                scrape_config["after_time"] = parsed_after_timestamp

            download_config = loaded_config.get("download_cfg", {})
            env_keys = loaded_config.get("env_keys", {})
            # Dataclass Assembly
            dataclass_constructor["scrape_cfg"] = ScrapeConfig(**scrape_config)
            dataclass_constructor["download_cfg"] = DownloadConfig(**download_config)
            dataclass_constructor["env_keys"] = EnvKeys(**env_keys)
            config_dataclass = Config(**dataclass_constructor)
            self.configs.append(config_dataclass)
