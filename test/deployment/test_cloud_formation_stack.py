from cloudlift.deployment.cloud_formation_stack import prepare_stack_options_for_template

from unittest import TestCase
from mock import patch
from moto import mock_s3
import boto3
from tempfile import NamedTemporaryFile


class TestCloudFormationStack(TestCase):
    def test_prepare_stack_options_for_template_for_small_template(self):
        template_body = 'sample template'
        environment = 'dummy-test'
        stack_name = 'test-stack'

        expected_options = {
            'TemplateBody': template_body
        }
        options = prepare_stack_options_for_template(template_body, environment, stack_name)

        self.assertEqual(options, expected_options)

    @patch("cloudlift.deployment.cloud_formation_stack.get_service_templates_bucket_for_environment")
    @patch("cloudlift.config.region.get_region_for_environment")
    @patch("cloudlift.deployment.cloud_formation_stack.get_region_for_environment")
    def test_prepare_stack_options_for_template_for_large_template(self,
                                                                   local_get_region_for_environment,
                                                                   config_get_region_for_environment,
                                                                   get_service_templates_bucket_for_environment):
        mock_bucket_url = "mock.bucket.url"
        mock_region = "mock-region"

        local_get_region_for_environment.return_value = mock_region
        config_get_region_for_environment.return_value = mock_region
        get_service_templates_bucket_for_environment.return_value = mock_bucket_url

        with mock_s3():
            template_body = 'sample template' * 4000
            environment = 'dummy-test'
            stack_name = 'test-stack'

            expected_options = {
                'TemplateURL': 'https://s3-mock-region.amazonaws.com/mock.bucket.url/dummy-test/test-stack.template'
            }
            options = prepare_stack_options_for_template(template_body, environment, stack_name)
            self.assertEqual(options, expected_options)
            s3 = boto3.resource('s3')

            mock_bucket = s3.Bucket(mock_bucket_url)
            self.assertEqual(mock_bucket.name, mock_bucket_url)

            f = NamedTemporaryFile(delete=True)
            mock_bucket.download_file('dummy-test/test-stack.template', f.name)

            with open(f.name) as data:
                self.assertEqual(data.read(), template_body)

            f.close()
