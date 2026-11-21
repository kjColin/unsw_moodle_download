#!/usr/bin/env python3
"""What webcms_download.py takes from a WebCMS page, and where it puts it.

    python3 -m unittest test_webcms_rules
"""
import unittest
from pathlib import Path

import webcms_download as w

H = "745a2931a60a5dffcd9202c85ad637bd7925ec4ac6c8dba2cbcf6ebb6e9e476d"
F = f"https://webcms3.cse.unsw.edu.au/files/{H}"


class WhatIsFetched(unittest.TestCase):
    def test_uploaded_file_named_by_its_link_text(self):
        anchors = [["View in browser", F], ["Download", F + "/attachment"], ["L1_Boolean.pdf", F]]
        self.assertEqual(w.fetchables(anchors, [F]),
                         [(H, "L1_Boolean.pdf", F + "/attachment", "file")])

    def test_project_spec_iframe_saved_as_html(self):
        src = "https://cgi.cse.unsw.edu.au/~wong/cs6714-2026proj.html"
        self.assertEqual(w.fetchables([], [src]), [(src, "cs6714-2026proj.html", src, "html")])

    def test_index_page_named_after_its_path(self):
        src = "https://www.cse.unsw.edu.au/~cs6714/21T3/index.html"
        self.assertEqual(w.fetchables([], [src])[0][1], "cs6714-21T3-index.html")

    def test_webcms_own_iframes_ignored(self):
        self.assertEqual(w.fetchables([], ["https://webcms3.cse.unsw.edu.au/x.html"]), [])

    def test_github_tree_link(self):
        g = "https://github.com/cs6714/Resources/tree/main"
        self.assertEqual(w.fetchables([[g, g]], []), [(g, None, g, "github")])

    def test_leaf_ids_skip_the_category_lists(self):
        base = "https://webcms3.cse.unsw.edu.au/COMP6714/26T3/resources/"
        anchors = [["Lectures", base + "124367"], ["Assignments", base + "124372"],
                   ["Boolean", base + "124333"], ["Staff", base + "124367#side-menu6"],
                   ["Boolean", base + "124333"]]
        self.assertEqual(w.leaf_ids(anchors, "COMP6714", "26T3", {124367, 124372}), [124333])


class WhereItGoes(unittest.TestCase):
    def test_same_name_different_file_gets_suffix(self):
        d = Path("/x/COMP6714/Lectures")
        m = {"aaaa1111": "/x/COMP6714/Lectures/L2.pdf"}
        self.assertEqual(w.target_path(d, "L2.pdf", "bbbb2222", m).name, "L2_bbbb2222.pdf")

    def test_known_file_keeps_its_path(self):
        d = Path("/x/COMP6714/Lectures")
        m = {"aaaa1111": "/x/COMP6714/Lectures/renamed.pdf"}
        self.assertEqual(str(w.target_path(d, "L2.pdf", "aaaa1111", m)), m["aaaa1111"])

    def test_unsafe_characters(self):
        self.assertEqual(w.safe_name('a/b:c?.pdf'), "a_b_c_.pdf")


if __name__ == "__main__":
    unittest.main()
