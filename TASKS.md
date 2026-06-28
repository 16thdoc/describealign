# Tasks

## Keep original audio synchronized when adding AD track

### Problem

When `describealign` adds an audio description track while preserving the original audio, it primarily syncs the AD track/video relationship. The preserved original audio should also be checked against the adjusted video timeline.

If the original audio would drift or become offset after video retiming, `describealign` should retime or sync that original audio too instead of blindly copying it.

### Desired behavior

- When preserving original audio and adding AD as an additional stream, validate original-audio-to-video sync after alignment decisions are made.
- If the video timeline is retimed or stretched, ensure original audio stays aligned to the resulting video output.
- If original audio cannot be safely copied without sync issues, process or retime it as needed.
- Preserve existing fork behavior where original audio is kept and AD is added as a separate track.
- Avoid degrading quality unnecessarily; copy streams when safe, transform only when needed.

### Acceptance criteria

- Add logic or a clearly defined check for whether preserved original audio remains in sync with output video.
- Add or adjust ffmpeg handling so original audio is corrected when needed.
- Existing AD alignment behavior still works.
- Outputs with subtitles still avoid prior subtitle/stream mapping issues.
- Test with the bundled Ask Dad sample and at least one real-world video where original audio is preserved.

### Notes

This is especially relevant to this fork's behavior where original audio is retained and AD is added as another track, rather than replacing the original audio.
