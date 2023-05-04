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
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher


class ServiceCreator(object):
    '''
        Create and execute CloudFormation template or changeset for existing
        CloudFormation template for ECS service and related dependencies
    '''

    def __init__(self, name, environment):
        self.name = name
        self.environment = environment
        self.stack_name = get_service_stack_name(environment, name)
        self.client = get_client_for('cloudformation', self.environment)
        self.s3client = get_client_for('s3', self.environment)
        self.ecrClient = get_client_for('ecr', self.environment)
        self.bucket_name = 'cloudlift-service-template'
        self.environment_stack = self._get_environment_stack()
        self.existing_events = get_stack_events(self.client, self.stack_name)
        self.service_configuration = ServiceConfiguration(
            self.name,
            self.environment
        )

    def delete_template(self, key=None):
        '''
            Delete CloudFormation Template stored in S3 bucket
        '''
        if key:
            try:
                self.s3client.delete_object(
                    Bucket=self.bucket_name,
                    Key=key,
                )
            except ClientError as boto_client_error:
                print(f"Error deleting s3 key: {key}")
                raise boto_client_error

    def create(self):
        '''
            Create and execute CloudFormation template for ECS service
            and related dependencies
        '''
        log_bold("Initiating service creation")
        self.service_configuration.edit_config()

        template_generator = ServiceTemplateGenerator(
            self.service_configuration,
            self.environment_stack
        )
        service_template_body, template_source, key = template_generator.generate_service()

        try:
            if template_source == 'TemplateBody':
                self.client.create_stack(
                    StackName=self.stack_name,
                    TemplateBody=service_template_body,
                    Parameters=[{
                        'ParameterKey': 'Environment',
                        'ParameterValue': self.environment,
                    }],
                    OnFailure='DO_NOTHING',
                    Capabilities=['CAPABILITY_NAMED_IAM'],
                )
            elif template_source == 'TemplateURL':
                self.client.create_stack(
                    StackName=self.stack_name,
                    TemplateURL=service_template_body,
                    Parameters=[{
                        'ParameterKey': 'Environment',
                        'ParameterValue': self.environment,
                    }],
                    OnFailure='DO_NOTHING',
                    Capabilities=['CAPABILITY_NAMED_IAM'],
                )
            log_bold("Submitted to cloudformation. Checking progress...")
            self.delete_template(key)
            self._print_progress()
        except ClientError as boto_client_error:
            self.delete_template(key)
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
        self.service_update_preflight_checks()
        self.service_configuration.edit_config()
        try:
            template_generator = ServiceTemplateGenerator(
                self.service_configuration,
                self.environment_stack
            )
            service_template_body, template_source, key = template_generator.generate_service()
            change_set = create_change_set(
                self.client,
                service_template_body,
                template_source,
                self.stack_name,
                "",
                self.environment
            )
            if change_set is None:
                self.delete_template(key)
                return
            self.service_configuration.update_cloudlift_version()
            log_bold("Executing changeset. Checking progress...")
            self.client.execute_change_set(
                ChangeSetName=change_set['ChangeSetId']
            )
            self.delete_template(key)
            self._print_progress()
        except ClientError as exc:
            self.delete_template(key)
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

    def service_update_preflight_checks(self):
        # If the current deployment is considered dirty, make sure that an image tagged as 'master' is uploaded to ECR otherwise on service update, the service will try to use an image tagged as 'master' which does not exist
        current_version = ServiceInformationFetcher(
            self.name, self.environment).get_current_version(skip_master_reset=True)
        if current_version == 'dirty':
            repo_name = self.name + '-repo'
            res = self.ecrClient.batch_get_image(repositoryName=repo_name, imageIds=[{'imageTag': 'master'}])
            if res['images'] == []:
                raise UnrecoverableException("Current deployment is dirty. Please push an image tagged as 'master' to ECR.")