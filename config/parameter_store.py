import re

import boto3

import config.mfa as mfa
from config.region import get_client_for, get_region_for_environment
from deployment.logging import log_err


class ParameterStore(object):
    def __init__(self, service_name, environment):
        self.service_name = service_name
        self.environment = environment
        self.path_prefix = "/%s/%s/" % (self.environment, self.service_name)
        # TODO: Use the below two lines when all parameter store actions
        # require MFA
        #
        # mfa_region = get_region_for_environment(environment)
        # mfa_session = mfa.get_mfa_session(mfa_region)
        # ssm_client = mfa_session.client('ssm')
        self.client = get_client_for('ssm', environment)

    def get_existing_config_as_string(self):
        environment_configs = self.get_existing_config()
        return '\n'.join('{}={}'.format(key, val) for key, val in sorted(
            environment_configs.items()
        ))

    def get_existing_config(self):
        environment_configs = {}
        next_token = None
        while True:
            if next_token:
                response = self.client.get_parameters_by_path(
                    Path=self.path_prefix,
                    Recursive=False,
                    WithDecryption=True,
                    MaxResults=10,
                    NextToken=next_token
                )
            else:
                response = self.client.get_parameters_by_path(
                    Path=self.path_prefix,
                    Recursive=False,
                    WithDecryption=True,
                    MaxResults=10
                )
            for parameter in response['Parameters']:
                parameter_name = parameter['Name'].split(self.path_prefix)[1]
                environment_configs[parameter_name] = parameter['Value']

            try:
                next_token = response['NextToken']
            except KeyError:
                break
        return environment_configs

    def set_config(self, differences):
        self._validate_changes(differences)
        for parameter_change in differences:
            if parameter_change[0] == 'change':
                response = self.client.put_parameter(
                    Name='%s%s' % (self.path_prefix, parameter_change[1]),
                    Value=parameter_change[2][1],
                    Type='SecureString',
                    KeyId='alias/aws/ssm',
                    Overwrite=True
                )
            elif parameter_change[0] == 'add':
                for added_parameter in parameter_change[2]:
                    response = self.client.put_parameter(
                        Name='%s%s' % (self.path_prefix, added_parameter[0]),
                        Value=added_parameter[1],
                        Type='SecureString',
                        KeyId='alias/aws/ssm',
                        Overwrite=False
                    )
            elif parameter_change[0] == 'remove':
                deleted_parameters = ["%s%s" % (self.path_prefix, item[0]) for item in parameter_change[2]]
                response = self.client.delete_parameters(
                    Names=deleted_parameters
                )

    def _validate_changes(self, differences):
        errors = []
        for parameter_change in differences:
            if parameter_change[0] == 'change':
                if not self._is_a_valid_parameter_key(parameter_change[1]):
                    errors.append("'%s' is not a valid key." % parameter_change[1])
                if not self._is_a_valid_parameter_value(parameter_change[2][1]):
                    errors.append("'%s' is not a valid value for key '%s'" % (parameter_change[2][1],parameter_change[1]))
            elif parameter_change[0] == 'add':
                for added_parameter in parameter_change[2]:
                    if not self._is_a_valid_parameter_key(added_parameter[0]):
                        errors.append("'%s' is not a valid key." % added_parameter[0])
                    if not self._is_a_valid_parameter_value(added_parameter[1]):
                        errors.append("'%s' is not a valid value for key '%s'" % (added_parameter[1],added_parameter[0]))
            elif parameter_change[0] == 'remove':
                # No validation required
                pass
        if errors:
            for error in errors:
                log_err(error)
            exit(1)
        return True

    def _is_a_valid_parameter_key(self, key):
        return bool(re.match(r"^[\w|\.|\-|\/]*$", key))

    def _is_a_valid_parameter_value(self, value):
        return bool(re.match(r"\w", value))
