'''
This module abstracts implementation of storing, editing and
retrieving service configuration.
'''

import json

import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from stringcase import pascalcase

from config.decimal_encoder import DecimalEncoder
from config.diff import print_json_changes
# import config.mfa as mfa
from config.region import get_resource_for
from deployment.logging import log_bold, log_err, log_warning
from version import VERSION

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
        self.table = get_resource_for(
            'dynamodb',
            environment
        ).Table(SERVICE_CONFIGURATION_TABLE)

    def edit_config(self):
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
            log_err("Unable to fetch configuration from DynamoDB.")
            exit(1)

    def get_config(self):
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
            else:
                existing_configuration = self._default_service_configuration()
                self.new_service = True

            existing_configuration.pop("cloudlift_version", None)
            return existing_configuration
        except ClientError:
            log_err("Unable to fetch configuration from DynamoDB.")
            exit(1)

    def set_config(self, config):
        '''
            Set configuration in DynamoDB
        '''
        config['cloudlift_version'] = VERSION
        self._validate_changes(config)
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
            log_err("Unable to store configuration in DynamoDB.")
            exit(1)

    def update_cloudlift_version(self):
        '''
            Updates cloudlift version in service configuration
        '''
        config = self.get_config()
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
                        }
                    },
                    "required": [
                        "internal",
                        "restrict_access_to",
                        "container_port"
                    ]
                },
                "memory_reservation": {
                    "type": "number",
                    "minimum": 1000,
                    "maximum": 8000
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
            "required": ["cloudlift_version", "services"]
        }
        try:
            validate(configuration, schema)
        except ValidationError as validation_error:
            log_err(validation_error.message + " in " +
                    str(".".join(list(validation_error.relative_path))))
            exit(0)
        log_bold("Schema valid!")

    def _default_service_configuration(self):
        return {
            u'services': {
                pascalcase(self.service_name): {
                    u'http_interface': {
                        u'internal': False,
                        u'restrict_access_to': [u'0.0.0.0/0'],
                        u'container_port': 80
                    },
                    u'memory_reservation': 1000,
                    u'command': None
                }
            }
        }
