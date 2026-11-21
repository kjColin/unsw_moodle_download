#!/usr/bin/env python3
"""Rules that let a re-scan mirror Baidu-only recordings to Google Drive
without re-uploading them to Baidu.

Run as colin (playwright lives in colin's site-packages):
    python3 -m unittest test_mirror_rules
"""
import json
import tempfile
import unittest
from pathlib import Path

import echo360_batch_download as d


class RegistryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._saved = (d.REG_PATH, d.LOCK_PATH)
        d.REG_PATH = tmp / 'reg.json'
        d.LOCK_PATH = tmp / 'reg.lock'
        self.write([])

    def tearDown(self):
        d.REG_PATH, d.LOCK_PATH = self._saved
        self.tmp.cleanup()

    def write(self, items):
        d.REG_PATH.write_text(json.dumps({'items': items}), encoding='utf-8')


class DoneMeansBothRemotes(RegistryFixture):
    def test_baidu_only_is_not_done(self):
        """The whole point: 332 Baidu-only recordings must be fetched again."""
        self.write([{'course_name': 'C', 'dedup_key': 'k', 'downloaded': True,
                     'uploaded': True, 'upload_status': 'done', 'local_path': '/nope'}])
        self.assertFalse(d.is_done_or_pending('C', 'k'))

    def test_both_remotes_is_done(self):
        self.write([{'course_name': 'C', 'dedup_key': 'k', 'downloaded': True,
                     'uploaded': True, 'gdrive_uploaded': True, 'local_path': '/nope'}])
        self.assertTrue(d.is_done_or_pending('C', 'k'))

    def test_downloaded_and_still_on_disk_is_pending(self):
        """A file awaiting upload must not be fetched a second time."""
        f = Path(self.tmp.name) / 'v.mp4'
        f.write_bytes(b'x')
        self.write([{'course_name': 'C', 'dedup_key': 'k', 'downloaded': True,
                     'uploaded': True, 'upload_status': 'done', 'local_path': str(f)}])
        self.assertTrue(d.is_done_or_pending('C', 'k'))


class BaiduStateCarriesOver(RegistryFixture):
    def test_same_key_already_on_baidu(self):
        self.write([{'course_name': 'C', 'dedup_key': 'C::L::slides',
                     'uploaded': True, 'remote_dir': '/Unsw/C/Lectures'}])
        self.assertEqual(d.baidu_state_for('C', 'C::L::slides', 'C::L', 'slides'),
                         (True, '/Unsw/C/Lectures'))

    def test_legacy_camera_key_counts_for_camera(self):
        """Pre-dual-stream rows stored the camera track under the bare lesson
        key; re-fetching it under ::camera must not upload it to Baidu again."""
        self.write([{'course_name': 'C', 'dedup_key': 'C::L',
                     'uploaded': True, 'remote_dir': '/Unsw/C/Lectures'}])
        self.assertEqual(d.baidu_state_for('C', 'C::L::camera', 'C::L', 'camera'),
                         (True, '/Unsw/C/Lectures'))

    def test_legacy_camera_key_does_not_count_for_slides(self):
        """The legacy row only ever held the camera track."""
        self.write([{'course_name': 'C', 'dedup_key': 'C::L', 'uploaded': True}])
        self.assertEqual(d.baidu_state_for('C', 'C::L::slides', 'C::L', 'slides'),
                         (False, None))

    def test_new_recording(self):
        self.assertEqual(d.baidu_state_for('C', 'C::L::single', 'C::L', 'single'),
                         (False, None))

    def test_other_course_same_key_ignored(self):
        self.write([{'course_name': 'OTHER', 'dedup_key': 'C::L::slides', 'uploaded': True}])
        self.assertEqual(d.baidu_state_for('C', 'C::L::slides', 'C::L', 'slides'),
                         (False, None))


class ClassifiedNotesSurviveRescan(RegistryFixture):
    def test_confirmed_no_media_is_kept(self):
        """A rescan finding no stream again must not turn a hand-checked
        "Flexibility Week (No Lecture)" back into an unexplained no_m3u8."""
        self.write([{'course_name': 'C', 'dedup_key': 'C::L', 'note': 'no_media_confirmed'}])
        self.assertTrue(d.keep_existing_classification('C', 'C::L'))

    def test_plain_no_m3u8_is_rewritten(self):
        self.write([{'course_name': 'C', 'dedup_key': 'C::L', 'note': 'no_m3u8'}])
        self.assertFalse(d.keep_existing_classification('C', 'C::L'))

    def test_unknown_lesson_is_written(self):
        self.assertFalse(d.keep_existing_classification('C', 'C::L'))


if __name__ == '__main__':
    unittest.main()
