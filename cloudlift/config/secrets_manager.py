from cloudlift.config import get_client_for
from cloudlift.config.logging import log
import json

_secret_manager_cache = {}


def set_secrets_manager_config(env, secret_name, config):
    client = get_client_for('secretsmanager', env)
    secret_string = json.dumps(config)
    try:
        client.put_secret_value(SecretId=secret_name, SecretString=secret_string)
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(Name=secret_name, SecretString=secret_string)
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
