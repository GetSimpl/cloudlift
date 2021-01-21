from unittest import TestCase
from cloudlift.deployment.task_definition_builder import TaskDefinitionBuilder


class TaskDefinitionBuilderTest(TestCase):
    def test_build_task_definition_for_http_api(self):
        configuration = {
            'command': './start_script.sh',
            "container_health_check": {
                "command": "./check-health.sh",
                "start_period": 10
            },
            'http_interface': {'container_port': 9090},
            'memory_reservation': 100,
            'stop_timeout': 70,
            'system_controls': [{"namespace": "net.core.somaxconn", "value": "1024"}],
            'task_execution_role_arn': 'arn1',
            'task_role_arn': 'arn2',
            'placement_constraints': [{'type': 'memberOf', 'expression': 'expr'}]
        }
        builder = TaskDefinitionBuilder(
            environment="test",
            service_name="dummy",
            configuration=configuration,
            region='region1',
        )

        expected = {
            'containerDefinitions': [{
                'command': ['./start_script.sh'],
                'cpu': 0,
                'environment': [{'name': 'PORT', 'value': '80'}],
                'essential': True,
                'healthCheck': {
                    'command': ['CMD-SHELL', './check-health.sh'],
                    'startPeriod': 10,
                },
                'image': 'nginx:default',
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-group': 'test-logs',
                        'awslogs-region': 'region1',
                        'awslogs-stream-prefix': 'dummy',
                    },
                },
                'memory': 20480,
                'memoryReservation': 100,
                'name': 'dummyContainer',
                'portMappings': [{'containerPort': 9090}],
                'secrets': [{'name': 'CLOUDLIFT_INJECTED_SECRETS', 'valueFrom': 'arn_injected_secrets'}],
                'stopTimeout': 70,
                'systemControls': [{'namespace': 'net.core.somaxconn', 'value': '1024'}],
            }],
            'executionRoleArn': 'arn1',
            'family': 'testdummyFamily',
            'taskRoleArn': 'arn2',
            'placementConstraints': [{'type': 'memberOf', 'expression': 'expr'}]
        }

        actual = builder.build_task_definition(
            container_configurations={
                'dummyContainer': {
                    "secrets": {"CLOUDLIFT_INJECTED_SECRETS": 'arn_injected_secrets'},
                    "environment": {"PORT": "80"}
                },
            },
            ecr_image_uri="nginx:default",
            fallback_task_role='fallback_arn1',
            fallback_task_execution_role='fallback_arn2',
        )

        self.assertEqual(expected, actual)

    def test_build_task_definition_with_log_group(self):
        configuration = {
            'command': './start_script.sh',
            'container_health_check': {
                'command': './check-health.sh',
                'start_period': 10
            },
            'log_group': 'custom-log-group',
            'memory_reservation': 100,
            'memory_hard_limit': 200,
        }
        builder = TaskDefinitionBuilder(
            environment="test",
            service_name="dummy",
            configuration=configuration,
            region='region1',
        )

        expected = {
            'containerDefinitions': [{
                'command': ['./start_script.sh'],
                'cpu': 0,
                'environment': [],
                'essential': True,
                'healthCheck': {
                    'command': ['CMD-SHELL', './check-health.sh'],
                    'startPeriod': 10,
                },
                'image': 'nginx:default',
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-group': 'custom-log-group',
                        'awslogs-region': 'region1',
                        'awslogs-stream-prefix': 'dummy',
                    },
                },
                'memory': 200,
                'memoryReservation': 100,
                'name': 'dummyContainer',
                'secrets': [],
            }],
            'executionRoleArn': 'fallback_arn1',
            'family': 'testdummyFamily',
            'taskRoleArn': 'fallback_arn2',
            'placementConstraints': [],
        }

        actual = builder.build_task_definition(
            container_configurations={
                'dummyContainer': {},
            },
            ecr_image_uri="nginx:default",
            fallback_task_execution_role='fallback_arn1',
            fallback_task_role='fallback_arn2',
        )

        self.assertEqual(expected, actual)

    def test_build_task_definition_with_fargate(self):
        configuration = {
            'command': './start_script.sh',
            'container_health_check': {
                'command': './check-health.sh',
                'start_period': 10
            },
            'fargate': {
                'cpu': 10,
                'memory': 256,
            },
            'log_group': 'custom-log-group',
            'memory_reservation': 100,
            'task_execution_role_arn': 'arn1',
            'task_role_arn': 'arn2',
        }
        builder = TaskDefinitionBuilder(
            environment="test",
            service_name="dummy",
            configuration=configuration,
            region='region1',
        )

        expected = {
            'containerDefinitions': [{
                'command': ['./start_script.sh'],
                'cpu': 0,
                'environment': [],
                'essential': True,
                'healthCheck': {
                    'command': ['CMD-SHELL', './check-health.sh'],
                    'startPeriod': 10,
                },
                'image': 'nginx:default',
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-group': 'custom-log-group',
                        'awslogs-region': 'region1',
                        'awslogs-stream-prefix': 'dummy',
                    },
                },
                'memory': 20480,
                'memoryReservation': 100,
                'name': 'dummyContainer',
                'secrets': [],
            }],
            'cpu': '10',
            'executionRoleArn': 'arn1',
            'family': 'testdummyFamily',
            'memory': '256',
            'networkMode': 'awsvpc',
            'requiresCompatibilities': ['FARGATE'],
            'taskRoleArn': 'arn2',
            'placementConstraints': [],
        }

        actual = builder.build_task_definition(
            container_configurations={
                'dummyContainer': {},
            },
            ecr_image_uri="nginx:default",
            fallback_task_role='fallback_arn',
            fallback_task_execution_role='fallback_arn',
        )

        self.assertEqual(expected, actual)

    def test_build_task_definition_with_udp_interface(self):
        configuration = {
            'command': './start_script.sh',
            'container_health_check': {
                'command': './check-health.sh',
                'start_period': 10
            },
            'udp_interface': {
                'container_port': 1,
                'health_check_port': 2,
            },
            'log_group': 'custom-log-group',
            'memory_reservation': 100,
            'task_execution_role_arn': 'arn1',
            'task_role_arn': 'arn2',
        }
        builder = TaskDefinitionBuilder(
            environment="test",
            service_name="dummy",
            configuration=configuration,
            region='region1',
        )

        expected = {
            'containerDefinitions': [{
                'command': ['./start_script.sh'],
                'cpu': 0,
                'environment': [],
                'essential': True,
                'healthCheck': {
                    'command': ['CMD-SHELL', './check-health.sh'],
                    'startPeriod': 10,
                },
                'image': 'nginx:default',
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-group': 'custom-log-group',
                        'awslogs-region': 'region1',
                        'awslogs-stream-prefix': 'dummy',
                    },
                },
                'memory': 20480,
                'memoryReservation': 100,
                'name': 'dummyContainer',
                'portMappings': [{'containerPort': 1, 'hostPort': 1, 'protocol': 'udp'},
                                 {'containerPort': 2, 'hostPort': 2, 'protocol': 'tcp'}],
                'secrets': [],
            }],
            'executionRoleArn': 'arn1',
            'family': 'testdummyFamily',
            'networkMode': 'awsvpc',
            'taskRoleArn': 'arn2',
            'placementConstraints': [],
        }

        actual = builder.build_task_definition(
            container_configurations={
                'dummyContainer': {},
            },
            ecr_image_uri="nginx:default",
            fallback_task_role='fallback_arn',
            fallback_task_execution_role='fallback_arn',
        )

        self.assertEqual(expected, actual)
