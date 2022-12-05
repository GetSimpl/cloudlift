'''
This module abstracts implementation of storing, editing and
retrieving service configuration.
'''

import json
from time import sleep

import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit
from cloudlift.exceptions import UnrecoverableException
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from stringcase import pascalcase

from cloudlift.config import DecimalEncoder, print_json_changes, get_resource_for
# import config.mfa as mfa
from cloudlift.config.logging import log_bold, log_err, log_warning, log
from cloudlift.version import VERSION
from cloudlift.config.dynamodb_configuration import DynamodbConfiguration
from cloudlift.config.pre_flight import check_sns_topic_exists


SERVICE_CONFIGURATION_TABLE = 'service_configurations'

class ServiceConfiguration(object):
    '''
        Handles configuration in DynamoDB for services
    '''

    def __init__(self, service_name, environment):
        self.service_name = service_name
        self.environment = environment
        self.new_service = False
        # TODO: Use the below two lines when all parameter store actions
        # require MFA
        #
        # mfa_region = get_region_for_environment(environment)
        # mfa_session = mfa.get_mfa_session(mfa_region)
        # ssm_client = mfa_session.client('ssm')
        self.dynamodb_resource = get_resource_for('dynamodb',environment)
        self.table = DynamodbConfiguration(SERVICE_CONFIGURATION_TABLE, [
            ('service_name', self.service_name), ('environment', self.environment)])._get_table()

    def edit_config(self):
        '''
            Open editor to update configuration
        '''

        try:
            from cloudlift.version import VERSION
            current_configuration = self.get_config(VERSION)

            updated_configuration = edit(
                json.dumps(
                    current_configuration,
                    indent=4,
                    sort_keys=True,
                    cls=DecimalEncoder
                )
            )

            if updated_configuration is None:
                if self.new_service:
                    self.set_config(current_configuration)
                    log_warning("Using default configuration.")
                else:
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
                        self.set_config(updated_configuration)
                    else:
                        log_warning("Changes aborted.")
        except ClientError:
            raise UnrecoverableException("Unable to fetch service configuration from DynamoDB.")

    def get_config(self, cloudlift_version):
        '''
            Get configuration from DynamoDB
        '''

        try:
            configuration_response = self.table.get_item(
                Key={
                    'service_name': self.service_name,
                    'environment': self.environment
                },
                ConsistentRead=True,
                AttributesToGet=[
                    'configuration'
                ]
            )
            if 'Item' in configuration_response:
                existing_configuration = configuration_response['Item']['configuration']

                from distutils.version import LooseVersion
                previous_cloudlift_version = existing_configuration.pop("cloudlift_version", None)
                if LooseVersion(cloudlift_version) < LooseVersion(previous_cloudlift_version):
                    raise UnrecoverableException(f'Cloudlift Version {previous_cloudlift_version} was used to '
                                                 f'create this service. You are using version {cloudlift_version}, '
                                                 f'which is older and can cause corruption. Please upgrade to at least '
                                                 f'version {previous_cloudlift_version} to proceed.\n\nUpgrade to the '
                                                 f'latest version (Recommended):\n'
                                                 f'\tpip install -U cloudlift\n\nOR\n\nUpgrade to a compatible version:\n'
                                                 f'\tpip install -U cloudlift=={previous_cloudlift_version}')
            else:
                existing_configuration = self._default_service_configuration()
                self.new_service = True

            return existing_configuration
        except ClientError:
            raise UnrecoverableException("Unable to fetch service configuration from DynamoDB.")

    def set_config(self, config):
        '''
            Set configuration in DynamoDB
        '''
        config['cloudlift_version'] = VERSION
        self._validate_changes(config)
        check_sns_topic_exists(config['notifications_arn'], self.environment)
        try:
            configuration_response = self.table.update_item(
                TableName=SERVICE_CONFIGURATION_TABLE,
                Key={
                    'service_name': self.service_name,
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
            raise UnrecoverableException("Unable to store service configuration in DynamoDB.")

    def update_cloudlift_version(self):
        '''
            Updates cloudlift version in service configuration
        '''
        config = self.get_config(VERSION)
        self.set_config(config)

    def _validate_changes(self, configuration):
        service_schema = {
            "title": "service",
            "type": "object",
            "properties": {
                "http_interface": {
                    "type": "object",
                    "properties": {
                        "internal": {
                            "type": "boolean"
                        },
                        "restrict_access_to": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        },
                        "container_port": {
                            "type": "number"
                        },
                        "health_check_path": {
                            "type": "string",
                            "pattern": "^\/.*$"
                        }
                    },
                    "required": [
                        "internal",
                        "restrict_access_to",
                        "container_port"
                    ]
                },
                "custom_metrics": {
                    "type": "object",
                    "properties": {
                        "metrics_port" : {"type": "string"},
                        "metrics_path": {"type": "string"}
                    }
                },
                "volume": {
                    "type": "object",
                    "properties": {
                        "efs_id" : {"type": "string"},
                        "efs_directory_path" : {"type": "string"},
                        "container_path" : {"type": "string"}
                    }
                },
                "memory_reservation": {
                    "type": "number",
                    "minimum": 10,
                    "maximum": 30000
                },
                "fargate": {
                    "type": "object",
                    "properties": {
                        "cpu": {
                            "type": "number",
                            "minimum": 256,
                            "maximum": 4096
                        },
                        "memory": {
                            "type": "number",
                            "minimum": 512,
                            "maximum": 30720
                        }
                    }
                },
                "command": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "null"}
                    ]
                }
            },
            "required": ["memory_reservation", "command"]
        }
        schema = {
            # "$schema": "http://json-schema.org/draft-04/schema#",
            "title": "configuration",
            "type": "object",
            "properties": {
                "notifications_arn": {
                    "type": "string"
                },
                "services": {
                    "type": "object",
                    "patternProperties": {
                        "^[a-zA-Z]+$": service_schema
                    }
                },
                "cloudlift_version": {
                    "type": "string"
                }
            },
            "required": ["cloudlift_version", "services", "notifications_arn"]
        }
        try:
            validate(configuration, schema)
        except ValidationError as validation_error:
            if validation_error.relative_path:
                raise UnrecoverableException(validation_error.message + " in " +
                        str(".".join(list(validation_error.relative_path))))
            else:
                raise UnrecoverableException(validation_error.message)
        log_bold("Schema valid!")

    def _default_service_configuration(self):
        return {
            u'notifications_arn': None,
            u'services': {
                pascalcase(self.service_name): {
                    u'http_interface': {
                        u'internal': False,
                        u'restrict_access_to': [u'0.0.0.0/0'],
                        u'container_port': 80,
                        u'health_check_path': u'/elb-check'
                    },
                    u'memory_reservation': 250,
                    u'command': None
                }
            }
        }
