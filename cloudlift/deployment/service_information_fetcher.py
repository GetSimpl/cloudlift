from re import search

from cloudlift.config import get_client_for
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.config import get_region_for_environment
from cloudlift.config.logging import log, log_warning, log_intent
from cloudlift.deployment.deployer import verify_and_get_secrets_for_all_namespaces
from cloudlift.deployment.ecs import DeployAction, EcsClient
from cloudlift.exceptions import UnrecoverableException


class ServiceInformationFetcher(object):
    def __init__(self, name, environment, service_configuration):
        self.name = name
        self.environment = environment
        self.cluster_name = get_cluster_name(environment)
        self.cfn_client = get_client_for('cloudformation', self.environment)
        self.service_configuration = service_configuration
        self.service_info = {}
        self.init_stack_info()

    def init_stack_info(self):
        stack_name = get_service_stack_name(self.environment, self.name)
        try:
            stack = self.cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]
            self.stack_found = True

            stack_outputs = {output['OutputKey']: output['OutputValue'] for output in stack['Outputs']}

            for service_name, service_config in self.service_configuration.get('services', {}).items():
                service_metadata = dict()

                if "ecs_service_name" in service_config:
                    service_metadata["ecs_service_name"] = service_config.get('ecs_service_name')
                else:
                    service_metadata["ecs_service_name"] = stack_outputs.get(f'{service_name}EcsServiceName')

                service_metadata["secrets_name"] = service_config.get('secrets_name', None)

                self.service_info[service_name] = service_metadata

            self.listener_rules = [resource_summary for resource_summary in (self._get_stack_resource_summaries())
                                   if resource_summary['LogicalResourceId'].endswith('ListenerRule')]
        except Exception as e:
            self.stack_found = False
            log_warning("Could not determine services. Stack not found. Error raised: {}".format(e))


    def get_current_image_uri(self):
        ecr_image_uri = self._fetch_current_image_uri()
        log_intent(f"Currently deployed tag: {ecr_image_uri}")
        return str(ecr_image_uri)

    def get_version(self, print_image=False, print_git=False):
        image = self._fetch_current_image_uri()
        tag = image.split(':').pop()
        if print_image:
            print(image)
            return
        if print_git:
            print(search("^[0-9a-f]{5,40}", tag).group())
            return

        print(tag)

    def _fetch_current_image_uri(self):
        ecs_client = get_client_for('ecs', self.environment)
        if len(self.service_info) < 1:
            raise UnrecoverableException(
                "cannot get running image_uri: no ECS services found")

        ecs_service_name = next(service_info['ecs_service_name'] for service, service_info in self.service_info.items()
                                if service_info.get('ecs_service_name'))

        ecs_services = ecs_client.describe_services(
            cluster=self.cluster_name,
            services=[ecs_service_name],
        )['services']

        if len(ecs_services) < 1:
            raise UnrecoverableException(
                "cannot get running image_uri: no service found.")

        task_definition_arn = ecs_services[0]['taskDefinition']
        task_definition = ecs_client.describe_task_definition(
            taskDefinition=task_definition_arn)
        return task_definition['taskDefinition']['containerDefinitions'][0]['image']

    def _get_stack_resource_summaries(self):
        stack_name = get_service_stack_name(self.environment, self.name)
        response = self.cfn_client.list_stack_resources(StackName=stack_name)
        resource_summaries = response['StackResourceSummaries']
        while 'NextToken' in response:
            response = self.cfn_client.list_stack_resources(
                StackName=stack_name,
                NextToken=response['NextToken'],
            )
            resource_summaries.extend(response.get('Rules', []))
        return resource_summaries

    def get_existing_listener_rule_summary(self, service_name):
        return next((rule for rule in self.listener_rules if rule['LogicalResourceId'].startswith(service_name)), None)

    def fetch_current_desired_count(self):
        desired_counts = {}
        try:
            deployment_ecs_client = EcsClient(None, None, get_region_for_environment(self.environment))
            for logical_service_name, service_config in self.service_info.items():
                deployment = DeployAction(deployment_ecs_client, self.cluster_name, service_config["ecs_service_name"])
                if deployment.service:
                    desired_counts[logical_service_name] = deployment.service.desired_count
            log("Existing service counts: " + str(desired_counts))
        except Exception as e:
            raise UnrecoverableException("Could not find existing services. {}".format(e))
        return desired_counts

    def verify_env_sample(self, env_sample_directory_path):
        if not self.stack_found:
            raise UnrecoverableException(
                "error finding stack in ServiceUpdater: {}-{}".format(self.name, self.environment))
        service_info = self.service_info
        for ecs_service_logical_name in service_info:
            ecs_service_info = service_info[ecs_service_logical_name]
            secrets_name = ecs_service_info.get('secrets_name')
            verify_and_get_secrets_for_all_namespaces(self.environment, env_sample_directory_path, secrets_name, None, None)
