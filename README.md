# About

Twitch VODs expire after a certain amount of time, Youtube videos do not. So this Python script helps automate Twitch VOD archiving to Youtube, by automatically generating yt-dlp and ffmpeg commands.

## Why generate terminal commands and not use the FFMPEG or YT-DLP libraries for Python?

Better debugging. Since this is a personal utility, I want to be able to run the exact commands that are being run with ease on my own with no change in behavior. I prefer stability over good code for this project.

## Why not use Twitch's download or export functionality?

Sometimes you want to provide an archive for others without asking for their Twitch password (scary)

## Why is this only focused/tested on Windows?

I use Windows at home. Until I can reliably scrape+download hidden Twitch VODs, or automate publishing unpublished Twitch VODs, there will still be a degree of manual input. This is low priority as Twitch doesn't even support these in their API with a full-permission token.

Also, from my limited work with Youtube APIs, they are semi-reliable at best. I do not currently trust them, and the daily limits are very restrictive for testing and development (or just more active channels).

If its ever capable of being automated E2E, I will move to and test \*Nix.

# "Default Commands" Explanation

## **download_commandline**

> `yt-dlp --fixup never --retries "infinite" --file-access-retries "infinite" --fragment-retries "infinite" --concurrent-fragments 10 -o "{file_name}.%(ext)s" {vod_url}`

`--fixup never`

> Setting this to `never` allows us to run the time-consuming cpu-focused (instead of network-focused) process at a later time. See `fixup_commandline` for why this is needed at all.

`--retries "infinite"`, `--file-access-retries "infinite"`, `--fragment-retries "infinite"`

> Forces the command to retry on common failures. If `concurrent-fragments` is specified (and higher than default `1`), recommend these to be infinite or very high.

`--concurrent-fragments 10`

> Allows multi-threaded downloading. `10` appears to be the highest you can have on a single download from Twitch without potentially running into a "timeout cascade", resulting in slower overall completion time.

`-o {file_name}.%(ext)s`

> Output file, where `{file_name}` is what this script chooses, and `.%(ext)s` is "`.`" (literal), followed by the extension yt-dlp will provide ("`%(ext)`"), formatted by yt-dlp as a string ("`s`"). It is possible to do date-time filenames with yl-dlp (see [Output Template](https://github.com/yt-dlp/yt-dlp#output-template)) but for consistency in our future commands, we choose the filename and only let it choose the extension (it's easier to debug a "file not found" error in FFmpeg if the extension is not mp4, versus silent failure or corruption from unexpected changes in yt-dlp)

`{vod_url}`

> Twitch URL to whatever VOD we will end up downloading

## **fixup_commandline**

[According to a "yt-dlp" developer](https://i.imgur.com/phxIiB2.png), any HLS-AAC streams not downloaded by FFmpeg may require this fixup, and it is not easy to detect if its required or not. In an automated system, the time it takes to run this versus risk of unsynchronized audio (or worse), is worth it.

_This command was obtained by running `yt-dlp --verbose` on a Twitch download with the `--fixup never` command omitted. This is effectively what `[FixupM3u8]` is._

> `ffmpeg -y -i "file:{file_name}.mp4" -map 0 -dn -ignore_unknown -c copy -f mp4 -bsf:a aac_adtstoasc -movflags "+faststart" "file:{temp_file_name}.mp4"`

`-y`

> Allows overwriting of the output file without prompting. Since we are writing to a temporary file, we want this to be true all the time.

`-i "file:{file_name}.mp4"`

> `-i` is desired input file. In FFmpeg, prefixing file arguments with `file:` prevents issues when the filename contains ":", since FFmpeg can interpret that as a protocol, or in previous versions, prevent breaking if the filename starts with "-".

`-map 0`

> Specifies ALL input streams should be included in the output. By default, only 1 stream per type is automatically chosen.

`-dn`

> When used as an input option, prevents filtering, auto-selection or auto-mapping for all data streams.

`-ignore_unknown`

> Instead of failing when copying an unknown input-stream-type, ignore and continue.

`-c copy`

> Indicate the stream is not to be re-encoded.

`-f mp4`

> Force file format to MP4.

`-bsf:a aac_adtstoasc`

> Applies the `aac_adtstoasc` audio bitstream filter. Required when copying an AAC stream from MPEG-TS container to MP4. Creates an MPEG-4 AudioSpecificConfig from an MPEG-4 ADTS header and removes the ADTS header.

`-movflags "+faststart"`

> Moves metadata about the video to the start of the file instead of the end of it, for better/quicker playback and compatibility.

`"file:{temp_file_name}.mp4"`

> Our output file, should be "FILENAME.temp.mp4"

## **split_commandline**

This command is only run if downloaded stream exceeds the specified `divide_time` config option, defaulting to `11h59m57s` (1s less than the 12 hour YouTube limit, plus 2s safety buffer)

> `ffmpeg -hwaccel cuda -i "file:{input_filename}.mp4" -map 0 -c copy -f segment -segment_time 11:59:57 -reset_timestamps 1 "file:{input_filename}_%03d.mp4"`

`-hwaccel cuda`

> Uses the CUDA acceleration if a compatible Nvidia card is present. Should be adjusted or removed to fit environment. Experiment with it!

`-i "file:{input_filename}.mp4"`

> `-i` is desired input file. In FFmpeg, prefixing file arguments with `file:` prevents issues when the filename contains ":", since FFmpeg can interpret that as a protocol. In previous FFmpeg versions, also prevents breaking if the filename starts with "-".

`-map 0`

> Specifies ALL input streams should be included in the output. By default, only 1 stream per type is automatically chosen.

`-c copy`

> Indicate the stream is not to be re-encoded.

`-f segment`

> A muxer that outputs input streams to a number of separate files of nearly fixed duration.

`-segment_time`

> Maximum duration a video can be before splitting to a new file.

`-reset_timestamps 1`

> Resets timestamps at the start of each new file to ensure accuracy. Prevents thumbnail corruption and other oddities, but primarily opts for "potentially have some video from part 1 in part 2" over "never have video from part 1 in part 2, but potentially lose some video forever in between"

`"file:{input_filename}_%03d.mp4"`

> Our output files, in this case "xyz_00#.mp4"
