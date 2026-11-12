"""A canned unittest sample (t-2045 N2b): the check forms of `assertion_probes_ast.python.forms` row PY-unittest and its null row.
Not collected as a test file (the name has no `test_` prefix); the tests read it as bytes and plan mutations of it."""
import unittest


class CalcTests(unittest.TestCase):
    def test_eq_with_author_msg(self):
        self.assertEqual(1 + 1, 2, "author words")

    def test_true_keyword_msg(self):
        self.assertTrue(1 == 1, msg="author kw")

    def test_raises_comes_first(self):
        self.assertRaises(ValueError, int, "x")
        self.assertEqual(1, 1)

    def test_with_raises_comes_first(self):
        with self.assertRaises(ValueError):
            int("x")
            self.assertEqual(1, 1)
        self.assertEqual(2, 2)

    def test_nested_with(self):
        with self.subTest(n=1):
            with self.assertRaises(
                ValueError,
            ):
                int("x")

    def test_unread_call_before_check(self):
        helper_that_checks(1)
        self.assertEqual(3, 3)

    def test_almost_equal_positional_places(self):
        self.assertAlmostEqual(1.0, 1.0, 3)

    def test_other_receiver(self):
        tc = unittest.TestCase()
        tc.assertEqual(1, 1)
        assert 2 == 2

    def test_inside_subtest(self):
        for n in (1, 2):
            with self.subTest(n=n):
                self.assertLess(n, 3)

    def test_multiline(self):
        self.assertIn(
            1,
            [1, 2],
        )
