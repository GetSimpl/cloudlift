"""
This module handles global cloudlift configuration that is custom to
the organization using cloudlift
"""
import ipaddress
import json
from distutils.version import LooseVersion

import boto3
import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit, prompt
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from cloudlift.version import VERSION
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config import DecimalEncoder, print_json_changes
from cloudlift.config.dynamodb_configuration import DynamodbConfiguration
from cloudlift.config.pre_flight import check_sns_topic_exists

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
                                             f'create this service. You are using version {cloudlift_version}, '
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
        vpc_cidr = ipaddress.IPv4Network(prompt("VPC CIDR", default='10.10.10.10/16'))
        nat_eip = prompt("Allocation ID Elastic IP for NAT")
        public_subnet_1_cidr = prompt(
            "Public Subnet 1 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[0])
        public_subnet_2_cidr = prompt(
            "Public Subnet 2 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[1])
        private_subnet_1_cidr = prompt(
            "Private Subnet 1 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[2])
        private_subnet_2_cidr = prompt(
            "Private Subnet 2 CIDR", default=list(vpc_cidr.subnets(new_prefix=22))[3])
        cluster_min_instances = prompt("Min instances in cluster", default=1)
        cluster_max_instances = prompt("Max instances in cluster", default=5)
        cluster_instance_type = prompt("Instance type", default='m5.xlarge')
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
                "min_instances": cluster_min_instances,
                "max_instances": cluster_max_instances,
                "instance_type": cluster_instance_type,
                "key_name": key_name
            },
            "environment": {
                "notifications_arn": notifications_arn,
                "ssl_certificate_arn": ssl_certificate_arn
            },
        }, 'cloudlift_version': VERSION}
        self._set_config(environment_configuration)
        pass

    def _edit_config(self):
        '''
            Open editor to update configuration
        '''
        try:
            current_configuration = self.get_config()
            previous_cloudlift_version = current_configuration.pop('cloudlift_version', None)
            updated_configuration = edit(
                json.dumps(
                    current_configuration,
                    indent=4,
                    sort_keys=True,
                    cls=DecimalEncoder
                )
            )

            if updated_configuration is None:
                log_warning("No changes made.")
            else:
                updated_configuration = json.loads(updated_configuration)
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
                    if confirm('Do you want update the config?'):
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
                                "instance_type": {"type": "string"},
                                "key_name": {"type": "string"},
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
            error_path = str(".".join(list(validation_error.relative_path)))
            if error_path:
                raise UnrecoverableException(validation_error.message + " in " + error_path)
            else:
                raise UnrecoverableException(validation_error.message)
        log_bold("Schema valid!")
