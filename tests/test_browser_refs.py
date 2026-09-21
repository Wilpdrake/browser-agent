import unittest

from browser_agent.browser import RefStore, StaleReferenceError, score_element


class ReferenceTests(unittest.TestCase):
    def test_clear_does_not_reuse_refs(self):
        refs = RefStore()
        first = refs.add({"token": "a"})
        refs.clear()
        second = refs.add({"token": "b"})
        self.assertNotEqual(first, second)
        with self.assertRaises(StaleReferenceError):
            refs.get(first)
        self.assertEqual(refs.get(second)["token"], "b")

    def test_search_synonyms(self):
        search = {"tag": "input", "type": "search", "label": "Search"}
        other = {"tag": "button", "text": "Submit"}
        self.assertGreater(
            score_element("поле поиска", search), score_element("поле поиска", other)
        )
        self.assertGreater(score_element("search box", {"placeholder": "Поиск"}), 0)
