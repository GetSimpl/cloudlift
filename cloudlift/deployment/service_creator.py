'''
Create or update ECS service and related dependencies
using CloudFormation templates
'''

from time import sleep

from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException

from cloudlift.config import get_client_for
from cloudlift.config import ServiceConfiguration
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.deployment.changesets import create_change_set
from cloudlift.config.logging import log, log_bold, log_err
from cloudlift.deployment.progress import get_stack_events, print_new_events
from cloudlift.deployment.service_template_generator import ServiceTemplateGenerator
from cloudlift.deployment.cloud_formation_stack import prepare_stack_options_for_template


class ServiceCreator(object):
    '''
        Create and execute CloudFormation template or changeset for existing
        CloudFormation template for ECS service and related dependencies
    '''

    def __init__(self, name, environment, env_sample_file):
        self.name = name
        self.environment = environment
        self.stack_name = get_service_stack_name(environment, name)
        self.client = get_client_for('cloudformation', self.environment)
        self.environment_stack = self._get_environment_stack()
        self.existing_events = get_stack_events(self.client, self.stack_name)
        self.service_configuration = ServiceConfiguration(
            self.name,
            self.environment
        )
        self.env_sample_file = env_sample_file

    def create(self):
        '''
            Create and execute CloudFormation template for ECS service
            and related dependencies
        '''
        log_bold("Initiating service creation")
        self.service_configuration.edit_config()

        template_generator = ServiceTemplateGenerator(
            self.service_configuration,
            self.environment_stack,
            self.env_sample_file,
        )
        service_template_body = template_generator.generate_service()

        try:
            options = prepare_stack_options_for_template(
                service_template_body, self.environment, self.stack_name)
            self.client.create_stack(
                StackName=self.stack_name,
                Parameters=[{
                    'ParameterKey': 'Environment',
                    'ParameterValue': self.environment,
                }],
                OnFailure='DO_NOTHING',
                Capabilities=['CAPABILITY_NAMED_IAM'],
                **options,
            )
            log_bold("Submitted to cloudformation. Checking progress...")
            self._print_progress()
        except ClientError as boto_client_error:
            error_code = boto_client_error.response['Error']['Code']
            if error_code == 'AlreadyExistsException':
                raise UnrecoverableException("Stack " + self.stack_name + " already exists.")
            else:
                raise boto_client_error

    def update(self):
        '''
            Create and execute changeset for existing CloudFormation template
            for ECS service and related dependencies
        '''

        log_bold("Starting to update service")
        self.service_configuration.edit_config()
        try:
            template_generator = ServiceTemplateGenerator(
                self.service_configuration,
                self.environment_stack,
                self.env_sample_file,
            )
            service_template_body = template_generator.generate_service()
            change_set = create_change_set(
                self.client,
                service_template_body,
                self.stack_name,
                None,
                self.environment
            )
            if change_set is None:
                return
            self.service_configuration.update_cloudlift_version()
            log_bold("Executing changeset. Checking progress...")
            self.client.execute_change_set(
                ChangeSetName=change_set['ChangeSetId']
            )
            self._print_progress()
        except ClientError as exc:
            if "No updates are to be performed." in str(exc):
                log_err("No updates are to be performed")
            else:
                raise exc

    def _get_environment_stack(self):
        try:
            log("Looking for " + self.environment + " cluster.")
            environment_stack = self.client.describe_stacks(
                StackName=get_cluster_name(self.environment)
            )['Stacks'][0]
            log_bold(self.environment+" stack found. Using stack with ID: " +
                     environment_stack['StackId'])
        except ClientError:
            raise UnrecoverableException(self.environment + " cluster not found. Create the environment \
cluster using `create_environment` command.")
        return environment_stack

    def _print_progress(self):
        while True:
            response = self.client.describe_stacks(StackName=self.stack_name)
            if "IN_PROGRESS" not in response['Stacks'][0]['StackStatus']:
                break
            all_events = get_stack_events(self.client, self.stack_name)
            print_new_events(all_events, self.existing_events)
            self.existing_events = all_events
            sleep(5)
        final_status = response['Stacks'][0]['StackStatus']
        if "FAIL" in final_status:
            log_err("Finished with status: %s" % (final_status))
        else:
            log_bold("Finished with status: %s" % (final_status))
