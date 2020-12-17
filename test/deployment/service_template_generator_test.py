import datetime
import os
from decimal import Decimal
from unittest import TestCase

from cfn_flip import to_json, to_yaml, load
from mock import patch, MagicMock, call
from moto import mock_dynamodb2


from cloudlift.config import ServiceConfiguration
from cloudlift.deployment.service_template_generator import ServiceTemplateGenerator


def mocked_service_config():
    return {
        "cloudlift_version": 'test-version',
        "notifications_arn": "some",
        "ecr_repo": {"name": "test-service-repo"},
        "services": {
            "Dummy": {
                "memory_reservation": Decimal(1000),
                "command": None,
                "http_interface": {
                    "internal": False,
                    "container_port": Decimal(7003),
                    "restrict_access_to": ["0.0.0.0/0"],
                    "health_check_path": "/elb-check",
                    "deregistration_delay": 88,
                    "load_balancing_algorithm": "round_robin",
                    "health_check_interval_seconds": 43,
                    "health_check_timeout_seconds": 24,
                    "health_check_healthy_threshold_count": 6,
                    "health_check_unhealthy_threshold_count": 4
                },
                "deployment": {
                    "maximum_percent": Decimal(150)
                },
                "secrets_name": "dummy-config",
                "sidecars": [
                    {
                        "name": "redis",
                        "image": "redis:latest",
                        "memory_reservation": 256,
                    }
                ],
                "container_labels": {"label1": "value1"}
            },
            "DummyRunSidekiqsh": {
                "memory_reservation": Decimal(1000),
                "command": "./run-sidekiq.sh",
                "deployment": {
                    "maximum_percent": Decimal(150)  # The configuration is read as decimal always
                },
                "task_role_attached_managed_policy_arns": ["arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"],
                "secrets_name": "dummy-sidekiq-config"
            }
        }
    }


def mocked_udp_service_config():
    return {
        "cloudlift_version": 'test-version',
        "ecr_repo": {"name": "test-service-repo"},
        "notifications_arn": "some",
        "services": {
            "FreeradiusServer": {
                "command": None,
                "memory_reservation": Decimal(1024),
                "secrets_name": "dummy-udp-config",
                "udp_interface": {
                    "container_port": Decimal(1812),
                    "eip_allocaltion_id1": "eipalloc-02abb9e5e123492ee",
                    "eip_allocaltion_id2": "eipalloc-02abb9e5e123492ee",
                    "health_check_port": Decimal(1814),
                    "internal": False,
                    "nlb_enabled": True,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ]
                }
            }
        }
    }


def mocked_tcp_service_config():
    return {
        "cloudlift_version": 'test-version',
        "ecr_repo": {"name": "test-service-repo"},
        "notifications_arn": "some",
        "services": {
            "LdapServer": {
                "command": None,
                "memory_reservation": Decimal(1024),
                "secrets_name": "dummy-tcp-config",
                "tcp_interface": {
                    "container_port": Decimal(1812),
                    "target_group_arn": "arn:aws:elasticloadbalancing:us-west-2:408750594584:targetgroup/Target-Group-for-ldap-test/4481a3b684843845",
                    "target_security_group": "sg-06e825475dae858b8"
                }
            }
        }
    }


def mocked_fargate_service_config():
    return {
        "cloudlift_version": 'test-version',
        "ecr_repo": {"name": "test-service-repo"},
        "notifications_arn": "some",
        "services": {
            "DummyFargateRunSidekiqsh": {
                "command": None,
                "fargate": {
                    "cpu": 256,
                    "memory": 512
                },
                "memory_reservation": 512,
                "secrets_name": "dummy-fargate-config"
            },
            "DummyFargateService": {
                "command": None,
                "fargate": {
                    "cpu": 256,
                    "memory": 512
                },
                "http_interface": {
                    "container_port": 80,
                    "internal": False,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ],
                    "health_check_path": "/elb-check"
                },
                "memory_reservation": 512,
                "secrets_name": "dummy-fargate-config"
            }
        }
    }


def mocked_udp_fargate_service_config():
    return {
        "cloudlift_version": 'test-version',
        "ecr_repo": {"name": "test-service-repo"},
        "notifications_arn": "some",
        "services": {
            "DummyFargateService": {
                "command": None,
                "fargate": {
                    "cpu": 256,
                    "memory": 512
                },
                "udp_interface": {
                    "container_port": 80,
                    "internal": False,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ]
                },
                "memory_reservation": 512,
                "secrets_name": "dummy-fargate-config"
            }
        }
    }


class TestServiceTemplateGenerator(TestCase):

    def test_initialization(self):
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name="test-service",
                                               environment="staging")

        generator = ServiceTemplateGenerator(mock_service_configuration, None, "env.sample", ecr_image_uri="image:v1")

        assert generator.env == 'staging'
        assert generator.application_name == 'test-service'
        assert generator.environment_stack is None

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = mocked_service_config()

        def mock_build_config_impl(env_name, service_name, sample_env_file_path, ecs_service_name, secrets_name):
            expected = "dummy-config" if ecs_service_name == "DummyContainer" else "dummy-sidekiq-config"
            self.assertEqual(secrets_name, expected)
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"Dummy": 100, "DummyRunSidekiqsh": 199})
        generated_template = template_generator.generate_service()
        template_file_path = os.path.join(os.path.dirname(__file__), '../templates/expected_service_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(generated_template) == to_json(''.join(expected_template_file.readlines()))

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service_with_new_alb(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = {
            "cloudlift_version": 'test-version',
            "notifications_arn": "some",
            "ecr_repo": {"name": "test-service-repo"},
            "services": {
                "Dummy": {
                    "memory_reservation": Decimal(1000),
                    "secrets_name": "something",
                    "command": None,
                    "http_interface": {
                        "internal": False,
                        "alb": {
                            "create_new": True,
                            "target_5xx_error_threshold": 10
                        },
                        "container_port": Decimal(7003),
                        "restrict_access_to": ["0.0.0.0/0"],
                        "health_check_path": "/elb-check"
                    },
                    "autoscaling": {
                        "max_capacity": 10,
                        "min_capacity": 5,
                        "request_count_per_target": {
                            "target_value": 10,
                            "scale_in_cool_down_seconds": 120,
                            "scale_out_cool_down_seconds": 60
                        }
                    }
                },
            }
        }

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, sec_name):
            return {ecs_service_name: {"secrets": {}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"
        mock_region_service.get_ssl_certification_for_environment.return_value = "certificateARN1234"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"Dummy": 100, "DummyRunSidekiqsh": 199})

        generated_template = template_generator.generate_service()
        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_service_with_new_alb_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(generated_template) == to_json(''.join(expected_template_file.readlines()))

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service_with_external_alb(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = {
            "cloudlift_version": 'test-version',
            "notifications_arn": "some",
            "ecr_repo": {"name": "test-service-repo"},
            "services": {
                "Dummy": {
                    "memory_reservation": Decimal(1000),
                    "secrets_name": "something",
                    "command": None,
                    "http_interface": {
                        "internal": False,
                        "container_port": Decimal(7003),
                        "restrict_access_to": ["0.0.0.0/0"],
                        "health_check_path": "/elb-check"
                    },
                    "autoscaling": {
                        "max_capacity": 10,
                        "min_capacity": 5,
                        "request_count_per_target": {
                            "alb_arn": "arn:aws:elasticloadbalancing:us-west-2:123456123456:loadbalancer/app/alb-name/alb-id",
                            "target_value": 10,
                            "scale_in_cool_down_seconds": 120,
                            "scale_out_cool_down_seconds": 60
                        }
                    }
                },
            }
        }

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, sec_name):
            return {ecs_service_name: {"secrets": {}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"
        mock_region_service.get_ssl_certification_for_environment.return_value = "certificateARN1234"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"Dummy": 100, "DummyRunSidekiqsh": 199})

        generated_template = template_generator.generate_service()
        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_service_with_external_alb_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(generated_template) == to_json(''.join(expected_template_file.readlines()))

    @patch('cloudlift.deployment.service_template_generator.get_client_for')
    @patch('cloudlift.deployment.service_template_generator.get_environment_level_alb_listener')
    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service_with_env_alb_host_based(self, mock_region_service, mock_get_account_id, mock_build_config,
                                                      mock_get_environment_level_alb_listener, mock_get_client_for):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = {
            "cloudlift_version": 'test-version',
            "notifications_arn": "some",
            "ecr_repo": {"name": "test-service-repo"},
            "services": {
                "Dummy": {
                    "memory_reservation": Decimal(1000),
                    "command": None,
                    "secrets_name": "something",
                    "http_interface": {
                        "internal": False,
                        "alb": {
                            "create_new": False,
                            "host": "abc.xyz.com",
                            "priority": 4,
                            "target_5xx_error_threshold": 10
                        },
                        "container_port": Decimal(7003),
                        "restrict_access_to": ["0.0.0.0/0"],
                        "health_check_path": "/elb-check"
                    },
                    "autoscaling": {
                        "max_capacity": 10,
                        "min_capacity": 5,
                        "request_count_per_target": {
                            "target_value": 10,
                            "scale_in_cool_down_seconds": 120,
                            "scale_out_cool_down_seconds": 60,
                            "alb_arn": "arn:aws:elasticloadbalancing:us-west-2:123456123456:loadbalancer/app/alb-name/alb-id"
                        }
                    }
                },
                "DummyWithCustomListener": {
                    "memory_reservation": Decimal(1000),
                    "command": None,
                    "secrets_name": "something",
                    "http_interface": {
                        "internal": False,
                        "alb": {
                            "create_new": False,
                            "target_5xx_error_threshold": 10,
                            "listener_arn": "arn:aws:elasticloadbalancing:us-west-2:434332696:listener/app/albname/randomalbid/randomlistenerid",
                            "path": "/api/*",
                            "priority": 100,
                        },
                        "container_port": Decimal(7003),
                        "restrict_access_to": ["0.0.0.0/0"],
                        "health_check_path": "/elb-check"
                    }
                },
            }
        }

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, s_name):
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"
        mock_get_environment_level_alb_listener.return_value = "listenerARN1234"
        mock_elbv2_client = MagicMock()
        mock_get_client_for.return_value = mock_elbv2_client

        def mock_describe_rules(ListenerArn=None, Marker=None):
            if ListenerArn:
                return {
                    'Rules': [{'Priority': '1'}, {'Priority': '2'}],
                    'NextMarker': '/next/marker'
                }
            if Marker:
                return {
                    'Rules': [{'Priority': '3'}, {'Priority': '5'}]
                }

        mock_elbv2_client.describe_rules.side_effect = mock_describe_rules

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"Dummy": 100, "DummyRunSidekiqsh": 199})

        generated_template = template_generator.generate_service()

        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_service_with_env_alb_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(generated_template) == to_json(''.join(expected_template_file.readlines()))


    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_fargate_service(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummyFargate'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = mocked_fargate_service_config()

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, prefix):
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/dummyFargate-repo:1.1.1",
                                                      desired_counts={"DummyFargateService": 45,
                                                                      "DummyFargateRunSidekiqsh": 51})

        generated_template = template_generator.generate_service()

        template_file_path = os.path.join(os.path.dirname(__file__),
                                          '../templates/expected_fargate_service_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(generated_template) == to_json(''.join(expected_template_file.readlines()))

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_fargate_service_should_fail_for_udp_interface(self, mock_region_service,
                                                                    mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummyFargate'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = mocked_udp_fargate_service_config()

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, prefix):
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "test-image-repo")
        with self.assertRaises(NotImplementedError) as context:
            template_generator.generate_service()
            self.assertTrue(
                'udp interface not yet implemented in fargate type, please use ec2 type' in context.exception)

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_udp_service(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = mocked_udp_service_config()

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, prefix):
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl
        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"FreeradiusServer": 100})
        generated_template = template_generator.generate_service()
        template_file_path = os.path.join(os.path.dirname(__file__), '../templates/expected_udp_service_template.yml')

        with(open(template_file_path)) as expected_template_file:
            assert to_json(''.join(expected_template_file.readlines())) == to_json(generated_template)

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_tcp_service(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = mocked_tcp_service_config()

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, prefix):
            return {ecs_service_name: {"secrets": {"LABEL": 'arn_secret_label_v1'}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl
        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"FreeradiusServer": 100})
        generated_template = template_generator.generate_service()
        template_file_path = os.path.join(os.path.dirname(__file__), '../templates/expected_tcp_service_template.yml')

        with(open(template_file_path)) as expected_template_file:
            assert to_json(''.join(expected_template_file.readlines())) == to_json(generated_template)

    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service_for_ecr(self, mock_region_service, mock_get_account_id, mock_build_config):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name,
                                               environment=environment)
        mock_service_configuration.get_config.return_value = {
            "cloudlift_version": 'test-version',
            "notifications_arn": "some",
            "ecr_repo": {"name": "main-repo", "assume_role_arn": "arn1234", "account_id": "1234"},
            "services": {
                "Dummy": {
                    "memory_reservation": Decimal(1000),
                    "secrets_name": "something",
                    "command": None,
                },
            }
        }

        def mock_build_config_impl(env_name, cloudlift_service_name, sample_env_file_path, ecs_service_name, sec_name):
            return {ecs_service_name: {"secrets": {}, "environment": {"PORT": "80"}}}

        mock_build_config.side_effect = mock_build_config_impl

        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"
        mock_region_service.get_ssl_certification_for_environment.return_value = "certificateARN1234"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack(),
                                                      './test/templates/test_env.sample',
                                                      "12537612.dkr.ecr.us-west-2.amazonaws.com/test-service-repo:1.1.1",
                                                      desired_counts={"Dummy": 1})

        generated_template = template_generator.generate_service()
        loaded_template = load(to_json(generated_template))

        self.assertGreaterEqual(len(loaded_template), 1, "no template generated")
        generated = loaded_template[0]
        self.check_in_outputs(generated, 'ECRRepoName', 'main-repo')
        self.check_in_outputs(generated, 'ECRAccountID', '1234')
        self.check_in_outputs(generated, 'ECRAssumeRoleARN', 'arn1234')

    def check_in_outputs(self, template, key, value):
        self.assertIn('Outputs', template)
        self.assertTrue(key in template['Outputs'])

        self.assertEqual(
            value,
            template['Outputs'][key].get('Value', None),
        )

    @staticmethod
    def _get_env_stack():
        return {
            u'StackId': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a',
            u'LastUpdatedTime': datetime.datetime(2018, 11, 9, 5, 22, 30, 691000),
            u'Parameters': [{u'ParameterValue': 'staging-cluster-v3', u'ParameterKey': 'KeyPair'},
                            {u'ParameterValue': '1', u'ParameterKey': 'ClusterSize'},
                            {u'ParameterValue': 'arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai',
                             u'ParameterKey': 'NotificationSnsArn'},
                            {u'ParameterValue': 'staging', u'ParameterKey': 'Environment'},
                            {u'ParameterValue': 'm5.xlarge', u'ParameterKey': 'InstanceType'},
                            {u'ParameterValue': '50', u'ParameterKey': 'MaxSize'}], u'Tags': [], u'Outputs': [
                {u'Description': 'VPC in which environment is setup', u'OutputKey': 'VPC',
                 u'OutputValue': 'vpc-00f07c5a6b6c9abdb'},
                {u'Description': 'Options used with cloudlift when building this cluster',
                 u'OutputKey': 'CloudliftOptions',
                 u'OutputValue': '{"min_instances": 1, "key_name": "staging-cluster-v3", "max_instances": 50, "instance_type": "m5.xlarge", "cloudlift_version": "0.9.4", "env": "staging"}'},
                {u'Description': 'Maximum instances in cluster', u'OutputKey': 'MaxInstances', u'OutputValue': '50'},
                {u'Description': 'Security group ID for ALB', u'OutputKey': 'SecurityGroupAlb',
                 u'OutputValue': 'sg-095dbeb511019cfd8'},
                {u'Description': 'Key Pair name for accessing the instances', u'OutputKey': 'KeyName',
                 u'OutputValue': 'staging-cluster-v3'}, {
                    u'Description': 'ID of the 1st subnet', u'OutputKey': 'PrivateSubnet1',
                    u'OutputValue': 'subnet-09b6cd23af94861cc'},
                {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PrivateSubnet2',
                 u'OutputValue': 'subnet-0657bc2faa99ce5f7'},
                {u'Description': 'Minimum instances in cluster', u'OutputKey': 'MinInstances', u'OutputValue': '1'},
                {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PublicSubnet2',
                 u'OutputValue': 'subnet-096377a44ccb73aca'},
                {u'Description': 'EC2 instance type', u'OutputKey': 'InstanceType', u'OutputValue': 'm5.xlarge'},
                {u'Description': 'ID of the 1st subnet', u'OutputKey': 'PublicSubnet1',
                 u'OutputValue': 'subnet-0aeae8fe5e13a7ff7'},
                {u'Description': 'The name of the stack', u'OutputKey': 'StackName', u'OutputValue': 'cluster-staging'},
                {
                    u'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.',
                    u'OutputKey': 'StackId',
                    u'OutputValue': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a'}],
            u'CreationTime': datetime.datetime(2018, 10, 17, 14, 53, 23, 469000),
            u'Capabilities': ['CAPABILITY_NAMED_IAM'], u'StackName': 'cluster-staging', u'NotificationARNs': [],
            u'StackStatus': 'UPDATE_COMPLETE', u'DisableRollback': True,
            u'ChangeSetId': 'arn:aws:cloudformation:ap-south-1:725827686899:changeSet/cg901a2f5dbf984b9e9807a21da1ac7d12/7588cd05-1e2d-4dd6-85ab-12b921baa814',
            u'RollbackConfiguration': {}}
