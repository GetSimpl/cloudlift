import unittest

from cloudlift.deployment import EcsTaskDefinition

class TestEcsTaskDefinition(unittest.TestCase):
    def test_apply_container_environment(self):
        td = EcsTaskDefinition({ 'containerDefinitions': [
            {
                'name': 'hello-world',
                'environment': [
                    { 'name': 'username', 'value': 'oldUser' },
                ],
            }
        ]})

        container = td.containers[0]

        # Method call with a side-effect and no return-value.
        # Assertion has to be done on the side-effect
        td.apply_container_environment(container, [
            ('username', 'adminUser'), ('password', 'superSeretPassword'),
        ])

        expected_task_definition = EcsTaskDefinition({ 'containerDefinitions': [
            {
                'name': 'hello-world',
                'environment': [
                    { 'name': 'username', 'value': 'adminUser' },
                    { 'name': 'password', 'value': 'superSeretPassword' },
                ],
            }
        ]})

        self.assertEqual(td, expected_task_definition)
