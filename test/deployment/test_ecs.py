import unittest

from cloudlift.deployment import EcsTaskDefinition


class TestEcsTaskDefinition(unittest.TestCase):
    def test_apply_container_environment(self):
        region = 'region-1'
        account_id = '1234'
        service_name = 'test-service'

        td = EcsTaskDefinition({'containerDefinitions': [
            {
                'name': 'hello-world',
                'environment': [
                    {'name': 'username', 'value': 'oldUser'},
                ],
                'secrets': [
                    {'name': 'existing-key',
                        'valueFrom': 'arn:aws:ssm:region-1:1234:test-service/existing-key'},
                ]
            }
        ]})

        container = td.containers[0]

        # Method call with a side-effect and no return-value.
        # Assertion has to be done on the side-effect
        td.apply_container_environment(container, region, account_id, service_name, [
            ('username', 'adminUser'), ('password', 'superSeretPassword'),
        ])

        expected_task_definition = EcsTaskDefinition({'containerDefinitions': [
            {
                'name': 'hello-world',
                'environment': [],
                'secrets': [
                    {'name': 'username',
                        'valueFrom': 'arn:aws:ssm:region-1:1234:test-service/username'},
                    {'name': 'password',
                        'valueFrom': 'arn:aws:ssm:region-1:1234:test-service/password'},
                ],
            }
        ]})

        assert td == expected_task_definition
