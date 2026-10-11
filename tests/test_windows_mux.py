import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import describealign as da


class FilterFileTests(unittest.TestCase):
  def test_short_command_is_unchanged(self):
    cmd = ['ffmpeg', '-bsf:v', "setts=pts='PTS'", 'out.mkv']
    with patch.object(da, 'IS_RUNNING_WINDOWS', True), patch.object(da.subprocess, 'run') as run:
      da.run_ffmpeg_with_filter_files(cmd)
    run.assert_called_once_with(cmd, capture_output=True, check=True)

  def test_long_command_preserves_filters_and_cleans_files(self):
    expression = "setts=pts='TS" + '+0' * 9000 + "'"
    cmd = ['ffmpeg', '-bsf:v', expression, '-bsf:a:0', expression,
           '-bsf:s', expression + ':duration=DURATION', 'out.mkv']
    original = list(cmd)
    paths = []

    def inspect_launch(args, **kwargs):
      self.assertLess(len(subprocess.list2cmdline(args)), 30000)
      for index in (1, 3, 5):
        self.assertEqual(args[index], '-/' + cmd[index][1:])
        path = Path(args[index + 1])
        paths.append(path)
        self.assertEqual(path.read_text(encoding='utf-8'), cmd[index + 1])
      self.assertEqual(args[2], args[4])
      return subprocess.CompletedProcess(args, 0, b'', b'')

    with patch.object(da, 'IS_RUNNING_WINDOWS', True), \
         patch.object(da.subprocess, 'run', side_effect=inspect_launch):
      da.run_ffmpeg_with_filter_files(cmd)
    self.assertEqual(cmd, original)
    self.assertTrue(all(not path.exists() for path in paths))

  def test_files_are_cleaned_after_launch_or_mux_failure(self):
    for error in (OSError('launch failed'), subprocess.CalledProcessError(1, 'ffmpeg')):
      paths = []

      def fail(args, **kwargs):
        paths.append(Path(args[2]))
        self.assertTrue(paths[0].exists())
        raise error

      with patch.object(da, 'IS_RUNNING_WINDOWS', True), \
           patch.object(da.subprocess, 'run', side_effect=fail):
        with self.assertRaises(type(error)):
          da.run_ffmpeg_with_filter_files(['ffmpeg', '-bsf:v', 'x' * 31000, 'out.mkv'])
      self.assertFalse(paths[0].exists())

  def test_non_windows_command_is_unchanged(self):
    cmd = ['ffmpeg', '-bsf:v', 'x' * 31000, 'out.mkv']
    with patch.object(da, 'IS_RUNNING_WINDOWS', False), patch.object(da.subprocess, 'run') as run:
      da.run_ffmpeg_with_filter_files(cmd)
    run.assert_called_once_with(cmd, capture_output=True, check=True)

  def test_unshortenable_command_fails_clearly(self):
    with patch.object(da, 'IS_RUNNING_WINDOWS', True), patch.object(da.subprocess, 'run') as run:
      with self.assertRaisesRegex(RuntimeError, 'still too long'):
        da.run_ffmpeg_with_filter_files(['ffmpeg', '-i', 'x' * 31000, 'out.mkv'])
      run.assert_not_called()


class ExitStatusTests(unittest.TestCase):
  def test_batch_continues_and_returns_failure(self):
    # Audio-only pairs without --stretch_audio fail before loading any media.
    with tempfile.TemporaryDirectory() as temp_dir:
      video = Path(temp_dir, 'video')
      audio = Path(temp_dir, 'audio')
      video.mkdir()
      audio.mkdir()
      for name in ('first.mp3', 'second.mp3'):
        (video / name).touch()
        (audio / name).touch()
      output = io.StringIO()
      with patch.object(da, 'PLOT_ALIGNMENT_TO_FILE', False), \
           patch.object(da, 'is_ffmpeg_installed', return_value=True), \
           contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        status = da.combine(str(video), str(audio), yes=True,
                            output_dir=str(Path(temp_dir, 'out')))
      self.assertEqual(status, 1)
      self.assertEqual(output.getvalue().count('ERROR: failed processing pair'), 2)

  def test_empty_inputs_are_not_success(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      with self.assertRaisesRegex(RuntimeError, 'Empty input directory'):
        da.combine(temp_dir, temp_dir, yes=True)
    with patch.object(da, 'get_sorted_filenames', return_value=([], [])):
      with self.assertRaisesRegex(RuntimeError, 'No valid'):
        da.combine('video', 'audio', yes=True)

  def test_cli_returns_combine_status(self):
    for status in (0, 1):
      with patch.object(sys, 'argv', ['describealign', 'video.mkv', 'audio.mp3', '--yes']), \
           patch.object(da, 'combine', return_value=status):
        self.assertEqual(da.command_line_interface(), status)

  def test_script_and_installed_entrypoint_exit_nonzero(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      video = Path(temp_dir, 'video.mp3')
      audio = Path(temp_dir, 'audio.mp3')
      video.touch()
      audio.touch()
      arguments = [str(video), str(audio), '--yes', '--output_dir',
                   str(Path(temp_dir, 'out')), '--alignment_dir', str(Path(temp_dir, 'plots'))]
      for entry in ([sys.executable, str(Path(da.__file__))],
                    [str(Path(sys.executable).parent / 'Scripts' / 'describealign.exe')]
                    if os.name == 'nt' else [sys.executable, '-m', 'describealign']):
        result = subprocess.run(entry + arguments, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('Completed with failures:', result.stdout)


class RealMuxTests(unittest.TestCase):
  def test_stretched_ad_is_appended_and_original_streams_are_preserved(self):
    import numpy as np
    ffmpeg = da.get_ffmpeg()
    for audio_count in (0, 2):
      with self.subTest(original_audio_tracks=audio_count), tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = str(root / 'source.mkv')
        output = str(root / 'stretched.mkv')
        subtitles = root / 'captions.srt'
        subtitles.write_text('1\n00:00:00,100 --> 00:00:00,900\nCaption\n', encoding='utf-8')
        command = [ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                   'testsrc2=size=64x64:rate=10:duration=2']
        if audio_count:
          command += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                      '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2']
        command += ['-i', str(subtitles), '-map', '0:v']
        if audio_count:
          command += ['-map', '1:a', '-map', '2:a',
                      '-metadata:s:a:0', 'language=eng', '-metadata:s:a:0', 'title=English',
                      '-metadata:s:a:1', 'language=ita', '-metadata:s:a:1', 'title=Italian']
        command += ['-map', f'{audio_count + 1}:s', '-c:v', 'mpeg4', '-c:a', 'aac', '-c:s', 'srt', source]
        subprocess.run(command, check=True)
        pcm = np.zeros((da.AUDIO_SAMPLE_RATE * 2, 2), dtype=np.int16)
        da.write_replaced_media_to_disk(output, pcm, video_file=source)
        probe = da.ffmpeg.probe(output, cmd=da.get_ffprobe())
        audio = [s for s in probe['streams'] if s['codec_type'] == 'audio']
        self.assertEqual(len(audio), audio_count + 1)
        self.assertEqual(audio[-1]['tags']['title'], 'Audio Description')
        self.assertEqual(audio[-1]['disposition']['visual_impaired'], 1)
        # Matroska stores visual_impaired; FFmpeg may not round-trip the separate
        # descriptions disposition bit in this container.
        self.assertAlmostEqual(float(probe['format']['duration']), 2, delta=0.1)
        if audio_count:
          self.assertEqual([s['tags']['title'] for s in audio[:-1]], ['English', 'Italian'])
          self.assertEqual([s['tags']['language'] for s in audio[:-1]], ['eng', 'ita'])
          self.assertTrue(all(s['disposition']['visual_impaired'] == 0 for s in audio[:-1]))
        def hashes(path, maps):
          result = subprocess.run([ffmpeg, '-v', 'error', '-i', path, *maps,
                                   '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-'],
                                  capture_output=True, text=True, check=True)
          return result.stdout.splitlines()
        source_maps = ['-map', '0:v', '-map', '0:s']
        if audio_count:
          source_maps += ['-map', '0:a']
        output_maps = ['-map', '0:v', '-map', '0:s']
        for index in range(audio_count):
          output_maps += ['-map', f'0:a:{index}']
        self.assertEqual(hashes(source, source_maps), hashes(output, output_maps))

  def test_oversized_mux_preserves_original_audio_subtitles_and_ad(self):
    ffmpeg = da.get_ffmpeg()
    with tempfile.TemporaryDirectory(prefix='describealign-test-') as temp_dir:
      root = Path(temp_dir)
      source = str(root / 'original.mkv')
      ad = str(root / 'AD.wav')
      output = str(root / 'output.mkv')
      subtitles = root / 'captions.srt'
      subtitles.write_text('1\n00:00:00,100 --> 00:00:00,900\nFixture caption\n', encoding='utf-8')
      subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                      'testsrc2=size=64x64:rate=10:duration=2', '-f', 'lavfi', '-i',
                      'sine=frequency=440:duration=2', '-f', 'lavfi', '-i',
                      'sine=frequency=880:duration=2', '-i', str(subtitles),
                      '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s',
                      '-c:v', 'mpeg4', '-c:a', 'aac', '-c:s', 'srt', source], check=True)
      subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                      'sine=frequency=660:duration=2', ad], check=True)
      # A >32K launch with nontrivial correction, repeated across copied streams.
      # Distant breakpoints are inert in this 2s fixture but inflate the
      # expression like a long movie's alignment. Avoid deep parser recursion.
      expression = 'TS+(0.1/TB' + ''.join(
        f'+clip(TS-{100 + index}.000000/TB,0,1.000000/TB)*0.000000000'
        for index in range(130)) + ')'
      with patch.object(da, 'IS_RUNNING_WINDOWS', True), \
           contextlib.redirect_stdout(io.StringIO()):
        report = da.write_replaced_media_to_disk(output, None, source, ad, expression,
                                                0, 0, retimestamp_original_audio=True)
      self.assertGreater(len(report), 32767)
      self.assertNotIn('describealign-bsf-', report)
      probe = da.ffmpeg.probe(output, cmd=da.get_ffprobe())
      streams = probe['streams']
      self.assertEqual(sum(s['codec_type'] == 'video' for s in streams), 1)
      audio = [s for s in streams if s['codec_type'] == 'audio']
      self.assertEqual(len(audio), 3)
      self.assertEqual(sum(s['codec_type'] == 'subtitle' for s in streams), 1)
      self.assertEqual(audio[-1]['tags']['title'], 'Audio Description')
      self.assertEqual(audio[-1]['disposition']['visual_impaired'], 1)
      self.assertAlmostEqual(float(probe['format']['duration']), 2.1, delta=0.15)
      # Copied originals move with video; AD is not retimestamped.
      for original_audio in audio[:-1]:
        self.assertGreater(float(original_audio['start_time']),
                           float(audio[-1]['start_time']) + 0.05)
      # Compare every packet timestamp to the equivalent small inline command.
      reference = str(root / 'reference.mkv')
      with contextlib.redirect_stdout(io.StringIO()):
        da.write_replaced_media_to_disk(reference, None, source, ad, 'TS+(0.1/TB)',
                                        0, 0, retimestamp_original_audio=True)
      def packet_times(filename):
        probe = da.ffmpeg.probe(filename, cmd=da.get_ffprobe(), show_packets=None)
        return [(p['stream_index'], p.get('pts'), p.get('dts'), p.get('duration'))
                for p in probe['packets']]
      self.assertEqual(packet_times(output), packet_times(reference))
      subprocess.run([ffmpeg, '-v', 'error', '-i', output, '-map', '0:v',
                      '-map', '0:a', '-f', 'null', '-'], check=True)


if __name__ == '__main__':
  unittest.main()
