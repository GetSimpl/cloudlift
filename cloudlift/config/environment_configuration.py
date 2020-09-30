"""
This module handles global cloudlift configuration that is custom to
the organization using cloudlift
"""
import ipaddress
import json

import boto3
import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit, prompt
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from cloudlift.exceptions import UnrecoverableException
from cloudlift.config import DecimalEncoder, print_json_changes
from cloudlift.config.dynamodb_config import DynamodbConfig
from cloudlift.config.logging import log_bold, log_err, log_warning

ENVIRONMENT_CONFIGURATION_TABLE = 'environment_configurations'


class EnvironmentConfiguration(DynamodbConfig):

    def __init__(self, environment=None):
        self.environment = environment
        super(EnvironmentConfiguration, self).__init__(ENVIRONMENT_CONFIGURATION_TABLE, [('environment', self.environment)])

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

    def get_config(self):
        try:
            return self.get_config_in_db()
        except KeyError:
            raise UnrecoverableException("Environment configuration not found. Does this environment exist?")

    def _env_config_exists(self):
        response = self.table.get_item(
            Key={
                'environment': self.environment,
            }
        )
        return response.get('Item') is not None

    def _create_vpc_config(self):
        if confirm("Create a new VPC?"):
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
            return {
                "create_new": True,
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
            }
        else:
            vpc_id = prompt("VPC ID")
            private_subnet_count = prompt("No of private subnets in the VPC", default=2)
            private_subnet_ids = [prompt("Private Subnet {} ID".format(idx)) for idx in
                                   range(1, private_subnet_count + 1)]
            public_subnet_count = prompt("No of public subnets in the VPC", default=2)
            public_subnet_ids = [prompt("Public Subnet {} ID".format(idx)) for idx in
                                  range(1, public_subnet_count + 1)]
            return {
                "create_new": False,
                "id": vpc_id,
                "subnets": {
                    "public": {
                        "subnet-{}".format(idx + 1): {
                            "id": public_subnet_ids[idx]
                        } for idx in range(public_subnet_count)
                    },
                    "private": {
                        "subnet-{}".format(idx + 1): {
                            "id": private_subnet_ids[idx]
                        } for idx in range(private_subnet_count)
                    },
                }
            }

    def _create_config(self):
        log_warning(
            "\nConfiguration for this environment was not found in DynamoDB.\
            \nInitiating prompts for setting up configuration.\
            \nIf this environment was previously configured, please ensure\
            \ndefault region is the same as previously used. Otherwise, use\
            \nthe same configuration.\n"
        )
        region = prompt("AWS region for environment", default='ap-south-1')
        vpc_config = self._create_vpc_config()
        cluster_min_instances = prompt("Min instances in cluster", default=1)
        cluster_max_instances = prompt("Max instances in cluster", default=5)
        cluster_instance_type = prompt("Instance type", default='m5.xlarge')
        key_name = prompt("SSH key name")
        notifications_arn = prompt("Notification SNS ARN")
        ssl_certificate_arn = prompt("SSL certificate ARN")
        environment_configuration = {
            self.environment: {
                "region": region,
                "vpc": vpc_config,
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
            raise UnrecoverableException("Unable to fetch environment configuration from DynamoDB.")

    def _set_config(self, config):
        '''
            Set configuration in DynamoDB
        '''
        self.set_config_in_db(config)

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
                            "oneOf": [
                                {
                                    "properties": {
                                        "create_new": {
                                            "enum": [True]
                                        },
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
                                    }
                                },
                                {
                                    "properties": {
                                        "create_new": {
                                            "enum": [False]
                                        },
                                        "subnets": {
                                            "type": "object",
                                            "properties": {
                                                "private": {
                                                    "type": "object",
                                                    "patternProperties": {
                                                        "^subnet-[0-9]$": {
                                                            "type": "object",
                                                            "properties": {
                                                                "id": {
                                                                    "type": "string"
                                                                }
                                                            },
                                                            "required": [
                                                                "id"
                                                            ]
                                                        },
                                                    },
                                                    "additionalProperties": False,
                                                    "maxProperties": 5,
                                                    "minProperties": 1
                                                },
                                                "public": {
                                                    "type": "object",
                                                    "patternProperties": {
                                                        "^subnet-[0-9]$": {
                                                            "type": "object",
                                                            "properties": {
                                                                "id": {
                                                                    "type": "string"
                                                                }
                                                            },
                                                            "required": [
                                                                "id"
                                                            ]
                                                        },
                                                    },
                                                    "additionalProperties": False,
                                                    "maxProperties": 5,
                                                    "minProperties": 1
                                                }
                                            },
                                            "required": [
                                                "private",
                                                "public"
                                            ]
                                        }
                                    }
                                }
                            ],
                            "required": [
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
