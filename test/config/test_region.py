from cloudlift.config import region
from unittest import TestCase
from mock import patch, MagicMock


class TestRegion(TestCase):
    @patch("cloudlift.config.region.local_cache", {})
    @patch("cloudlift.config.region.EnvironmentConfiguration")
    def test_get_region_for_environment_without_cache(self, env_config):
        mock = MagicMock()
        env_config.return_value = mock
        mock.get_config.return_value = {
            'test-env': {
                'region': 'mock-region'
            }
        }

        expected = 'mock-region'
        actual = region.get_region_for_environment('test-env')

        self.assertEqual(actual, expected)

    @patch("cloudlift.config.region.local_cache", {'region': 'mock-region'})
    @patch("cloudlift.config.region.EnvironmentConfiguration")
    def test_get_region_for_environment_with_cache(self, env_config):
        expected = 'mock-region'
        actual = region.get_region_for_environment('test-env')

        self.assertEqual(actual, expected)
        env_config.assert_not_called()

    @patch("cloudlift.config.region.EnvironmentConfiguration")
    def test_get_service_templates_bucket_for_environment_without_cache(self, env_config):
        mock = MagicMock()
        env_config.return_value = mock
        mock.get_config.return_value = {
            'test-env': {
                'service_templates_bucket': 'mock.bucket.url'
            }
        }

        expected = 'mock.bucket.url'
        actual = region.get_service_templates_bucket_for_environment('test-env')

        self.assertEqual(actual, expected)

    @patch("cloudlift.config.region.local_cache", {'bucket': 'mock.bucket.url'})
    @patch("cloudlift.config.region.EnvironmentConfiguration")
    def test_get_service_templates_bucket_for_environment_with_cache(self, env_config):
        expected = 'mock.bucket.url'

        actual = region.get_service_templates_bucket_for_environment('test-env')

        self.assertEqual(actual, expected)
        env_config.assert_not_called()
