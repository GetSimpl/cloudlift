from cloudlift.config import secrets_manager
from mock import patch, MagicMock
import unittest
import datetime
from dateutil.tz.tz import tzlocal
import json
from cloudlift.exceptions import UnrecoverableException


class TestSecretsManager(unittest.TestCase):
    @patch('cloudlift.config.secrets_manager.get_client_for')
    def test_get_config(self, mock_get_client_for):
        secrets_manager._secret_manager_cache = {}
        mock_client = MagicMock('boto3_client', get_secret_value=MagicMock(return_value=_get_secret_response()))
        mock_get_client_for.return_value = mock_client

        config = secrets_manager.get_config("dummy-test", "test")

        mock_get_client_for.assert_called_once_with('secretsmanager', 'test')
        mock_client.get_secret_value.assert_called_once_with(SecretId='dummy-test')
        self.assertEqual(config, {'secrets': {'LABEL': 'L1', 'PORT': '80'},
                                  'ARN': 'arn:aws:secretsmanager:us-west-2:12345678:secret:dummy-test-QvDJsW:::a1b87fb5-453e-42bd-a4f5-fdc0834854ef'})

    @patch('cloudlift.config.secrets_manager.get_client_for')
    def test_get_config_caching(self, mock_get_client_for):
        secrets_manager._secret_manager_cache = {}
        mock_client = MagicMock('boto3_client', get_secret_value=MagicMock(return_value=_get_secret_response()))
        mock_get_client_for.return_value = mock_client

        secrets_manager.get_config("dummy-common", "test")
        secrets_manager.get_config("dummy-common", "test")

        mock_get_client_for.assert_called_once_with('secretsmanager', 'test')
        mock_client.get_secret_value.assert_called_once_with(SecretId='dummy-common')

    @patch('cloudlift.config.secrets_manager.get_client_for')
    def test_set_secrets_manager_config_waits_for_consistency(self, mock_client):
        mock_client.return_value = mock_client

        env = "test"
        secret_name = "test-secret"
        config = {'LABEL': 'label', 'PORT': '8080'}

        mock_client.get_secret_value.side_effect = [
            {'SecretString': "{}"},
            {'SecretString': json.dumps({"LABEL": "label"})},
            {'SecretString': json.dumps(config)},
        ]

        secrets_manager.set_secrets_manager_config(env, secret_name, config)

    @patch.object(secrets_manager, 'SECRETS_MANAGER_CONSISTENCY_CHECK_TIMEOUT_SECONDS', 1)
    @patch('cloudlift.config.secrets_manager.get_client_for')
    def test_set_secrets_manager_config_fails_if_not_consistent(self, mock_client):
        mock_client.return_value = mock_client

        env = "test"
        secret_name = "test-secret"
        config = {'LABEL': 'label', 'PORT': '8080'}

        mock_client.get_secret_value.return_value = {"SecretString": "{}"}
        with self.assertRaises(UnrecoverableException):
            secrets_manager.set_secrets_manager_config(env, secret_name, config)

        mock_client.get_secret_value.side_effect = Exception("unable to fetch secret")
        with self.assertRaises(UnrecoverableException):
            secrets_manager.set_secrets_manager_config(env, secret_name, config)


def _get_secret_response():
    return {
        'ARN': 'arn:aws:secretsmanager:us-west-2:12345678:secret:dummy-test-QvDJsW',
        'Name': 'dummy-test', 'VersionId': 'a1b87fb5-453e-42bd-a4f5-fdc0834854ef',
        'SecretString': '{"PORT":"80","LABEL":"L1"}', 'VersionStages': ['AWSCURRENT'],
        'CreatedDate': datetime.datetime(2020, 9, 2, 15, 20, 37, 944000, tzinfo=tzlocal()),
        'ResponseMetadata': {'RequestId': '17f66dd3-8fad-4dad-a43e-e1ec9c99ef06', 'HTTPStatusCode': 200,
                             'HTTPHeaders': {'date': 'Thu, 03 Sep 2020 18:01:47 GMT',
                                             'content-type': 'application/x-amz-json-1.1', 'content-length': '292',
                                             'connection': 'keep-alive',
                                             'x-amzn-requestid': '17f66dd3-8fad-4dad-a43e-e1ec9c99ef06'},
                             'RetryAttempts': 0}}
