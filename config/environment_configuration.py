"""
This module handles global cloudlift configuration that is custom to
the organization using cloudlift
"""

import json

import boto3
import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit, prompt
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from config.decimal_encoder import DecimalEncoder
from config.diff import print_json_changes
# import config.mfa as mfa
from deployment.logging import log_bold, log_err, log_warning

ENVIRONMENT_CONFIGURATION_TABLE = 'environment_configurations'

class EnvironmentConfiguration(object):
    '''
        Handles configuration in DynamoDB for cloudlift
    '''

    def __init__(self, environment=None):
        self.environment = environment

        session = boto3.session.Session()
        self.dynamodb = session.resource('dynamodb')
        self.table = self._get_table()

    def get_config(self):
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
            return configuration_response['Item']['configuration']
        except ClientError:
            log_err("Unable to fetch configuration from DynamoDB.")
            exit(1)
        except KeyError:
            log_err("Configuration not found.")
            exit(1)

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

    def _get_table(self):
        dynamodb_client = boto3.session.Session().client('dynamodb')
        table_names = dynamodb_client.list_tables()['TableNames']
        if ENVIRONMENT_CONFIGURATION_TABLE not in table_names:
            log_warning("Could not find configuration table, creating one..")
            self._create_configuration_table()
        return self.dynamodb.Table(ENVIRONMENT_CONFIGURATION_TABLE)

    def _create_configuration_table(self):
        self.dynamodb.create_table(
            TableName=ENVIRONMENT_CONFIGURATION_TABLE,
            KeySchema=[
                {
                    'AttributeName': 'environment',
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'environment',
                    'AttributeType': 'S'
                }
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        log_bold("Configuration table created!")

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
        vpc_cidr = prompt("VPC CIDR", default='10.10.10.10/16')
        nat_eip = prompt("Allocation ID Elastic IP for NAT")
        public_subnet_1_cidr = prompt(
            "Public Subnet 1 CIDR", default='10.10.0.0/22')
        public_subnet_2_cidr = prompt(
            "Public Subnet 2 CIDR", default='10.10.4.0/22')
        private_subnet_1_cidr = prompt(
            "Private Subnet 1 CIDR", default='10.10.8.0/22')
        private_subnet_2_cidr = prompt(
            "Private Subnet 2 CIDR", default='10.10.12.0/22')
        cluster_min_instances = prompt("Min instances in cluster", default=1)
        cluster_max_instances = prompt("Max instances in cluster", default=5)
        cluster_instance_type = prompt("Instance type", default='m5.xlarge')
        key_name = prompt("SSH key name")
        notifications_arn = prompt("Notification SNS ARN")
        ssl_certificate_arn = prompt("SSL certificate ARN")
        environment_configuration = {
            self.environment: {
                "region": region,
                "vpc": {
                    "cidr": vpc_cidr,
                    "nat-gateway": {
                        "elastic-ip-allocation-id": nat_eip
                    },
                    "subnets": {
                        "public": {
                            "subnet-1": {
                                "cidr": public_subnet_1_cidr
                            },
                            "subnet-2": {
                                "cidr": public_subnet_2_cidr
                            }
                        },
                        "private": {
                            "subnet-1": {
                                "cidr": private_subnet_1_cidr
                            },
                            "subnet-2": {
                                "cidr": private_subnet_2_cidr
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
                }
            }
        }
        self._set_config(environment_configuration)
        pass

    def _edit_config(self):
        '''
            Open editor to update configuration
        '''

        try:
            current_configuration = self.get_config()

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
                else:
                    print_json_changes(differences)
                    if confirm('Do you want update the config?'):
                        self._set_config(updated_configuration)
                    else:
                        log_warning("Changes aborted.")
        except ClientError:
            log_err("Unable to fetch configuration from DynamoDB.")
            exit(1)

    def _set_config(self, config):
        '''
            Set configuration in DynamoDB
        '''
        self._validate_changes(config)
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
            log_err("Unable to store configuration in DynamoDB.")
            exit(1)
        pass

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
                log_err(validation_error.message + " in " + error_path)
            else:
                log_err(validation_error.message)
            exit(0)
        log_bold("Schema valid!")
