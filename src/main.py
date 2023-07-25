from traceback import format_exc

from config import ConfigManager
from utilities import log_error
from vod_download import download_vods, fixup_vods, order_vods, split_vods
from vod_scrape import scrape_vods


def main():
    CFG_MAN = ConfigManager()
    configs = CFG_MAN.configs

    for config in configs:
        scrape_vods(config)
        print("\n\n\n\n\n")
    dl_configs = [config for config in configs if config.download_cfg.do_download]
    for config in dl_configs:
        download_vods(config)
        print("\n\n\n\n\n")
    for config in dl_configs:
        fixup_vods(config)
        print("\n\n\n\n\n")
    for config in dl_configs:
        split_vods(config)
        print("\n\n\n\n\n")
    for config in dl_configs:
        if config.order_before_upload:
            order_vods(config)
            print("\n\n\n\n\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        # TODO: Admin alert
        log_error(format_exc())
