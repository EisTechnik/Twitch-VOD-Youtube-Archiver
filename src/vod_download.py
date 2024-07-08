import json
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from os import remove, rename
from pathlib import Path
from typing import Dict, List

from config import COOKIES_PATH, DATA_PATH, UPLOAD_FOLDER_NAME, Config
from utilities import VODStatus, do_log, log_error

PART_ERROR1 = "[Errno 2] No such file or directory: '{file_name}.mp4.part-Frag"
PART_ERROR2 = (
    "[WinError 2] The system cannot find the file specified: '{file_name}.mp4.part-Frag"
)
INIT_ERROR = "ERROR: 'NoneType' object does not support item assignment"
FIXUP_FILE_NAME = "{file_name}_fixed"


@dataclass
class DownloadCommand:
    """An object containing all data for a specific download."""

    id: str
    file_name: str
    url: str


@dataclass
class FixupCommand:
    """An object containing all data for a specific fixup."""

    id: str
    file_name: str


@dataclass
class SplitCommand:
    """An object containing all data for a specific split."""

    id: str
    file_name: str
    should_split: bool


@dataclass
class OrderParentCommand:
    """An object containing all data for a specific order, originating from a VOD"""

    id: str
    file_name: str
    date_str: str
    unix_timestamp: float
    expected_splits: List[str]
    should_order: bool


@dataclass
class OrderChildCommand:
    """An object containing all data for a specific move, originating from a split mp4"""

    vod_id: str
    file_name: str
    should_order: bool


def download_vods(cfg: Config):
    vods_to_download: List[DownloadCommand] = []

    # FIXME: Cookies don't seem to do anything unfortunately.
    cookies_arg = (
        ""
        if not cfg.cookies_file_name
        else f"--cookies {Path(COOKIES_PATH, cfg.cookies_file_name)} "
    )
    download_cmd_raw = cfg.download_cfg.download_commandline.format(
        cookies_arg=cookies_arg, file_name="{file_name}", vod_url="{vod_url}"
    )

    data_file_name = f"{cfg.twitch_channel_name}.json"

    do_log(f'[Downloading VODs for "{cfg.twitch_channel_name}" channel]')

    with open(Path(DATA_PATH, data_file_name), "r") as json_file:
        data_file = json.load(json_file)

    for vod_id, vod_data in data_file.items():
        if vod_data["status"] == VODStatus.NOT_DOWNLOADED:
            vods_to_download.append(
                DownloadCommand(vod_id, vod_data["file_name"], vod_data["url"])
            )

    for index, vod in enumerate(vods_to_download):
        do_log(f"[Downloading VOD {index+1}/{len(vods_to_download)}]")

        download_cmd = download_cmd_raw.format(file_name=vod.file_name, vod_url=vod.url)
        print(download_cmd)

        completed_process = subprocess.run(  # nosec B603
            download_cmd,
            cwd=cfg.recording_path,
            stderr=subprocess.PIPE,
        )
        expected_error1 = PART_ERROR1.format(file_name=vod.file_name)
        expected_error2 = PART_ERROR2.format(file_name=vod.file_name)
        while completed_process.returncode != 0:
            print("\n")  # clear buffer
            error = (
                ""
                if completed_process.stderr is None
                else completed_process.stderr.decode()
            )
            if expected_error1 in error or expected_error2 in error:
                # I/O may trip over itself at high concurrency.
                # We don't care, tell it to try again and re-download the missing piece.
                do_log("Fragmentation error detected, requeuing")
                completed_process = subprocess.run(  # nosec B603
                    download_cmd, cwd=cfg.recording_path, stderr=subprocess.PIPE
                )
            elif INIT_ERROR in error:
                # Recent bug as of 2023-02-24. Unknown cause.
                do_log("Initialization error detected, requeuing")
                completed_process = subprocess.run(  # nosec B603
                    download_cmd, cwd=cfg.recording_path, stderr=subprocess.PIPE
                )
            else:
                log_error(f"Error in 'download' subprocess: '{error}'")
                if error == "ERROR: 'NoneType' object is not subscriptable\n":
                    log_error("Couldn't get vod: Recently deleted?")
                    break
                else:
                    # TODO: Admin alert
                    exit()

        # Update status in datafile
        data_file[vod.id]["status"] = VODStatus.DOWNLOADED
        with open(Path(DATA_PATH, data_file_name), "w") as json_file:
            json.dump(data_file, json_file, indent=2)


def fixup_vods(cfg: Config):
    vods_to_fix: List[FixupCommand] = []
    fix_cmd_raw = cfg.download_cfg.fixup_commandline
    data_file_name = f"{cfg.twitch_channel_name}.json"

    do_log(f'[Fixing VODs for "{cfg.twitch_channel_name}" channel]')

    with open(Path(DATA_PATH, data_file_name), "r") as json_file:
        data_file = json.load(json_file)

    for vod_id, vod_data in data_file.items():
        if vod_data["status"] == VODStatus.DOWNLOADED:
            vods_to_fix.append(FixupCommand(vod_id, vod_data["file_name"]))

    for index, vod in enumerate(vods_to_fix):
        do_log(f"[Fixing VOD {index+1}/{len(vods_to_fix)}]")
        temp_file_name = FIXUP_FILE_NAME.format(file_name=vod.file_name)
        fix_cmd = fix_cmd_raw.format(
            file_name=vod.file_name, temp_file_name=temp_file_name
        )

        completed_process = subprocess.run(  # nosec B603
            fix_cmd,
            cwd=cfg.recording_path,
            stderr=subprocess.PIPE,
        )
        if completed_process.returncode != 0:
            error = (
                ""
                if completed_process.stderr is None
                else completed_process.stderr.decode()
            )
            log_error(f"Error in 'fix' subprocess: {error}")
            # TODO: Admin alert
            exit()

        # Remove unfixed file
        remove(Path(cfg.recording_path, f"{vod.file_name}.mp4"))

        # Update status in datafile
        data_file[vod.id]["status"] = VODStatus.FIXED
        with open(Path(DATA_PATH, data_file_name), "w") as json_file:
            json.dump(data_file, json_file, indent=2)


def split_vods(cfg: Config):
    vods_to_split: List[SplitCommand] = []
    split_cmd_raw = cfg.download_cfg.split_commandline
    data_file_name = f"{cfg.twitch_channel_name}.json"

    do_log(f'[Splitting VODs for "{cfg.twitch_channel_name}" channel]')

    with open(Path(DATA_PATH, data_file_name), "r") as json_file:
        data_file = json.load(json_file)

    for vod_id, vod_data in data_file.items():
        if vod_data["status"] == VODStatus.FIXED:
            should_split = len(vod_data["expected_splits"]) > 1
            vods_to_split.append(
                SplitCommand(vod_id, vod_data["file_name"], should_split)
            )

    for index, vod in enumerate(vods_to_split):
        do_log(f"[Splitting VOD {index+1}/{len(vods_to_split)}]")
        fixed_file_name = FIXUP_FILE_NAME.format(file_name=vod.file_name)

        split_cmd = split_cmd_raw.format(
            input_file_name=fixed_file_name,
            segment_time=cfg.divide_time,
            output_file_name=vod.file_name,
        )

        # TODO: Lengthy process. We need some kind of live progress indicator and it seems we're either
        # limited to "check output programmatically after its done" or
        # "see output as it happens but not be able to use it in code"

        if vod.should_split:
            process = subprocess.run(
                split_cmd,
                cwd=cfg.recording_path,
                shell=True,  # nosec B602
                stdout=sys.stdout,
                stderr=subprocess.STDOUT,
            )

            if process.returncode != 0:
                log_error("Error in 'split' subprocess")
                # TODO: Admin alert
                exit()

            # Remove unsplit file
            remove(Path(cfg.recording_path, f"{fixed_file_name}.mp4"))
        else:
            # File doesn't need to be split but we still want it to follow the format
            rename(
                Path(cfg.recording_path, f"{fixed_file_name}.mp4"),
                Path(cfg.recording_path, f"{vod.file_name}_000.mp4"),
            )

        # Update status in datafile
        data_file[vod.id]["status"] = VODStatus.SPLIT
        with open(Path(DATA_PATH, data_file_name), "w") as json_file:
            json.dump(data_file, json_file, indent=2)


def order_vods(cfg: Config):
    data_file_name = f"{cfg.twitch_channel_name}.json"

    upload_folder = Path(cfg.recording_path, UPLOAD_FOLDER_NAME)
    upload_folder.mkdir(parents=True, exist_ok=True)

    do_log(f'[Ordering VODs for "{cfg.twitch_channel_name}" channel]')

    with open(Path(DATA_PATH, data_file_name), "r") as json_file:
        data_file = json.load(json_file)

    vods_to_sort: List[OrderParentCommand] = []

    unordered_keys = set()

    # Get a list of vods that need to be ordered
    for vod_id, vod_data in data_file.items():
        if vod_data["status"] == VODStatus.SPLIT:
            vods_to_sort.append(
                OrderParentCommand(
                    vod_id,
                    vod_data["file_name"],
                    vod_data["date_str"],
                    vod_data["unix_timestamp"],
                    [split["name"] for split in vod_data["expected_splits"]],
                    True,
                )
            )
            unordered_keys.add(vod_data["date_str"])

    # Get a list of vods that DON'T need to be ordered, but share a day
    for vod_id, vod_data in data_file.items():
        if (
            vod_data["date_str"] in unordered_keys
            and vod_data["status"] != VODStatus.SPLIT
        ):
            do_log(
                f"Found {vod_data['file_name']} under {vod_data['date_str']}, adding to reorder queue"
            )
            vods_to_sort.append(
                OrderParentCommand(
                    vod_id,
                    vod_data["file_name"],
                    vod_data["date_str"],
                    vod_data["unix_timestamp"],
                    [split["name"] for split in vod_data["expected_splits"]],
                    False,
                )
            )

    ordered_vods_to_sort = sorted(
        vods_to_sort, key=lambda vod_data: vod_data.unix_timestamp
    )
    ordered_keys = []
    file_groupings: Dict[str, List[OrderChildCommand]] = {}
    for ordered_vod in ordered_vods_to_sort:
        if ordered_vod.date_str not in ordered_keys:
            ordered_keys.append(ordered_vod.date_str)
            file_groupings[ordered_vod.date_str] = []

        if not ordered_vod.should_order:
            associated_videos = (
                ordered_vod.expected_splits
                if len(ordered_vod.expected_splits) > 1
                else [ordered_vod.file_name]
            )
            for file_name in associated_videos:
                file_groupings[ordered_vod.date_str].append(
                    OrderChildCommand(
                        ordered_vod.id, file_name, ordered_vod.should_order
                    )
                )
            continue

        found_files = sorted(
            [
                file.stem
                for file in cfg.recording_path.glob(f"{ordered_vod.file_name}*.mp4")
            ]
        )

        if (
            len(ordered_vod.expected_splits) > 1
            and found_files != ordered_vod.expected_splits
        ):
            log_error(
                f"Found files not equal to expected splits.\n"
                f"Found files: {found_files}\nExpected Splits:{ordered_vod.expected_splits}"
            )
            return
        else:
            for file_name in found_files:
                file_groupings[ordered_vod.date_str].append(
                    OrderChildCommand(
                        ordered_vod.id, file_name, ordered_vod.should_order
                    )
                )

    for key in ordered_keys:
        file_group = file_groupings[key]
        do_log(f"[Ordering {len(file_group)} VODs from {key}]")

        for index, video in enumerate(file_group):
            original_file_name = f"{video.file_name}.mp4"
            if not video.should_order:
                do_log(
                    f"[Skipping {original_file_name}, but accounting for in rename/sort]"
                )
                continue
            original_path = Path(cfg.recording_path, original_file_name)
            sub_index = f"{(index+1):03d}"
            new_file_name = (
                f"{key}.mp4" if len(file_group) == 1 else f"{key}_{sub_index}.mp4"
            )
            new_path = Path(upload_folder, new_file_name)

            do_log(f"{original_file_name} -> {new_file_name}")
            rename(original_path, new_path)

            data_file[video.vod_id]["status"] = VODStatus.ORDERED

    with open(Path(DATA_PATH, data_file_name), "w") as json_file:
        json.dump(data_file, json_file, indent=2)


def rename_vods(cfg: Config):
    if cfg.title_prefix is None:
        do_log(f'[Skipping rename for "{cfg.twitch_channel_name}" channel]')
        return

    upload_folder = Path(cfg.recording_path, UPLOAD_FOLDER_NAME)
    upload_folder.mkdir(parents=True, exist_ok=True)

    do_log(f'[Renaming VODs for "{cfg.twitch_channel_name}" channel]')

    # TODO: Make better

    files = sorted([file for file in Path(upload_folder).glob("*.mp4")])
    file_names = [file.name for file in files]
    for file in sorted([file for file in Path(upload_folder).glob("*.mp4")]):
        if file.name.startswith(cfg.title_prefix):
            continue
        file_split = file.name.rstrip(".mp4").split("_")
        if len(file_split) == 1:
            date = file_split[0]
            part = 1
        else:
            date, part = file_split # type: ignore
        part = int(part)
        if cfg.title_part_format is None:
            print("No title_part_format defined, skipping")
            continue
        part_str = cfg.title_part_format.replace("{PART_FORMAT}", str(part))

        new_name = f"{cfg.title_prefix} [{date}] {part_str}.mp4"
        name_without_part = f"{cfg.title_prefix} [{date}].mp4"

        if cfg.title_omit_part_if_missing and part == 1:
            potential_part_2_name = f"{date}_002.mp4"
            if potential_part_2_name not in file_names:
                new_name = name_without_part

        new_path = Path(upload_folder, new_name)

        print(f"Renaming '{file.name}' to '{new_name}'")
        rename(file, new_path)
