import unittest
import json
from unittest.mock import MagicMock
from unittest.mock import patch, mock_open

from cloudlift.deployment import deploy_new_version, EcsTaskDefinition


class TestDeployNewVersion(unittest.TestCase):
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.DeployAction')
    def test(self, DeployAction, ParameterStore):
        sample_env_file_content = "key1=value1\nkey2=value2"
        client = MagicMock()

        mock_deployment = MagicMock()
        DeployAction.return_value = mock_deployment

        mock_param_store = MagicMock()
        ParameterStore.return_value = mock_param_store
        mock_param_store.get_existing_config.return_value = {
            'key1': 'valu1', 'key2': 'value2'}

        task_definition = EcsTaskDefinition({
            'containerDefinitions': [
                {
                    'name': 'test-service',
                    'image': 'test-service:sha0'
                }
            ]
        })

        expected_task_definition = EcsTaskDefinition({
            'containerDefinitions': [
                {
                    'name': 'test-service',
                    'image': 'test-service:sha1',
                    'environment': [],
                    'secrets': [
                        {'name': 'key1', 'valueFrom': 'arn:aws:ssm:region-a:1234:test-service/key1'},
                        {'name': 'key2',
                            'valueFrom': 'arn:aws:ssm:region-a:1234:test-service/key2'}
                    ],
                }
            ]
        })

        mock_deployment.get_current_task_definition.return_value = task_definition
        mock_deployment.get_service.return_value = MagicMock(errors=[])

        with patch("builtins.open", mock_open(read_data=sample_env_file_content)):
            try:
                deploy_new_version(
                    client,
                    cluster_name="test-cluster",
                    ecs_service_name="test-service-ecs",
                    deploy_version_tag="sha1",
                    service_name="test-service",
                    sample_env_file_path='/tmp/filepath',
                    env_name='test',
                    region="region-a",
                    account_id='1234',
                )
            except:
                self.fail('exception raised when not expected')

        DeployAction.assert_called_with(
            client, 'test-cluster', 'test-service-ecs')

        assert task_definition == expected_task_definition

        mock_deployment.update_task_definition.assert_called_with(
            expected_task_definition)
