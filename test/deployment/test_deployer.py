import unittest
import json
from unittest.mock import MagicMock
from unittest.mock import patch, mock_open

from cloudlift.deployment import deploy_new_version, EcsTaskDefinition


class TestDeployNewVersion(unittest.TestCase):
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.DeployAction')
    def test(self, DeployAction, ParameterStore):
        sample_env_file_content = "unmodified-key=value1\nadded-key=value2"
        client = MagicMock()

        mock_deployment = MagicMock()
        DeployAction.return_value = mock_deployment

        mock_param_store = MagicMock()
        ParameterStore.return_value = mock_param_store
        mock_param_store.get_existing_config.return_value = {
            'unmodified-key': 'value1', 'added-key': 'value2'}

        task_definition = EcsTaskDefinition({
            'containerDefinitions': [
                {
                    'name': 'test-service',
                    'image': 'test-service:sha0',
                    'environment': [
                        { 'name': 'key1', 'value': 'value1' }
                    ],
                    'secrets': [
                        {'name': 'deleted-key',
                            'valueFrom': 'arn:aws:ssm:region-a:1234:parameter/test/test-service/deleted-key'},
                        {'name': 'unmodified-key', 'valueFrom': 'arn:aws:ssm:region-a:1234:parameter/test/test-service/unmodified-key'},
                    ],
                }
            ]
        })

        expected_task_definition = EcsTaskDefinition({
            'executionRoleArn': 'arn:aws:iam::1234:role/ecsTaskExecutionRole',
            'containerDefinitions': [
                {
                    'name': 'test-service',
                    'image': 'test-service:sha1',
                    'environment': [],
                    'secrets': [
                        {'name': 'unmodified-key', 'valueFrom': 'arn:aws:ssm:region-a:1234:parameter/test/test-service/unmodified-key'},
                        {'name': 'added-key',
                            'valueFrom': 'arn:aws:ssm:region-a:1234:parameter/test/test-service/added-key'}
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
