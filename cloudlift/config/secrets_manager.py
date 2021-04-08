from cloudlift.config import get_client_for
from cloudlift.config.logging import log, log_warning
import json
from time import sleep
from cloudlift.exceptions import UnrecoverableException
from cloudlift.utils import wait_until

_secret_manager_cache = {}

SECRETS_MANAGER_CONSISTENCY_CHECK_TIMEOUT_SECONDS = 15


def set_secrets_manager_config(env, secret_name, config):
    client = get_client_for('secretsmanager', env)
    secret_string = json.dumps(config)
    try:
        client.put_secret_value(SecretId=secret_name, SecretString=secret_string)
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(Name=secret_name, SecretString=secret_string)

    def check_consistency(secret_id, expected_configuration):
        try:
            r = client.get_secret_value(SecretId=secret_id)
            value = json.loads(r['SecretString'])
            return expected_configuration == value
        except Exception as e:
            log_warning("secrets_manager consistency failure: {}".format(e))
            return False

    secrets_consistent = wait_until(lambda: check_consistency(secret_name, config),
                                    timeout=SECRETS_MANAGER_CONSISTENCY_CHECK_TIMEOUT_SECONDS, period=1)
    if secrets_consistent:
        log(f'{secret_name} successfully updated')
    else:
        raise UnrecoverableException("Created secrets are not consistent")
    clear_cache()


def get_config(secret_name, env):
    if secret_name not in _secret_manager_cache:
        log(f"Fetching config from AWS secrets manager for secret {secret_name}")
        response = get_client_for('secretsmanager', env).get_secret_value(SecretId=secret_name)
        log(f"Fetched secret {secret_name}. Version: {response['VersionId']}")
        secret_val = json.loads(response['SecretString'])
        _secret_manager_cache[secret_name] = {'secrets': secret_val,
                                              'ARN': f"{response['ARN']}:::{response['VersionId']}"}
    return _secret_manager_cache[secret_name]


def clear_cache():
    global _secret_manager_cache
    _secret_manager_cache = {}
