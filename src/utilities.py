from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone
from enum import Enum
from json import load as load_json
from time import strptime as time_strptime
from typing import Any, Dict, List, TextIO, Tuple

import iso8601
from pytz import timezone as pytz_timezone


class VODStatus(str, Enum):
    NOT_DOWNLOADED = "NOT_DOWNLOADED"
    DOWNLOADED = "DOWNLOADED"
    FIXED = "FIXED"
    SPLIT = "SPLIT"
    ORDERED = "ORDERED"
    READY_TO_UPLOAD = "READY_TO_UPLOAD"
    UPLOADED = "UPLOADED"
    FAILED_TO_UPLOAD = "FAILED_TO_UPLOAD"


# TODO: Please just use the logging library, this is an awful series of patches from code of a decade ago
def get_est_time(datetime_to_convert: datetime | None = None) -> str:
    """
    Gets the current time (or 'datetime_to_convert' arg, if provided) as datetime and converts it to a
    readable string
    """
    desired_timezone = pytz_timezone("America/Toronto")
    if datetime_to_convert is not None:
        input_timezone = pytz_timezone("UTC")
        if datetime_to_convert.tzinfo is not None:
            # TODO: Convert datetime tzinfo to pytz accordingly
            do_log("GET_EST_TIME ERROR, PLEASE IMPLEMENT CONVERTER")
            return "ERROR"
        timezoned_datetime = input_timezone.localize(datetime_to_convert)
        output_datetime = timezoned_datetime.astimezone(desired_timezone)
    else:
        output_datetime = datetime.now(desired_timezone)

    return output_datetime.strftime("%Y-%b-%d %I:%M:%S %p EST")


# TODO: Please just use the logging library, this is an awful series of patches from code of a decade ago
def do_log(message: str):
    log_message = f"[{get_est_time()}] {message}"
    log_filename = "log.log"
    try:
        with open(log_filename, "a") as log_file:
            log_file.write(f"{log_message}\n\n")
    except FileNotFoundError:
        with open(log_filename, "w") as log_file:
            log_message = f"[{get_est_time()}] WARNING: Failed to find existing log. Writing to new.\n\n{log_message}"
            log_file.write(f"{log_message}\n\n")
    print(log_message)


# TODO: Please just use the logging library, this is an awful series of patches from code of a decade ago
def log_error(error: str):
    if "KeyboardInterrupt" in error:
        raise KeyboardInterrupt
    error_message = f"[{get_est_time()}]\n{error}"
    error_log_filename = "errors.log"
    try:
        with open(error_log_filename, "a") as error_log:
            error_log.write(f"{error_message}\n\n")
    except FileNotFoundError:
        with open(error_log_filename, "w") as error_log:
            error_message = f"[{get_est_time()}] WARNING: Failed to find existing error log. Writing to new.\n\n{error}"
            error_log.write(f"{error_message}\n\n")
    print(error_message)


# TODO: Implement Pydantic
def json_eval_object_pairs_hook(ordered_pairs: List[Tuple[Any, Any]]) -> Dict:
    """
    Additional hook for JSON loader to turn any strings into representative datatypes (bool, int,
    float) wherever possible.
    """
    special = {
        "true": True,
        "false": False,
        "null": None,
    }
    result = {}
    for key, value in ordered_pairs:
        if key in special:
            key = special[key]
        else:
            for numeric in int, float:
                try:
                    key = numeric(key)
                except ValueError:
                    continue
                else:
                    break
        result[key] = value
    return result


# TODO: Implement Pydantic
def json_load_eval(fp_obj: TextIO) -> Dict:
    """
    Loads a JSON file, evaluating any strings to possible variables.
    """
    return load_json(fp_obj, object_pairs_hook=json_eval_object_pairs_hook)


def stream_time_to_datetime(time_string):
    converted_time = (
        iso8601.parse_date(time_string)
        .replace(tzinfo=datetime_timezone.utc)
        .astimezone(tz=None)
    )
    return converted_time


def stream_time_to_timestamp(time_string):
    converted_time = (
        iso8601.parse_date(time_string)
        .replace(tzinfo=datetime_timezone.utc)
        .astimezone(tz=None)
    )
    return converted_time.timestamp()


def duration_str_to_seconds(duration_str: str) -> int:
    """
    Converts a string like "1d9h8m7s" to seconds, as an int.

    This is typically the format used in Twitch API responses.
    """
    # TODO: datetime.strptime
    total_seconds = 0.0
    if "d" in duration_str:
        days, duration_str = duration_str.split("d", 1)
        total_seconds += float(days) * 60 * 60 * 24

    if "h" in duration_str:
        hours, duration_str = duration_str.split("h", 1)
        total_seconds += float(hours) * 60 * 60

    if "m" in duration_str:
        minutes, duration_str = duration_str.split("m", 1)
        total_seconds += float(minutes) * 60

    if "s" in duration_str:
        seconds, duration_str = duration_str.split("s", 1)
        total_seconds += float(seconds)

    return int(total_seconds)


def hhmmss_to_seconds(duration_str: str) -> int:
    """
    Converts an "HH:MM:SS"-like string to seconds, as an int.
    """
    time_struct = time_strptime(duration_str, "%H:%M:%S")
    time_delta = timedelta(
        hours=time_struct.tm_hour,
        minutes=time_struct.tm_min,
        seconds=time_struct.tm_sec,
    )
    return int(time_delta.total_seconds())
