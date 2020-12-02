import unittest
from cloudlift.deployment.ecs import EcsTaskDefinition, EcsAction, EcsClient
from cloudlift.exceptions import UnrecoverableException

from mock import MagicMock, patch, call


class TestEcsTaskDefinition(unittest.TestCase):
    def test_apply_container_environment_and_secrets_with_env_conf_only(self):
        env = [{'name': 'PORT', 'value': '80'}, {'name': 'LABEL', 'value': 'L3'}]
        td = _build_task_definition(_build_container_definition(environment=env))

        new_env_config = {
            "secrets": {},
            "environment": {"PORT": "80", "LABEL": 'L4'}
        }
        td.apply_container_environment_and_secrets(td.containers[0], new_env_config)

        expected_updated_env = [{'name': 'PORT', 'value': '80'}, {'name': 'LABEL', 'value': 'L4'}]
        self.assertEqual(td.containers[0]['environment'], expected_updated_env)
        self.assertEqual(len(td.diff), 2)
        diff = td.diff[0]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'environment')
        self.assertEqual(diff.value, {'LABEL': 'L4', 'PORT': '80'})
        self.assertEqual(diff.old_value, {'LABEL': 'L3', 'PORT': '80'})
        diff = td.diff[1]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'secrets')
        self.assertEqual(diff.value, {})
        self.assertEqual(diff.old_value, {})

    def test_apply_container_environment_and_secrets_with_env_moving_to_secrets(self):
        env = [{'name': 'PORT', 'value': '80'}, {'name': 'LABEL', 'value': 'L3'}]
        td = _build_task_definition(_build_container_definition(environment=env, secrets=[]))

        new_env_config = {
            "secrets": {"LABEL": 'secret_label_arn'},
            "environment": {"PORT": "80"}
        }
        td.apply_container_environment_and_secrets(td.containers[0], new_env_config)

        expected_updated_env = [{'name': 'PORT', 'value': '80'}]
        self.assertEqual(td.containers[0]['environment'], expected_updated_env)
        expected_updated_secrets = [{'name': 'LABEL', 'valueFrom': 'secret_label_arn'}]
        self.assertEqual(td.containers[0]['secrets'], expected_updated_secrets)
        self.assertEqual(len(td.diff), 2)
        diff = td.diff[0]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'environment')
        self.assertEqual(diff.value, {'PORT': '80'})
        self.assertEqual(diff.old_value, {'LABEL': 'L3', 'PORT': '80'})
        diff = td.diff[1]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'secrets')
        self.assertEqual(diff.value, {"LABEL": 'secret_label_arn'})
        self.assertEqual(diff.old_value, {})

    def test_apply_container_environment_and_secrets_with_secrets_modified(self):
        secrets = [{'name': 'LABEL', 'valueFrom': 'arn:v1'}]
        td = _build_task_definition(_build_container_definition(secrets=secrets))

        new_env_config = {
            "secrets": {"LABEL": 'arn:v2'},
        }
        td.apply_container_environment_and_secrets(td.containers[0], new_env_config)

        self.assertEqual(td.containers[0]['environment'], [])
        expected_updated_secrets = [{'name': 'LABEL', 'valueFrom': 'arn:v2'}]
        self.assertEqual(td.containers[0]['secrets'], expected_updated_secrets)
        self.assertEqual(len(td.diff), 2)
        diff = td.diff[0]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'environment')
        self.assertEqual(diff.value, {})
        self.assertEqual(diff.old_value, {})
        diff = td.diff[1]
        self.assertEqual(diff.container, 'DummyContainer')
        self.assertEqual(diff.field, 'secrets')
        self.assertEqual(diff.value, {"LABEL": 'arn:v2'})
        self.assertEqual(diff.old_value, {"LABEL": 'arn:v1'})


class TestEcsAction(unittest.TestCase):
    def test_get_task_definition_by_deployment_identifier(self):
        cluster_name = "cluster-1"
        service_name = MagicMock()
        service_name.task_definition.return_value.family.return_value = "prodServiceAFamily"
        client = MagicMock()
        client.list_task_definitions.return_value = (['arn1', 'arn2', 'arn3', 'arn4'], None)

        def mock_describe_task_definition(task_definition_arn):
            if task_definition_arn == 'arn3':
                return {'taskDefinition': {'taskDefinitionArn': task_definition_arn}, 'tags': [
                    {'key': 'deployment_identifier', 'value': 'id-0'},
                ]}
            else:
                return {'taskDefinition': {'taskDefinitionArn': task_definition_arn}, 'tags': {}}

        client.describe_task_definition.side_effect = mock_describe_task_definition

        action = EcsAction(client, cluster_name, service_name)

        actual_td = action.get_task_definition_by_deployment_identifier(service=service_name,
                                                                        deployment_identifier="id-0")

        self.assertEqual('arn3', actual_td.arn)
        self.assertEqual({'deployment_identifier': 'id-0'}, actual_td.tags)
        client.list_task_definitions.assert_called_with = 'prodServiceAFamily'

    @patch("cloudlift.deployment.ecs.Session")
    def test_get_task_definition_by_deployment_identifier_with_next_token(self, mock_session):
        cluster_name = "cluster-1"
        service_name = MagicMock()
        service_name.task_definition.return_value.family.return_value = "prodServiceAFamily"
        mock_boto_client = MagicMock()
        mock_session.return_value.client.return_value = mock_boto_client

        client = EcsClient()

        mock_boto_client.list_task_definitions.side_effect = [
            {'taskDefinitionArns': ['arn1', 'arn2'], 'nextToken': 'token1'},
            {'taskDefinitionArns': ['arn3', 'arn3']},
        ]

        def mock_describe_task_definition(taskDefinition, include):
            if taskDefinition == 'arn3':
                return {'taskDefinition': {'taskDefinitionArn': taskDefinition, 'family': 'tdFamily'}, 'tags': [
                    {'key': 'deployment_identifier', 'value': 'id-0'},
                ]}
            else:
                return {'taskDefinition': {'taskDefinitionArn': taskDefinition, 'family': 'tdFamily'}, 'tags': {}}

        mock_boto_client.describe_task_definition.side_effect = mock_describe_task_definition

        action = EcsAction(client, cluster_name, service_name)

        actual_td = action.get_task_definition_by_deployment_identifier(service=service_name,
                                                                        deployment_identifier="id-0")

        self.assertEqual('arn3', actual_td.arn)
        self.assertEqual({'deployment_identifier': 'id-0'}, actual_td.tags)
        mock_boto_client.list_task_definitions.assert_has_calls([
            call(familyPrefix='tdFamily', status='ACTIVE', sort='DESC'),
            call(familyPrefix='tdFamily', status='ACTIVE', sort='DESC', nextToken='token1')
        ])

    @patch("cloudlift.deployment.ecs.Session")
    def test_get_task_definition_by_deployment_identifier_with_no_matches(self, mock_session):
        cluster_name = "cluster-1"
        service_name = MagicMock()
        service_name.task_definition.return_value.family.return_value = "stgServiceAFamily"
        mock_boto_client = MagicMock()
        mock_session.return_value.client.return_value = mock_boto_client

        client = EcsClient()

        mock_boto_client.list_task_definitions.side_effect = [
            {'taskDefinitionArns': ['arn1', 'arn2'], 'nextToken': 'token1'},
            {'taskDefinitionArns': ['arn3', 'arn3']},
        ]

        def mock_describe_task_definition(taskDefinition, include):
            return {'taskDefinition': {'taskDefinitionArn': taskDefinition, 'family': 'tdFamily'}, 'tags': {}}

        mock_boto_client.describe_task_definition.side_effect = mock_describe_task_definition

        action = EcsAction(client, cluster_name, service_name)

        with self.assertRaises(UnrecoverableException) as error:
            action.get_task_definition_by_deployment_identifier(service=service_name,
                                                                deployment_identifier="id-0")

        self.assertEqual("task definition does not exist for deployment_identifier: id-0", error.exception.value)


def _build_task_definition(container_defn):
    return EcsTaskDefinition({'taskDefinitionArn': 'arn:aws:ecs:us-west-2:408750594584:task-definition/DummyFamily:4',
                              'containerDefinitions': [container_defn],
                              'family': 'DummyFamily',
                              'taskRoleArn': 'arn:aws:iam::408750594584:role/dummy-test-DummyRole-BEXNIBTBTB33',
                              'revision': 4, 'volumes': [], 'status': 'ACTIVE',
                              'requiresAttributes': [{'name': 'com.amazonaws.ecs.capability.logging-driver.awslogs'},
                                                     {'name': 'com.amazonaws.ecs.capability.ecr-auth'}, ],
                              'placementConstraints': [], 'compatibilities': ['EC2']})


def _build_container_definition(environment=None, secrets=None):
    image = '408750594584.dkr.ecr.us-west-2.amazonaws.com/dummy-repo:eb3089ccc48b5fa8081d296ab81457759fb9995d'
    cd = {'name': 'DummyContainer', 'image': image,
          'cpu': 0, 'memoryReservation': 1000, 'links': [], 'portMappings': [
            {'containerPort': 80, 'hostPort': 0, 'protocol': 'tcp'}], 'essential': True,
          'entryPoint': [], 'command': [],
          'logConfiguration': {'logDriver': 'awslogs',
                               'secretOptions': []}, 'systemControls': []}
    if environment:
        cd['environment'] = environment
    if secrets:
        cd['secrets'] = secrets
    return cd
