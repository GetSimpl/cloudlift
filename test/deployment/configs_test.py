import unittest

from mock import patch

from cloudlift.deployment.configs import deduce_name


class TestDeduceName(unittest.TestCase):
    @patch('cloudlift.deployment.configs.getcwd')
    def test_deduce_name(self, mock_getcwd):
        mock_getcwd.return_value = '/projects/rippling/main'
        self.assertEqual(deduce_name(None), "main")

    @patch('cloudlift.deployment.configs.getcwd')
    def test_deduce_name_replace_rippling_prefix(self, mock_getcwd):
        mock_getcwd.return_value = '/projects/rippling/rippling-main'
        self.assertEqual(deduce_name(None), "rippling-main")

    def test_deduce_name_with_override(self):
        self.assertEqual(deduce_name('custom-name'), "custom-name")

