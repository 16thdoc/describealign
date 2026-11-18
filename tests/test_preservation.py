import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

import describealign as da


def local_support(audio_times, video_times, quality=1.):
  ad = np.linspace(audio_times[0], audio_times[-1], 4201)
  video = np.interp(ad, audio_times, video_times)
  return np.column_stack((video, ad, np.zeros_like(ad), np.full_like(ad, quality), ad))


class PreservationPlanTests(unittest.TestCase):
  def plan(self, audio_times, video_times, quality=1., rate=1., ad_seconds=20., video_seconds=24.):
    audio_times = np.array(audio_times)
    video_times = np.array(video_times)
    return da.plan_preserved_audio(
      audio_times, video_times, local_support(audio_times, video_times, quality), 15., rate,
      round(video_seconds*da.AUDIO_SAMPLE_RATE), round(ad_seconds*da.AUDIO_SAMPLE_RATE), video_seconds)

  def test_offset_and_early_credit_end_preserve_length_without_retiming(self):
    spans, metrics, reasons = self.plan([0., 20.], [.5, 20.508])
    self.assertEqual(reasons, [])
    self.assertEqual(len(spans), 1)
    self.assertFalse(metrics['audio_retimed'])
    self.assertAlmostEqual(metrics['ad_replaced_seconds'], 20.)
    self.assertAlmostEqual(metrics['tail_original_seconds'], 3.5)

  def test_stable_rate_difference_only_retimes_ad(self):
    spans, metrics, reasons = self.plan([0., 20.], [0., 20.84], rate=1.042)
    self.assertEqual(reasons, [])
    self.assertEqual(len(spans), 1)
    self.assertTrue(metrics['audio_retimed'])
    self.assertAlmostEqual(metrics['last_replaced_video_seconds'], 20.84, delta=.001)
    self.assertAlmostEqual(metrics['tail_original_seconds'], 3.16, delta=.001)

  def test_failure_with_a_locally_supported_edit_jump(self):
    _, metrics, reasons = self.plan([0., 9., 9.01, 20.], [0., 9., 11., 21.99])
    self.assertIn('interior_gap_or_edit_jump', reasons)
    self.assertAlmostEqual(metrics['max_interior_original_seconds'], 2.)

  def test_silence_and_unverified_ad_end_do_not_qualify(self):
    _, metrics, reasons = self.plan([0., 17.], [0., 17.], quality=0.)
    self.assertIn('insufficient_overlap_support', reasons)
    self.assertIn('unverified_overlap_boundary', reasons)
    self.assertIsNone(metrics['first_matched_video_seconds'])
    self.assertIn('unverified_ad_trim', self.plan([0., 16.], [0., 16.])[-1])


class PreservationMuxTests(unittest.TestCase):
  def test_render_checks_synced_movie_audio_and_restored_tail(self):
    rate = da.AUDIO_SAMPLE_RATE
    rng = np.random.default_rng(404)
    seconds = np.arange(24*rate) / rate
    envelope = np.interp(seconds, np.arange(0., 24.1, .10), rng.uniform(.08, .9, 241))
    soundtrack = (rng.standard_normal(seconds.shape) * envelope * 4500).astype(np.int16)
    ad = soundtrack[:20*rate].copy()
    ad[3*rate:4*rate] += (1000*np.sin(2*np.pi*350*seconds[:rate])).astype(np.int16)

    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      original_wav, described = root / 'original.wav', root / 'described.wav'
      for filename, sound in ((original_wav, soundtrack), (described, ad)):
        with wave.open(str(filename), 'wb') as stream:
          stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
          stream.writeframes(sound.tobytes())
      original = root / 'original.mkv'
      chapters = root / 'chapters.txt'
      chapters.write_text(';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=20000\ntitle=Story\n'
                          '[CHAPTER]\nTIMEBASE=1/1000\nSTART=20000\nEND=24000\ntitle=Credits\n',
                          encoding='utf-8')
      subprocess.run(
        [da.get_ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i', 'color=s=64x64:r=25:d=24',
         '-i', str(original_wav), '-i', str(chapters), '-map_chapters', '2',
         '-c:v', 'mpeg4', '-c:a', 'flac', str(original)], check=True)
      manifest_path = root / 'validation' / 'result.json'
      with patch.object(da, 'PLOT_ALIGNMENT_TO_FILE', False), \
           contextlib.redirect_stdout(io.StringIO()):
        status = da.combine(str(original), str(described), stretch_audio=True, yes=True,
                            output_dir=str(root / 'out'), validation_manifest=manifest_path)
      self.assertEqual(status, 0)
      manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
      self.assertEqual(manifest['schema'], 1)
      self.assertEqual(manifest['verdict'], 'qualified', manifest)
      self.assertEqual(manifest['reasons'], [])
      metrics = manifest['metrics']
      self.assertFalse(metrics['audio_retimed'])
      self.assertAlmostEqual(metrics['tail_original_seconds'], 4., delta=.03)
      self.assertEqual(metrics['post_render_sync']['status'], 'passed')
      self.assertEqual(metrics['post_render_sync']['restored_tail_window']['status'], 'passed')
      preservation = metrics['original_stream_preservation']
      self.assertEqual(preservation['status'], 'passed')
      self.assertEqual(preservation['matched_original_streams'], 2)
      self.assertEqual(preservation['timed_av_streams'], 2)
      self.assertEqual(preservation['matched_chapters'], 2)
      self.assertEqual(Path(manifest['output_path']).stat().st_size, manifest['output_bytes'])
      self.assertEqual(metrics['source_video_seconds'], 24.)

      def original_stream_hashes(path):
        return subprocess.run(
          [da.get_ffmpeg(), '-v', 'error', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0',
           '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-'],
          check=True, capture_output=True).stdout
      self.assertEqual(original_stream_hashes(original), original_stream_hashes(manifest['output_path']))

      probe_options = {'cmd': da.get_ffprobe(), 'show_chapters': None}
      original_probe = da.ffmpeg.probe(original, **probe_options)
      output_probe = da.ffmpeg.probe(manifest['output_path'], **probe_options)
      output_probe['streams'][0]['start_time'] = '.300'
      output_probe['chapters'][1]['start_time'] = '20.300'
      issues = da.verify_original_streams(original_probe, output_probe)['issues']
      self.assertIn('stream_0_timing_differs_or_unavailable', issues)
      self.assertIn('chapter_1_differs', issues)

      # The AD's audio matches the original at the correct timestamp, not 200 ms late.
      same_tail = np.tile(soundtrack[21*rate:23*rate], (2, 1))
      late_tail = da.check_rendered_window(manifest['output_path'], 1, same_tail, 21.2)
      self.assertEqual(late_tail['status'], 'inconclusive')
      self.assertAlmostEqual(late_tail['lag_seconds'], -.2, delta=.04)

      with self.assertRaisesRegex(FileExistsError, 'new sidecar path'):
        da.combine(str(original), str(described), stretch_audio=True, yes=True,
                   output_dir=str(root / 'out'), validation_manifest=manifest_path)

      review_path = root / 'validation' / 'review.json'
      times = np.array([0., 20.])
      with patch.object(da, 'align', return_value=(times, times, 98., local_support(times, times, 0.), 1.)), \
           patch.object(da, 'PLOT_ALIGNMENT_TO_FILE', False), \
           contextlib.redirect_stdout(io.StringIO()):
        status = da.combine(str(original), str(described), stretch_audio=True, yes=True,
                            output_dir=str(root / 'review'), validation_manifest=review_path)
      self.assertEqual(status, 0)
      review = json.loads(review_path.read_text(encoding='utf-8'))
      self.assertEqual(review['verdict'], 'review_required')
      self.assertIn('insufficient_overlap_support', review['reasons'])

  def test_mp4_validation_preserves_embedded_chapter_carrier(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      original, output, chapters = root / 'original.mp4', root / 'out.mp4', root / 'chapters.txt'
      chapters.write_text(';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=3000\ntitle=Credits\n',
                          encoding='utf-8')
      subprocess.run(
        [da.get_ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i', 'color=s=64x64:r=25:d=3',
         '-f', 'lavfi', '-i', 'sine=duration=3', '-i', str(chapters), '-map_chapters', '2',
         '-c:v', 'mpeg4', '-c:a', 'aac', str(original)], check=True)
      pcm = np.zeros((2, 3*da.AUDIO_SAMPLE_RATE), dtype=np.int16)
      da.write_replaced_media_to_disk(str(output), pcm, video_file=str(original),
                                      preserve_original_dispositions=True)
      probes = [da.ffmpeg.probe(path, cmd=da.get_ffprobe(), show_chapters=None)
                for path in (original, output)]
      preservation = da.verify_original_streams(*probes)
      self.assertEqual(preservation['status'], 'passed', preservation)
      self.assertEqual(preservation['matched_original_streams'], 3)
      self.assertEqual(preservation['matched_chapters'], 1)

  def test_redirected_cli_uses_utf8_with_non_ascii_filenames(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      video, ad = root / '字幕.mp3', root / '音声.mp3'
      video.touch()
      ad.touch()
      result = subprocess.run(
        [sys.executable, str(Path(da.__file__)), str(video), str(ad), '--yes',
         '--output_dir', str(root / 'out'), '--alignment_dir', str(root / 'plots')],
        env={**os.environ, 'PYTHONIOENCODING': 'cp1252'}, capture_output=True)
      self.assertEqual(result.returncode, 1)
      self.assertIn(video.name, result.stdout.decode('utf-8'))
      self.assertNotIn(b'UnicodeEncodeError', result.stderr)


if __name__ == '__main__':
  unittest.main()
