#!/usr/bin/env python3
"""Rules for backing up course materials (PDFs, notebooks, summaries).

    python3 -m unittest test_resource_rules
"""
import tempfile
import unittest
from pathlib import Path

import upload_moodle_resources as r


class DriveLayout(unittest.TestCase):
    def setUp(self):
        self._term_for = r.term_for
        r.term_for = lambda c: {'COMP9414': '2026T1', 'COMP4418': '2026T3'}.get(c, 'Unsorted')

    def tearDown(self):
        r.term_for = self._term_for

    def test_course_file(self):
        self.assertEqual(r.gdrive_dir_for(('COMP4418', 'Lectures')),
                         'UNSW-Backup/2026T3/COMP4418/Lectures')

    def test_nested_category_kept(self):
        self.assertEqual(r.gdrive_dir_for(('COMP9414', 'Materials', 'zip')),
                         'UNSW-Backup/2026T1/COMP9414/Materials/zip')

    def test_summary_lives_with_its_course(self):
        """Summaries sit beside the slides they summarise, not in a separate tree."""
        self.assertEqual(r.gdrive_dir_for(('Summaries', 'COMP9414', 'Lectures')),
                         'UNSW-Backup/2026T1/COMP9414/Summaries/Lectures')

    def test_summary_without_a_course(self):
        self.assertEqual(r.gdrive_dir_for(('Summaries',)), 'UNSW-Backup/Summaries')

    def test_unmapped_course_goes_to_unsorted(self):
        self.assertEqual(r.gdrive_dir_for(('COMP0000', 'Lectures')),
                         'UNSW-Backup/Unsorted/COMP0000/Lectures')

    def test_baidu_path_is_unchanged(self):
        """Baidu keeps its flat /Unsw/<rel> layout — 300+ files already live there."""
        self.assertEqual(r.baidu_dir_for(('Summaries', 'COMP9414', 'Lectures')),
                         '/Unsw/Summaries/COMP9414/Lectures')


class WhatNeedsUploading(unittest.TestCase):
    def test_new_file(self):
        self.assertTrue(r.needs_upload({}))

    def test_baidu_only(self):
        """The 313 T1 materials: on Baidu since June, never on Drive."""
        self.assertTrue(r.needs_upload({'uploaded': True}))

    def test_drive_only(self):
        self.assertTrue(r.needs_upload({'gdrive_uploaded': True}))

    def test_both(self):
        self.assertFalse(r.needs_upload({'uploaded': True, 'gdrive_uploaded': True}))


class DiscoversCoursesFromDisk(unittest.TestCase):
    def test_every_course_dir_is_picked_up(self):
        """A hard-coded course list is why T3 materials were never uploaded."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for rel in ('COMP4418/Lectures/a.pdf', 'COMP9900/Tutorials/b.pdf',
                        'Summaries/COMP4418/Lectures/a.md'):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('x')
            found = {p.relative_to(root).as_posix() for p, _ in r.collect_files(root)}
            self.assertEqual(found, {'COMP4418/Lectures/a.pdf', 'COMP9900/Tutorials/b.pdf',
                                     'Summaries/COMP4418/Lectures/a.md'})

    def test_skips_junk(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for rel in ('COMP4418/.hidden.pdf', 'COMP4418/x.mp4',
                        'COMP4418/proj/.venv/lib/y.py', 'COMP4418/proj/__pycache__/z.py'):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('x')
            self.assertEqual(list(r.collect_files(root)), [])


if __name__ == '__main__':
    unittest.main()
