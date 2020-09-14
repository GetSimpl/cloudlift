from cloudlift.config import get_client_for
from cloudlift.config.logging import log
import json

_secret_manager_cache = {}


def get_config(secret_name, env):
    if secret_name not in _secret_manager_cache:
        response = get_client_for('secretsmanager', env).get_secret_value(SecretId=secret_name)
        log(f"Fetched config from AWS secrets manager. Version: {response['VersionId']}")
        secret_val = json.loads(response['SecretString'])
        _secret_manager_cache[secret_name] = {k: f"{response['ARN']}:{k}::{response['VersionId']}" for k in secret_val}
    return _secret_manager_cache[secret_name]
