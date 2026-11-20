#!/usr/bin/env python3
"""Guards the rule that makes this pipeline safe to run on a full disk:
a local video is only ever deleted once BOTH remotes have a verified copy."""
import unittest

import upload_and_clean_videos as u


class SafeToDeleteLocal(unittest.TestCase):
    def test_both_remotes_verified(self):
        self.assertTrue(u.safe_to_delete_local({'uploaded': True, 'gdrive_uploaded': True}))

    def test_baidu_only(self):
        self.assertFalse(u.safe_to_delete_local({'uploaded': True, 'gdrive_uploaded': False}))

    def test_gdrive_only(self):
        self.assertFalse(u.safe_to_delete_local({'uploaded': False, 'gdrive_uploaded': True}))

    def test_neither(self):
        self.assertFalse(u.safe_to_delete_local({}))

    def test_legacy_item_without_gdrive_field_is_not_deletable(self):
        """Pre-Drive items say uploaded=True and nothing about Drive. Those
        still on disk must wait for Drive, not be deleted on the old rule."""
        self.assertFalse(u.safe_to_delete_local({'uploaded': True}))


class NeedsWork(unittest.TestCase):
    def test_pending_when_only_baidu_done(self):
        self.assertTrue(u.needs_work({'downloaded': True, 'uploaded': True}))

    def test_pending_when_only_gdrive_done(self):
        self.assertTrue(u.needs_work({'downloaded': True, 'gdrive_uploaded': True}))

    def test_not_pending_when_both_done(self):
        self.assertFalse(u.needs_work({'downloaded': True, 'uploaded': True, 'gdrive_uploaded': True}))

    def test_not_pending_when_never_downloaded(self):
        self.assertFalse(u.needs_work({'downloaded': False, 'note': 'no_m3u8'}))


if __name__ == '__main__':
    unittest.main()
