import click
import dictdiffer

from config.diff import print_parameter_changes
from config.parameter_store import ParameterStore
from deployment.deployer import read_config
from deployment.logging import log_warning


def edit_config(name, environment):
    parameter_store = ParameterStore(name, environment)
    env_config_strings = parameter_store.get_existing_config_as_string()
    edited_config_content = click.edit(str(env_config_strings))

    if edited_config_content is None:
        log_warning("No changes made, exiting.")
        exit(0)

    differences = list(dictdiffer.diff(
        read_config(env_config_strings),
        read_config(edited_config_content)
    ))
    if not differences:
        log_warning("No changes made, exiting.")
    else:
        print_parameter_changes(differences)
        if click.confirm('Do you want update the config?'):
            parameter_store.set_config(differences)
        else:
            log_warning("Changes aborted.")
