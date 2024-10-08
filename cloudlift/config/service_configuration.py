'''
This module abstracts implementation of storing, editing and
retrieving service configuration.
'''

import dictdiffer
from botocore.exceptions import ClientError
from click import confirm, edit, prompt
from cloudlift.exceptions import UnrecoverableException
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from stringcase import pascalcase

from cloudlift.config import  print_json_changes, get_resource_for
# import config.mfa as mfa
from cloudlift.config.logging import log_bold, log_err, log_warning
from cloudlift.version import VERSION
from cloudlift.config.dynamodb_configuration import DynamodbConfiguration
from cloudlift.config.pre_flight import check_sns_topic_exists
from cloudlift.config.environment_configuration import EnvironmentConfiguration
from cloudlift.constants import FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME, logging_json_schema
from cloudlift.config.utils import ConfigUtils

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

        self.masked_config_keys = {}
        self.config_utils = ConfigUtils(changes_validation_function=self._validate_changes)
        self.environment_configuration = EnvironmentConfiguration(self.environment).get_config().get(self.environment, {})
        self.service_defaults = self.environment_configuration.get('service_defaults', {})

    def edit_config(self):
        '''
            Open editor to update configuration
        '''

        try:
            from cloudlift.version import VERSION
            current_configuration = self.get_config(VERSION)

            current_configuration, _ = self._mask_config_keys(current_configuration, ["depends_on", "sidecars"])
            updated_configuration = self.config_utils.fault_tolerant_edit_config(current_configuration=current_configuration, inject_version=True)

            if updated_configuration is None:
                self.set_config(current_configuration)
                if self.new_service:
                    log_warning("Using default configuration.")
            else:
                differences = list(dictdiffer.diff(
                    current_configuration,
                    updated_configuration
                ))
                if not differences:
                    log_warning("No changes made.")
                else:
                    print_json_changes(differences)
                    if confirm('Do you want update the config?'):
                        updated_configuration = self._unmask_config_keys(updated_configuration)
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

        # inject fluentbit sidecars if needed
        if config.get('services'):
            for service_name, service_configuration in config.get('services').items():
                config['services'][service_name] = self._inject_fluentbit_sidecar(service_configuration)
        
        config = self._inject_alb_mode(config)

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

    def _inject_alb_mode(self, config: dict) -> dict:
        """
        Adds `alb_mode` to the `http_interface` of each service from service_defaults of
        environment configuration if not already present.
        """
        services = config.get("services", {})

        # Falls back to 'dedicated' if not present in service_defaults
        default_alb_mode = self.service_defaults.get("alb_mode", "dedicated")

        for _service_name, service_configuration in services.items():
            if "http_interface" in service_configuration:
                http_interface = service_configuration.get("http_interface")
                if "alb_mode" not in http_interface:
                    log_warning(f"'alb_mode' not found in 'http_interface'. Using environment default: '{default_alb_mode}'")
                    http_interface["alb_mode"] = default_alb_mode
        return config

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
                        },
                        "alb_mode": {
                            "type": "string",
                            "pattern": "^(cluster|dedicated)$"
                        },
                        "hostnames": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                # Regex for FQDN: https://stackoverflow.com/a/20204811/9716730
                                "pattern": "(?=^.{4,253}$)(^((?!-)[a-zA-Z0-9-]{1,63}(?<!-)\.)+[a-zA-Z]{2,63}$)"
                            },
                            "minItems": 1,
                            "maxItems": 5
                        }
                    },
                    "required": [
                        "internal",
                        "restrict_access_to",
                        "container_port",
                        "hostnames"
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
                    "efs_id": {"type": "string"},
                    "efs_directory_path": {"type": "string"},
                    "container_path": {"type": "string"}
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
                },
                "spot_deployment": {
                    "type": "boolean"
                },
                "logging": logging_json_schema,
                "disable_service_alarms": {
                    "type": "boolean"
                },
                "depends_on": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {    
                            "container_name": {"type": "string"},
                            "condition": {"type": "string", "enum": ["START", "COMPLETE", "SUCCESS", "HEALTHY"]}
                            }
                    }
                },
                "sidecars": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                # convention: sidecar name ends with -sidecar
                                "pattern": ".*-sidecar$"
                                },
                            "image_uri": {"type": "string"},
                            "command": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "null"}
                                ]
                            },
                            "logging": logging_json_schema,
                            "memory_reservation": {
                                "type": "number",
                                "minimum": 10,
                                "maximum": 30000
                            },
                            "env": {
                                "type": "object"
                            },
                            "essential": {"type": "boolean"},
                            "health_check": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                        },
                                    "interval": {"type": "number"},
                                    "timeout": {"type": "number"},
                                    "retries": {"type": "number"},
                                    "start_period": {"type": "number"}
                                },
                                "required": ["command"]
                            }
                        },
                        "required": ["name", "image_uri", "memory_reservation", "essential"]
                    }
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
            for _, service_configuration in configuration.get('services').items():
                for sidecar in service_configuration.get('sidecars', []):
                    if sidecar.get('name') == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME and sidecar.get('log_driver') == 'awsfirelens':
                        raise UnrecoverableException("Set logging to 'awslogs' or 'null' for fluentbit firelens sidecar when using 'awsfirelens' for main container logging.")
            validate(configuration, schema)
        except ValidationError as validation_error:
            log_err("Schema validation failed!")
            if validation_error.relative_path:
                path_parts = []
                for item in validation_error.relative_path:
                    # casting to string to handle integer keys, else str.join() will fail
                    path_parts.append(str(item))
                relative_path = ".".join(path_parts)
                raise UnrecoverableException(f"{validation_error.message} in {relative_path}")
            else:
                raise UnrecoverableException(validation_error.message)
        log_bold("Schema valid!")

    def _default_service_configuration(self):
        default_alb_mode = self.service_defaults.get('alb_mode', 'dedicated')
        return {
            'notifications_arn': None,
            'services': {
                pascalcase(self.service_name): {
                    'http_interface': {
                        'internal': True,
                        'restrict_access_to': ['0.0.0.0/0'],
                        'container_port': 80,
                        'health_check_path': '/elb-check',
                        'alb_mode': default_alb_mode,
                        'hostnames': [],
                    },
                    'memory_reservation': 250,
                    'command': None,
                    'spot_deployment': False
                }
            }
        }

    def _mask_config_keys(self, configuration, keys_to_mask):
        for service_name, service_data in configuration["services"].items():
            if service_name not in self.masked_config_keys:
                self.masked_config_keys[service_name] = {}
            for key in keys_to_mask:
                if key in service_data:
                    self.masked_config_keys[service_name][key] = service_data.pop(key)
        return configuration, self.masked_config_keys

    def _unmask_config_keys(self, configuration):
        for service_name, masked_keys in self.masked_config_keys.items():
            if service_name in configuration["services"]:
                service_data = configuration["services"][service_name]
                for key, value in masked_keys.items():
                    service_data[key] = value
        return configuration
    
    def _inject_fluentbit_sidecar(self, service_configuration):
        '''
        Inject fluentbit sidecar in service configuration
        '''
        try:
            logging_driver = service_configuration.get('logging') or self.service_defaults.get('logging')

            # If 'logging' is explicitly set to None in service_configuration, override with None
            if 'logging' in service_configuration and service_configuration.get('logging') is None:
                logging_driver = None

            if logging_driver is None or logging_driver != 'awsfirelens':
                if service_configuration.get('sidecars'):
                    # if logging is not set to awsfirelens, remove the fluentbit sidecar container configuration if present
                    sidecars = service_configuration.get('sidecars')
                    other_sidecars = [sidecar for sidecar in sidecars if sidecar.get('name') != FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME]
                    # remove the key 'sidecars' if it's an empty list
                    if len(other_sidecars) == 0:
                        del service_configuration['sidecars']
                    else:
                        service_configuration['sidecars'] = other_sidecars
                
                if service_configuration.get('depends_on'):
                    depends_on = service_configuration.get('depends_on')
                    depends_on = [depend_on for depend_on in depends_on if depend_on.get('container_name') != FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME]
                    if len(depends_on) == 0:
                        del service_configuration['depends_on']
                    else:
                        service_configuration['depends_on'] = depends_on
                return service_configuration
            
            if any(sidecar.get('name') == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME for sidecar in service_configuration.get('sidecars', [])):
                return service_configuration
            
            log_bold('Logging driver found: awsfirelens')
            
            sidecars = service_configuration.get('sidecars', [])

            default_fluentbit_config = self.service_defaults.get('fluentbit_config', {})
            
            if default_fluentbit_config == {}:
                log_warning('Default fluentbit configuration not found in environment configuration. To avoid entering fluentbit image URI manually repeatedly, add it to environment configuration.')
            
            fluentbit_image_uri = default_fluentbit_config.get('image_uri')
            if fluentbit_image_uri:
                log_bold('Using fluentbit image URI from environment configuration: ' + fluentbit_image_uri)
            else:
                fluentbit_image_uri = prompt('Enter fluentbit image URI', confirmation_prompt=True, type=str)

            if not service_configuration.get('depends_on') or not any(depends_on.get('container_name') == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME for depends_on in service_configuration['depends_on']):
                service_configuration['depends_on'] = service_configuration.get('depends_on', []) + [{
                    'container_name': FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME,
                    'condition': 'START'
                }]

            # Check if no sidecar is present with name FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
            if not any(sidecar.get('name') == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME for sidecar in sidecars):
                env_vars = default_fluentbit_config.get('env', {})

                env_vars.setdefault('delivery_stream', f"{self.environment}-{self.service_name}")
                env_vars.setdefault('CL_ENVIRONMENT', self.environment)
                env_vars.setdefault('CL_SERVICE', self.service_name)


                sidecars.append({
                    'name': FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME,
                    'memory_reservation': 100,
                    'essential': True,
                    'image_uri': fluentbit_image_uri,
                    'env': env_vars,
                    'logging': 'awslogs',
                    'health_check': {
                        'command': ['CMD-SHELL', 'curl -f -s http://localhost:2020/api/v1/health || exit 1'],
                        'interval': 5,
                        'timeout': 2,
                        'retries': 3,
                    },
                })

            service_configuration['sidecars'] = sidecars
            return service_configuration

        except Exception as e:
            raise UnrecoverableException(f'Error while injecting fluentbit sidecar: {e}')
