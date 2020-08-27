import pytest
from mock import patch, call, MagicMock

from cloudlift.config import ParameterStore
from cloudlift.exceptions import UnrecoverableException


class TestParameterStore(object):
    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_initialization(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        store_object = ParameterStore('test-service', 'staging')

        mock_get_client_for.assert_called_with('ssm', 'staging')
        assert store_object.environment == 'staging'
        assert store_object.service_name == 'test-service'
        assert store_object.path_prefix == '/staging/test-service/'

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_get_existing_config(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        mock_client.get_parameters_by_path.return_value = {
            'Parameters': [
                {'Name': '/staging/test-service/DUMMY_VAR{}'.format(i), 'Value': 'dummy_values_{}'.format(i)} for i in
                range(0, 4)
            ]
        }

        store_object = ParameterStore('test-service', 'staging')

        env_configs, sidecar_configs = store_object.get_existing_config()
        assert env_configs == {u'DUMMY_VAR0': u'dummy_values_0', u'DUMMY_VAR1': u'dummy_values_1',
                               u'DUMMY_VAR2': u'dummy_values_2', u'DUMMY_VAR3': u'dummy_values_3'}
        assert sidecar_configs == {}

        mock_client.get_parameters_by_path.assert_called_with(
            Path='/staging/test-service/', Recursive=True, WithDecryption=True, MaxResults=10
        )

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_get_existing_config_with_sidecars(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        mock_client.get_parameters_by_path.return_value = {
            'Parameters': [
                {'Name': '/staging/test-service/DUMMY_VAR0', 'Value': 'dummy_values_0'},
                {'Name': '/staging/test-service/sidecars/redis/KEY1', 'Value': 'value1'},
                {'Name': '/staging/test-service/sidecars/redis/KEY2', 'Value': 'value2'},
                {'Name': '/staging/test-service/sidecars/nginx/WORKER_COUNT', 'Value': '2'},
            ]
        }

        store_object = ParameterStore('test-service', 'staging')

        env_config, sidecars_config = store_object.get_existing_config()
        assert env_config == {u'DUMMY_VAR0': u'dummy_values_0'}
        assert sidecars_config == {
            'redis': {'KEY1': 'value1', 'KEY2': 'value2'},
            'nginx': {'WORKER_COUNT': '2'},
        }

        mock_client.get_parameters_by_path.assert_called_with(
            Path='/staging/test-service/', Recursive=True, WithDecryption=True, MaxResults=10
        )

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_get_existing_config_as_string(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        mock_client.get_parameters_by_path.return_value = {
            'Parameters': [
                {'Name': '/staging/test-service/DUMMY_VAR{}'.format(i), 'Value': 'dummy_values_{}'.format(i)} for i in
                range(0, 4)
            ]
        }

        store_object = ParameterStore('test-service', 'staging')

        env_configs = store_object.get_existing_config_as_string()
        assert env_configs == """DUMMY_VAR0=dummy_values_0
DUMMY_VAR1=dummy_values_1
DUMMY_VAR2=dummy_values_2
DUMMY_VAR3=dummy_values_3"""

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_get_existing_config_as_string_for_sidecars(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        mock_client.get_parameters_by_path.return_value = {
            'Parameters': [
                {'Name': '/staging/test-service/DUMMY_VAR0', 'Value': 'dummy_values_0'},
                {'Name': '/staging/test-service/sidecars/redis/KEY1', 'Value': 'value1'},
                {'Name': '/staging/test-service/sidecars/redis/KEY2', 'Value': 'value2'},
                {'Name': '/staging/test-service/sidecars/nginx/WORKER_COUNT', 'Value': '2'},
            ]
        }

        store_object = ParameterStore('test-service', 'staging')

        assert store_object.get_existing_config_as_string('redis') == """KEY1=value1
KEY2=value2"""
        assert store_object.get_existing_config_as_string('nginx') == "WORKER_COUNT=2"

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_set_config(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        differences = [
            ['change', 'DUMMY_VAR12', ('dummy_values_12', 'test_change')],
            ['add', '', [('DUMMY_VAR20', 'test_add_20'), ('DUMMY_VAR21', 'test_add_21')]],
            ['remove', '', [('DUMMY_VAR13', 'dummy_values_13'), ('DUMMY_VAR10', 'dummy_values_10')]]
        ]
        store_object = ParameterStore('test-service', 'dummy-staging')
        store_object.set_config(differences)

        mock_client.put_parameter.assert_has_calls([
            call(Name='/dummy-staging/test-service/DUMMY_VAR12', Value='test_change', Type='SecureString',
                 KeyId='alias/aws/ssm', Overwrite=True),
            call(Name='/dummy-staging/test-service/DUMMY_VAR20', Value='test_add_20', Type='SecureString',
                 KeyId='alias/aws/ssm', Overwrite=False),
            call(Name='/dummy-staging/test-service/DUMMY_VAR21', Value='test_add_21', Type='SecureString',
                 KeyId='alias/aws/ssm', Overwrite=False),
        ])
        mock_client.delete_parameters.assert_called_with(
            Names=['/dummy-staging/test-service/DUMMY_VAR13', '/dummy-staging/test-service/DUMMY_VAR10']
        )

    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_set_config_for_sidecars(self, mock_get_client_for):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        differences = [
            ['change', 'DUMMY_VAR12', ('dummy_values_12', 'test_change')],
            ['add', '', [('DUMMY_VAR20', 'test_add_20'), ('DUMMY_VAR21', 'test_add_21')]],
            ['remove', '', [('DUMMY_VAR13', 'dummy_values_13'), ('DUMMY_VAR10', 'dummy_values_10')]]
        ]
        store_object = ParameterStore('test-service', 'dummy-staging')
        store_object.set_config(differences, 'nginx')

        mock_client.put_parameter.assert_has_calls([
            call(Name='/dummy-staging/test-service/sidecars/nginx/DUMMY_VAR12', Value='test_change',
                 Type='SecureString', KeyId='alias/aws/ssm', Overwrite=True),
            call(Name='/dummy-staging/test-service/sidecars/nginx/DUMMY_VAR20', Value='test_add_20',
                 Type='SecureString', KeyId='alias/aws/ssm', Overwrite=False),
            call(Name='/dummy-staging/test-service/sidecars/nginx/DUMMY_VAR21', Value='test_add_21',
                 Type='SecureString', KeyId='alias/aws/ssm', Overwrite=False),
        ])
        mock_client.delete_parameters.assert_called_with(
            Names=[
                '/dummy-staging/test-service/sidecars/nginx/DUMMY_VAR13',
                '/dummy-staging/test-service/sidecars/nginx/DUMMY_VAR10']
        )

    @patch("cloudlift.config.parameter_store.log_err")
    @patch("cloudlift.config.parameter_store.get_client_for")
    def test_set_config_validation(self, mock_get_client_for, mock_log_err):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client

        invalid_differences = [
            ['change', 'DUMMY_VAR12', ('dummy_values_12', '')],
            ['add', '', [('DUMMY_VAR22', ''), ('DUMMY_VAR*', 'valid_value')]]
        ]
        store_object = ParameterStore('test-service', 'dummy-staging')

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            store_object.set_config(invalid_differences)

        mock_log_err.assert_called_with("'DUMMY_VAR*' is not a valid key.")
        assert pytest_wrapped_e.type == UnrecoverableException
        assert str(pytest_wrapped_e.value) == "'Environment variables validation failed with above errors.'"

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            store_object.set_config(invalid_differences, sidecar_name='nginx')

        mock_log_err.assert_called_with("'DUMMY_VAR*' is not a valid key.")
        assert pytest_wrapped_e.type == UnrecoverableException
        assert str(pytest_wrapped_e.value) == "'Environment variables validation failed with above errors.'"
