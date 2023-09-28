"""
This module handles global cloudlift configuration that is custom to
the organization using cloudlift
"""
import ipaddress
from distutils.version import LooseVersion

import boto3
import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, prompt
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from cloudlift.version import VERSION
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config import DecimalEncoder, print_json_changes
from cloudlift.config.dynamodb_configuration import DynamodbConfiguration
from cloudlift.config.pre_flight import check_sns_topic_exists, check_aws_instance_type
from cloudlift.config.utils import ConfigUtils
from cloudlift.constants import logging_json_schema
# import config.mfa as mfa
from cloudlift.config.logging import log_bold, log_err, log_warning

ENVIRONMENT_CONFIGURATION_TABLE = 'environment_configurations'


class EnvironmentConfiguration(object):
    '''
        Handles configuration in DynamoDB for cloudlift
    '''

    def __init__(self, environment=None):
        self.environment = environment

        session = boto3.session.Session()
        self.dynamodb = session.resource('dynamodb')
        self.table = DynamodbConfiguration(ENVIRONMENT_CONFIGURATION_TABLE, [
                       ('environment', self.environment)])._get_table()
        self.config_utils = ConfigUtils(changes_validation_function=self._validate_changes)

    def get_config(self, cloudlift_version=VERSION):
        '''
            Get configuration from DynamoDB
        '''

        try:
            configuration_response = self.table.get_item(
                Key={
                    'environment': self.environment
                },
                ConsistentRead=True,
                AttributesToGet=[
                    'configuration'
                ]
            )
            existing_configuration = configuration_response['Item']['configuration']
            previous_cloudlift_version = existing_configuration.pop("cloudlift_version", None)
            # print(f"Previous cloudlift version in environment config is {previous_cloudlift_version}")
            if previous_cloudlift_version and LooseVersion(cloudlift_version) < LooseVersion(previous_cloudlift_version):
                raise UnrecoverableException(f'Cloudlift Version {previous_cloudlift_version} was used to '
                                             f'create this environment. You are using version {cloudlift_version}, '
                                             f'which is older and can cause corruption. Please upgrade to at least '
                                             f'version {previous_cloudlift_version} to proceed.\n\nUpgrade to the '
                                             f'latest version (Recommended):\n'
                                             f'\tpip install -U cloudlift\n\nOR\n\nUpgrade to a compatible version:\n'
                                             f'\tpip install -U cloudlift=={previous_cloudlift_version}')
            return existing_configuration
        except ClientError:
            raise UnrecoverableException("Unable to fetch environment configuration from DynamoDB.")
        except KeyError:
            raise UnrecoverableException("Environment configuration not found. Does this environment exist?")

    def update_config(self):

        if not self._env_config_exists():
            self._create_config()
        self._edit_config()

    def get_all_environments(self):
        response = self.table.scan(
            TableName=ENVIRONMENT_CONFIGURATION_TABLE,
            AttributesToGet=[
                'environment',
            ],
            Limit=10,
            Select='SPECIFIC_ATTRIBUTES',
            ScanFilter={},
            ConsistentRead=True
        )
        return [env['environment'] for env in response['Items']]

    def _env_config_exists(self):
        response = self.table.get_item(
            Key={
                'environment': self.environment,
            }
        )
        return response.get('Item') is not None

    def _create_config(self):
        log_warning(
            "\nConfiguration for this environment was not found in DynamoDB.\
            \nInitiating prompts for setting up configuration.\
            \nIf this environment was previously configured, please ensure\
            \ndefault region is the same as previously used. Otherwise, use\
            \nthe same configuration.\n"
        )
        region = prompt("AWS region for environment", default='ap-south-1')
        vpc_cidr = ipaddress.IPv4Network(prompt("VPC CIDR, for example 10.10.0.0/16"))
        nat_eip = prompt("Allocation ID Elastic IP for NAT")
        public_subnet_1_cidr = prompt(
            "Public Subnet 1 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[0])
        public_subnet_2_cidr = prompt(
            "Public Subnet 2 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[1])
        private_subnet_1_cidr = prompt(
            "Private Subnet 1 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[2])
        private_subnet_2_cidr = prompt(
            "Private Subnet 2 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[3])
        cluster_types = prompt("Cluster type \n [1] On-Demand \n [2] Spot \n [3] Both \n default ", default=3)
        if cluster_types == 1:
            od_cluster_min_instances = prompt("Min instances in On-Demand cluster", default=1)
            od_cluster_max_instances = prompt("Max instances in On-Demand cluster", default=5)
            spot_cluster_min_instances = 0
            spot_cluster_max_instances = 0
            ecs_cluster_default_instance_type = "ondemand"
            cluster_instance_types = prompt("Instance types", default='t2.micro')
        elif cluster_types == 2:
            spot_cluster_min_instances = prompt("Min instances in Spot cluster", default=1)
            spot_cluster_max_instances = prompt("Max instances in Spot cluster", default=5)
            od_cluster_min_instances = 0
            od_cluster_max_instances = 0
            ecs_cluster_default_instance_type = "spot"
            cluster_instance_types = prompt("Instance types in comma delimited string", default='t2.micro,m5.xlarge')
        else:
            od_cluster_min_instances = prompt("Min instances in On-Demand cluster", default=1)
            od_cluster_max_instances = prompt("Max instances in On-Demand cluster", default=5)
            spot_cluster_min_instances = prompt("Min instances in Spot cluster", default=1)
            spot_cluster_max_instances = prompt("Max instances in Spot cluster", default=5)
            cluster_instance_types = prompt("Instance types in comma delimited string, \nFor On-Demand only first instance type will be considered", default='t2.micro,m5.xlarge')
            ecs_cluster_default_instance_type = prompt("Default instance type for ECS cluster Spot/OnDemand", default='OnDemand')
        check = False
        while not check:
            cluster_instance_types = cluster_instance_types.replace(" ", "")
            check, instance_type = check_aws_instance_type(cluster_instance_types)
            if not check:
                log_err(f"Invalid instance type: {instance_type}")
                cluster_instance_types = prompt( "Instance types in comma delimited string, \nFor On-Demand only first instance type will be considered", default='t2.micro,m5.xlarge')

        if cluster_types != 1:
            spot_allocation_strategy = prompt("Spot Allocation Strategy capacity-optimized/lowest-price/price-capacity-optimized", default='capacity-optimized')
            if spot_allocation_strategy == 'lowest-price':
                spot_instance_pools = prompt("Number of Spot Instance Pools", default=2)
        cluster_ami_id_ssm = prompt("SSM parameter path of Custom AMI ID", default='None')
        key_name = prompt("SSH key name")
        notifications_arn = prompt("Notification SNS ARN")
        ssl_certificate_arn = prompt("SSL certificate ARN")
        environment_configuration = {self.environment: {
            "region": region,
            "vpc": {
                "cidr": str(vpc_cidr),
                "nat-gateway": {
                    "elastic-ip-allocation-id": nat_eip
                },
                "subnets": {
                    "public": {
                        "subnet-1": {
                            "cidr": str(public_subnet_1_cidr)
                        },
                        "subnet-2": {
                            "cidr": str(public_subnet_2_cidr)
                        }
                    },
                    "private": {
                        "subnet-1": {
                            "cidr": str(private_subnet_1_cidr)
                        },
                        "subnet-2": {
                            "cidr": str(private_subnet_2_cidr)
                        }
                    }
                }
            },
            "cluster": {
                "min_instances": od_cluster_min_instances,
                "max_instances": od_cluster_max_instances,
                "spot_min_instances": spot_cluster_min_instances,
                "spot_max_instances": spot_cluster_max_instances,
                "instance_type": cluster_instance_types,
                "key_name": key_name,
                "ami_id": cluster_ami_id_ssm,
                "ecs_instance_default_lifecycle_type": ecs_cluster_default_instance_type.lower()
            },
            "environment": {
                "notifications_arn": notifications_arn,
                "ssl_certificate_arn": ssl_certificate_arn
            },
            "service_defaults": {
                "logging": "awslogs",
                "fluentbit_config": {
                "image_uri": "amazon/aws-for-fluent-bit:stable",
                "env": {
                    "kinesis_role_arn": ""
                    }
                },
            }
        }, 'cloudlift_version': VERSION}
        if cluster_types != 1:
            environment_configuration[self.environment]['cluster']['spot_allocation_strategy'] = spot_allocation_strategy
            if spot_allocation_strategy == 'lowest-price':
                environment_configuration[self.environment]['vpc']['cluster']['spot_instance_pools'] = spot_instance_pools
        self._set_config(environment_configuration)
        pass

    def _edit_config(self):
        '''
            Open editor to update configuration
        '''
        try:
            current_configuration = self.get_config()
            previous_cloudlift_version = current_configuration.pop('cloudlift_version', None)
            updated_configuration = self.config_utils.fault_tolerant_edit_config(current_configuration=current_configuration)
            if updated_configuration is None:
                log_warning("No changes made.")
                return
            differences = list(dictdiffer.diff(
                    current_configuration,
                    updated_configuration
                ))
            if not differences:
                    log_warning("No changes made.")
                    updated_configuration['cloudlift_version']=VERSION
                    self._set_config(updated_configuration)
                    # self.update_cloudlift_version()
            else:
                print_json_changes(differences)
                if confirm('Do you want to update the config?'):
                    self._set_config(updated_configuration)
                    # self.update_cloudlift_version()
                else:
                    log_warning("Changes aborted.")
        except ClientError:
            raise UnrecoverableException("Unable to fetch environment configuration from DynamoDB.")

    def _set_config(self, config):
        '''
            Set configuration in DynamoDB
        '''
        self._validate_changes(config)
        config['cloudlift_version'] = VERSION
        sns_arn = config[self.environment]['environment']['notifications_arn']
        check_sns_topic_exists(sns_arn, self.environment)

        try:
            configuration_response = self.table.update_item(
                TableName=ENVIRONMENT_CONFIGURATION_TABLE,
                Key={
                    'environment': self.environment
                },
                UpdateExpression='SET configuration = :configuration',
                ExpressionAttributeValues={
                    ':configuration': config
                },
                ReturnValues="UPDATED_NEW"
            )
            return configuration_response
        except ClientError:
            raise UnrecoverableException("Unable to store environment configuration in DynamoDB.")
        pass

    def update_cloudlift_version(self):
        '''
            Updates cloudlift version in service configuration
        '''
        print(f"setting cloudlift version to {VERSION}")
        config = self.get_config(VERSION)
        self._set_config(config)

    def _validate_changes(self, configuration):
        log_bold("\nValidating schema..")
        # TODO: add cidr etc validation
        schema = {
            # "$schema": "http://json-schema.org/draft-04/schema#",
            "title": "configuration",
            "type": "object",
            "properties": {
                self.environment: {
                    "type": "object",
                    "properties": {
                        "cluster": {
                            "type": "object",
                            "properties": {
                                "min_instances": {"type": "integer"},
                                "max_instances": {"type": "integer"},
                                "spot_min_instances": {"type": "integer"},
                                "spot_max_instances": {"type": "integer"},
                                "instance_type": {"type": "string"},
                                "key_name": {"type": "string"},
                                "allocation_strategy": {"type": "string"},
                                "spot_instance_pools": {"type": "integer"},
                                "ecs_instance_default_lifecycle_type": {"type": "string"}
                            },
                            "required": [
                                "min_instances",
                                "max_instances",
                                "instance_type",
                                "key_name"
                            ]
                        },
                        "environment": {
                            "type": "object",
                            "properties": {
                                "notifications_arn": {"type": "string"},
                                "ssl_certificate_arn": {"type": "string"}
                            },
                            "required": [
                                "notifications_arn",
                                "ssl_certificate_arn"
                            ]
                        },
                        "region": {"type": "string"},
                        "vpc": {
                            "type": "object",
                            "properties": {
                                "cidr": {
                                    "type": "string"
                                },
                                "nat-gateway": {
                                    "type": "object",
                                    "properties": {
                                        "elastic-ip-allocation-id": {
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "elastic-ip-allocation-id"
                                    ]
                                },
                                "subnets": {
                                    "type": "object",
                                    "properties": {
                                        "private": {
                                            "type": "object",
                                            "properties": {
                                                "subnet-1": {
                                                    "type": "object",
                                                    "properties": {
                                                        "cidr": {
                                                            "type": "string"
                                                        }
                                                    },
                                                    "required": [
                                                        "cidr"
                                                    ]
                                                },
                                                "subnet-2": {
                                                    "type": "object",
                                                    "properties": {
                                                        "cidr": {
                                                            "type": "string"
                                                        }
                                                    },
                                                    "required": [
                                                        "cidr"
                                                    ]
                                                }
                                            },
                                            "required": [
                                                "subnet-1",
                                                "subnet-2"
                                            ]
                                        },
                                        "public": {
                                            "type": "object",
                                            "properties": {
                                                "subnet-1": {
                                                    "type": "object",
                                                    "properties": {
                                                        "cidr": {
                                                            "type": "string"
                                                        }
                                                    },
                                                    "required": [
                                                        "cidr"
                                                    ]
                                                },
                                                "subnet-2": {
                                                    "type": "object",
                                                    "properties": {
                                                        "cidr": {
                                                            "type": "string"
                                                        }
                                                    },
                                                    "required": [
                                                        "cidr"
                                                    ]
                                                }
                                            },
                                            "required": [
                                                "subnet-1",
                                                "subnet-2"
                                            ]
                                        }
                                    },
                                    "required": [
                                        "private",
                                        "public"
                                    ]
                                }
                            },
                            "required": [
                                "cidr",
                                "nat-gateway",
                                "subnets"
                            ]
                        },
                        "service_defaults": {
                            "type": "object",
                            "properties": {
                                "logging": logging_json_schema,
                                "fluentbit_config": {
                                    "type": "object",
                                    "properties": {
                                        "image_uri": {
                                            "type": "string"
                                        },
                                        "env": {
                                            "type": "object",
                                        }
                                    },
                                    "required": ["image_uri"]
                                },
                            }
                        }
                    },
                    "required": [
                        "cluster",
                        "environment",
                        "region",
                        "vpc"
                    ]
                }
            },
            "required": [self.environment]
        }
        try:
            validate(configuration, schema)
        except ValidationError as validation_error:
            log_err("Schema validation failed!")
            error_path = str(".".join(list(validation_error.relative_path)))
            if error_path:
                raise UnrecoverableException(validation_error.message + " in " + error_path)
            else:
                raise UnrecoverableException(validation_error.message)
        log_bold("Schema valid!")
