import os
from unittest import TestCase

from cfn_flip import to_json
from mock import patch, PropertyMock

from cloudlift.deployment.cluster_template_generator import ClusterTemplateGenerator


ami_for_test = 'ami-04bb74f3ffa3aa3e2'

environment_config_when_vpc_parameterized = {
    "test3": {
        "cluster": {
            "instance_type": "m5.xlarge",
            "key_name": "test2-cluster",
            "max_instances": 5,
            "min_instances": 1,
            "ami_id": "ami-088bb4cd2f62fc0e1",
        },
        "environment": {
            "notifications_arn": "arn:aws:sns:us-west-2:388418451245:test2-cluster",
            "ssl_certificate_arn": "arn:aws:acm:us-west-2:388418451245:certificate/b2bb9a95-cc18-4cb9-a903-593cf8acebde"
        },
        "region": "us-west-2",
        "vpc": {
            "create_new": False,
            "id": "vpc-07a0c611fbe19449a",
            "subnets": {
                "private": {
                    "subnet-1": {
                        "id": "subnet-07f8a309441dbd1cb"
                    },
                    "subnet-2": {
                        "id": "subnet-0039e0fa5344aad34"
                    }
                },
                "public": {
                    "subnet-1": {
                        "id": "subnet-0d8893f4b13dff97e"
                    },
                    "subnet-2": {
                        "id": "subnet-0b2e5ba848982351b"
                    }
                }
            }
        }
    }
}

environment_config_when_vpc_created = {
    "test2": {
        "cluster": {
            "instance_type": "m5.xlarge",
            "key_name": "test2-cluster",
            "max_instances": 5,
            "min_instances": 1
        },
        "environment": {
            "notifications_arn": "arn:aws:sns:us-west-2:388418451245:test2-cluster",
            "ssl_certificate_arn": "arn:aws:acm:us-west-2:388418451245:certificate/b2bb9a95-cc18-4cb9-a903-593cf8acebde"
        },
        "region": "us-west-2",
        "vpc": {
            "create_new": True,
            "cidr": "10.0.0.0/16",
            "nat-gateway": {
                "elastic-ip-allocation-id": "eipalloc-0d11bc40a4f4e9468"
            },
            "subnets": {
                "private": {
                    "subnet-1": {
                        "cidr": "10.0.8.0/22"
                    },
                    "subnet-2": {
                        "cidr": "10.0.12.0/22"
                    }
                },
                "public": {
                    "subnet-1": {
                        "cidr": "10.0.0.0/22"
                    },
                    "subnet-2": {
                        "cidr": "10.0.4.0/22"
                    }
                }
            }
        }
    }
}


class TestClusterTemplateGenerator(TestCase):
    @classmethod
    @patch("cloudlift.deployment.cluster_template_generator.VERSION", "test-version")
    @patch("cloudlift.config.environment_configuration.EnvironmentConfiguration.get_config")
    @patch("cloudlift.config.environment_configuration.EnvironmentConfiguration._get_table")
    @patch("cloudlift.deployment.cluster_template_generator.ClusterTemplateGenerator._get_availability_zones")
    def test_initialization(self, mock_avalability_zones, mock_get_table, mock_get_environment_config):
        mock_get_environment_config.return_value = environment_config_when_vpc_created
        mock_avalability_zones.return_value = ['us-west-2a', 'us-west-2b']
        template_generator = ClusterTemplateGenerator("test2", environment_config_when_vpc_created["test2"])

        generated_template = template_generator.generate_cluster()

        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_cluster_template_when_vpc_created.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(''.join(expected_template_file.readlines())) == to_json(generated_template)

    @staticmethod
    @patch("cloudlift.deployment.cluster_template_generator.VERSION", "test-version")
    @patch("cloudlift.config.region.EnvironmentConfiguration")
    @patch("cloudlift.deployment.ClusterTemplateGenerator._get_availability_zones")
    def helper_mock_create_cluster(env_config, mock_get_avalability_zones, mock_environment_config):
        environment = list(env_config.keys())[0]
        mock_env_config_inst = mock_environment_config.return_value
        mock_env_config_inst.get_config.return_value = env_config
        mock_env_config_inst._get_table.return_value = None
        mock_env_config_inst.env = PropertyMock(return_value=environment)
        mock_get_avalability_zones.return_value = ['us-west-2a', 'us-west-2b']
        template_generator = ClusterTemplateGenerator(environment, env_config[environment])

        return template_generator.generate_cluster()

    def test_create_cluster_when_vpc_parameterized(self):
        generated_template = self.helper_mock_create_cluster(environment_config_when_vpc_parameterized)
        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_cluster_template_when_vpc_parameterized.yml')
        with(open(template_file_path)) as expected_template_file:
            assert generated_template == ''.join(expected_template_file.readlines())

    def test_create_cluster_when_vpc_created(self):
        generated_template = self.helper_mock_create_cluster(environment_config_when_vpc_created)
        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_cluster_template_when_vpc_created.yml')
        with(open(template_file_path)) as expected_template_file:
            assert generated_template == ''.join(expected_template_file.readlines())
