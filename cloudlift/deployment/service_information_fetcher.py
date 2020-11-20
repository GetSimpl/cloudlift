from subprocess import call

from cloudlift.config import get_client_for
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.config.logging import log, log_bold, log_err, log_warning, log_intent
from cloudlift.exceptions import UnrecoverableException
from cloudlift.deployment.ecs import DeployAction, EcsClient
from cloudlift.config import get_region_for_environment
from stringcase import spinalcase
from re import search


class ServiceInformationFetcher(object):
    def __init__(self, name, environment):
        self.name = name
        self.environment = environment
        self.cluster_name = get_cluster_name(environment)
        self.cfn_client = get_client_for('cloudformation', self.environment)
        self.init_stack_info()

    def init_stack_info(self):
        stack_name = get_service_stack_name(self.environment, self.name)
        try:
            stack = self.cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]
            self.stack_found = True
            ecs_service_outputs = list(
                filter(
                    lambda x: x['OutputKey'].endswith('EcsServiceName'),
                    stack['Outputs']
                )
            )
            stack_outputs = {output['OutputKey']: output['OutputValue'] for output in stack['Outputs']}

            # For backwards compatibility during deployment, using default as {service-name}-repo
            self.ecr_repo_name = stack_outputs.get('ECRRepoName', spinalcase(self.name + '-repo'))
            self.ecr_assume_role_arn = stack_outputs.get('ECRAssumeRoleARN', None)
            self.ecr_account_id = stack_outputs.get('ECRAccountID', None)
            self.service_info = {}

            for service_output in ecs_service_outputs:
                ecs_service_logical_name = service_output['OutputKey'].replace("EcsServiceName", "")
                self.service_info[ecs_service_logical_name] = {
                    "ecs_service_name": service_output['OutputValue'],
                    "secrets_name": stack_outputs.get(ecs_service_logical_name + 'SecretsName')
                }

            self.ecs_service_names = [svc_name['OutputValue'] for svc_name in ecs_service_outputs]
            self.ecs_service_logical_name_mappings = []
            for service_output in ecs_service_outputs:
                self.ecs_service_logical_name_mappings.append({
                    "key": service_output['OutputKey'].replace("EcsServiceName", ""),
                    "value": service_output['OutputValue']
                })
            resource_summaries = self._get_stack_resource_summaries()
            self.listener_rules = [resource_summary for resource_summary in resource_summaries
                                   if resource_summary['LogicalResourceId'].endswith('ListenerRule')]
        except Exception as e:
            self.ecs_service_names = []
            self.ecs_service_logical_name_mappings = []
            self.stack_found = False
            log_warning("Could not determine services.")

    def get_current_image_uri(self):
        ecr_image_uri = self._fetch_current_image_uri()
        log_intent(f"Currently deployed tag: {ecr_image_uri}")
        return str(ecr_image_uri)

    def get_instance_ids(self):
        instance_ids = {}
        ecs_client = get_client_for('ecs', self.environment)
        for service in self.ecs_service_names:
            task_arns = ecs_client.list_tasks(
                cluster=self.cluster_name,
                serviceName=service
            )['taskArns']
            tasks = ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=task_arns
            )['tasks']
            container_instance_arns = [
                task['containerInstanceArn'] for task in tasks
            ]
            container_instances = ecs_client.describe_container_instances(
                cluster=self.cluster_name,
                containerInstances=container_instance_arns
            )['containerInstances']
            service_instance_ids = [
                container['ec2InstanceId'] for container in container_instances
            ]
            instance_ids[service] = service_instance_ids
        return instance_ids

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
        if len(self.ecs_service_names) < 1:
            raise UnrecoverableException("cannot get running image_uri: no ECS services found")

        service = self.ecs_service_names[0]
        task_arns = ecs_client.list_tasks(
            cluster=self.cluster_name,
            serviceName=service
        )['taskArns']

        if len(task_arns) < 1:
            raise UnrecoverableException("cannot get running image_uri: no task ARNs found for service")

        tasks = ecs_client.describe_tasks(
            cluster=self.cluster_name,
            tasks=task_arns
        )['tasks']

        task_definition_arns = tasks[0]['taskDefinitionArn']
        task_definition = ecs_client.describe_task_definition(
            taskDefinition=task_definition_arns
        )
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

    # TODO: Test cover this. Also this can use boto ecs client describe_services method. That can describe up to 10
    #  services in one call. It would be simpler implementation to test as well. We can also use self.service_info
    #  instead of ecs_service_logical_name_mappings and simplify the init_stack_info logic
    def fetch_current_desired_count(self):
        desired_counts = {}
        try:
            deployment_ecs_client = EcsClient(None, None, get_region_for_environment(self.environment))
            for service_logical_name_map in self.ecs_service_logical_name_mappings:
                deployment = DeployAction(deployment_ecs_client, self.cluster_name, service_logical_name_map["value"])
                desired_counts[service_logical_name_map["key"]] = deployment.service.desired_count
            log("Existing service counts: " + str(desired_counts))
        except Exception:
            raise UnrecoverableException("Could not find existing services.")
        return desired_counts
