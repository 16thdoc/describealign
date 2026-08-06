# describealign

`describealign` is a desktop-friendly Python tool for lining up a video with a matching audio file, usually an audio description track, and exporting a synced result without making you hand-edit timestamps like a cave goblin.

It compares the source video's audio against the external audio, figures out where they line up, then builds a usable output file and alignment report. The usual use case is taking a movie or episode plus a separate audio description track and producing a version that is actually watchable instead of spiritually hostile.

![describealign](describealign.png)

## What It Does

- Aligns a video file to a matching external audio track.
- Handles timing drift, offsets, and skipped segments.
- Exports combined media into `videos_with_ad`.
- Writes alignment plots and text reports into `alignment_plots`.
- Supports single files, batch folders, drag-and-drop, and CLI usage.
- Uses an English source-audio track when one is present in a multilingual video, otherwise falls back to its first audio track.
- Can also align audio-to-audio when `--stretch_audio` is used.

This fork also includes a practical quality-of-life change:

- It can preserve the original video audio and add the audio description as an additional audio track instead of always replacing the original.

That makes it much nicer for real-world media workflows where you want both the source audio and the AD track available instead of flattening everything into one irreversible blob.

## Why This Exists

Audio description tracks in the wild are often:

- offset from the video
- extracted from podcasts or alt releases
- padded with intros or junk
- stretched or cut in weird places
- close enough to be useful, but annoying enough to be a pain

`describealign` exists to take that mess, detect the matching structure, and produce something synchronized without you manually scrubbing waveforms for an hour and questioning your life choices.

## Quick Start

### GUI

Launch the app, pick:

- a video file or folder of videos
- a matching audio file or folder of audio files

Then click `Combine`.

The output goes to:

- `videos_with_ad` for the exported media
- `alignment_plots` for the visual and text alignment reports

The GUI supports:

- file picking
- folder batching
- drag and drop
- light/dark theme support based on your OS

### Command Line

Run on one video and one audio file:

```bash
describealign video.mp4 audio_description.mp3
```

Run directly from source:

```bash
python describealign.py video.mp4 audio_description.mp3
```

## Installation

### Option 1: Install From PyPI

Python 3.8+ is required.

```bash
pip install describealign
```

Then start the GUI with:

```bash
describealign
```

### Option 2: Run From Source

Clone the repo and install dependencies:

```bash
pip install -r requirements.txt
python describealign.py
```

### Option 3: Use a Release Binary

Prebuilt releases are available here:

<https://github.com/julbean/describealign/releases/latest>

On macOS, you may need to right-click the app and choose `Open` the first time because Apple insists on being Apple.

## Typical Workflow

1. Grab your video.
2. Grab the matching audio description track.
3. Run `describealign`.
4. Review the output media.
5. Check the alignment plot if you want to verify offsets, skips, or drift.

This is especially useful when the AD track:

- starts late
- starts early
- contains intros or dead air
- was sourced from a different release
- has small timing jumps throughout

## Output Behavior

By default, `describealign` stretches the video timeline to match the audio description timing.

Depending on the mode, it can:

- replace aligned sections of the original audio
- preserve the original audio and add AD as a separate track
- generate a plot and text summary of what changed

The text report includes things like:

- similarity score
- start offset
- rate-change segments
- version hash used to generate the alignment

So if the result looks cursed, you have something better than vibes to debug with.

## Advanced Usage

### Batch Processing

You can pass directories instead of single files. Files are matched in lexicographic order.

That means:

- video folder item 1 is paired with audio folder item 1
- video folder item 2 is paired with audio folder item 2
- and so on

This is fast and convenient, but it also means garbage naming leads to garbage pairing, which is fair.

### `--stretch_audio`

`--stretch_audio` flips the alignment direction.

Instead of changing the video timing to fit the external audio, it stretches the audio to fit the video. In this mode, the tool can preserve the original audio and attach the AD track as an additional audio stream, which is often the better output for archive or player-friendly workflows.

It is also required when aligning audio to another audio file.

### Drag and Drop

You can drag files or folders directly into the GUI input lists. Unsupported extensions are ignored.

### Module Usage

You can also call it from Python:

```python
import describealign as da

da.combine("video.mp4", "audio_description.mp3")
```

## Test Media

The repo includes sample media under `test_media` so you can verify that your install is working without sacrificing one of your real files to the debugging gods.

If everything is behaving, you should get:

- a combined output file
- a matching alignment plot
- a text report explaining what happened

## Good Use Cases

- syncing audio description tracks to movies or TV episodes
- lining up dubbed or alternate-language audio against a source video
- generating accessibility-friendly playback versions
- making timing-adjusted outputs without re-encoding the entire video unnecessarily
- doing semi-lossless video edits by using edited audio as the alignment guide

## Caveats

- Better input similarity gives better results.
- Batch mode assumes filenames sort into the right order.
- Weird source edits, missing sections, or totally unrelated tracks can still confuse the alignment.
- You still need `ffmpeg` support available through the toolchain and dependencies.

This is automation, not sorcery. It is good automation, but it is still automation.

## Fork Notes

This repository is based on the original work by Julian Brown and keeps the core alignment workflow intact while adding Trenton-focused practical workflow improvements.

Most notably:

- support for keeping original audio while adding audio description as an additional track
- fixes around subtitle-bearing inputs
- improvements aimed at real local media-library workflows instead of just the clean-room demo path

## Credits

Original project:

- Julian Brown

Fork and workflow-focused enhancements:

- Trenton Smith

## License

GPLv3, same as the upstream project.
