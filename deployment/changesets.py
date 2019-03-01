import sys
import uuid
from time import sleep

import click

from deployment.logging import log, log_bold, log_err


def create_change_set(client, service_template_body, stack_name,
                      key_name, environment):
    change_set_parameters = [
        {'ParameterKey': 'Environment', 'ParameterValue': environment}
    ]
    if key_name:
        change_set_parameters.append({
            'ParameterKey': 'KeyPair',
            'ParameterValue': key_name
        })
    create_change_set_res = client.create_change_set(
        StackName=stack_name,
        ChangeSetName="cg"+uuid.uuid4().hex,
        TemplateBody=service_template_body,
        Parameters=change_set_parameters,
        Capabilities=['CAPABILITY_NAMED_IAM'],
        ChangeSetType='UPDATE'
    )
    log("Changeset creation initiated. Checking the progress...")
    change_set = client.describe_change_set(
        ChangeSetName=create_change_set_res['Id']
    )
    while change_set['Status'] in ['CREATE_PENDING', 'CREATE_IN_PROGRESS']:
        sleep(1)
        status_string = '\x1b[2K\rChecking changeset status.  Status: ' + \
                        change_set['Status']
        sys.stdout.write(status_string)
        sys.stdout.flush()
        change_set = client.describe_change_set(
            ChangeSetName=create_change_set_res['Id']
        )
    status_string = '\x1b[2K\rChecking changeset status..  Status: ' + \
                    change_set['Status']+'\n'
    sys.stdout.write(status_string)
    if change_set['Status'] == 'FAILED':
        log_err("Changeset creation failed!")
        log_bold(change_set.get(
            'StatusReason',
            "Check AWS console for reason."
        ))
        client.delete_change_set(ChangeSetName=create_change_set_res['Id'])
        exit(0)
    else:
        log_bold("Changeset created.. Following are the changes")
        _print_changes(change_set)
        if click.confirm('Do you want to execute the changeset?'):
            return change_set
        log_bold("Deleting changeset...")
        client.delete_change_set(
            ChangeSetName=create_change_set_res['Id']
        )
        log_bold("Done. Bye!")
        exit(0)


def _print_changes(change_set):
    for change in change_set['Changes']:
        resource_change = change['ResourceChange']
        change_line = click.style(
            resource_change['Action'] + ": " +
            resource_change['LogicalResourceId'] +
            " (" + resource_change['ResourceType'] + "/" +
            resource_change.get('PhysicalResourceId', '--') + ")\n",
            fg='green', bold=True) + \
            click.style("  "+str(resource_change['Details']), fg='green')
        click.echo(change_line)
