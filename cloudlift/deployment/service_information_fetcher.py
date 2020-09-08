from subprocess import call

from cloudlift.config import get_client_for
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.config.logging import log, log_bold, log_err, log_intent, log_warning
from cloudlift.exceptions import UnrecoverableException
from cloudlift.deployment.ecs import DeployAction, EcsClient
from cloudlift.config import get_region_for_environment


class ServiceInformationFetcher(object):
    def __init__(self, name, environment):
        self.name = name
        self.environment = environment
        self.cluster_name = get_cluster_name(environment)
        self.init_stack_info()

    def init_stack_info(self):
        stack_name = get_service_stack_name(self.environment, self.name)
        try:
            cfn_client = get_client_for('cloudformation', self.environment)
            stack = cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]
            ecs_service_outputs = list(
                filter(
                    lambda x: x['OutputKey'].endswith('EcsServiceName'),
                    stack['Outputs']
                )
            )
            stack_outputs = {output['OutputKey']: output['OutputValue'] for output in stack['Outputs']}
            self.service_info = {}
            for service_output in ecs_service_outputs:
                ecs_service_logical_name = service_output['OutputKey'].replace("EcsServiceName", "")
                self.service_info[ecs_service_logical_name] = {
                    "ecs_service_name": service_output['OutputValue'],
                    "secrets_name_prefix": stack_outputs.get(ecs_service_logical_name + 'SecretsNamePrefix')
                }

            self.ecs_service_names = [svc_name['OutputValue'] for svc_name in ecs_service_outputs]
            self.ecs_service_logical_name_mappings = []
            for service_output in ecs_service_outputs:
                self.ecs_service_logical_name_mappings.append({
                    "key": service_output['OutputKey'].replace("EcsServiceName", ""),
                    "value": service_output['OutputValue']
                })
        except Exception:
            self.ecs_service_names = []
            self.ecs_service_logical_name_mappings = []
            log_warning("Could not determine services.")

    def get_current_version(self):
        commit_sha = self._fetch_current_task_definition_tag()
        log_warning(f"Currently deployed tag: {commit_sha}")
        return str(commit_sha)

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

    def get_version(self, short):
        commit_sha = self._fetch_current_task_definition_tag()
        if commit_sha is None:
            log_err("Current task definition tag could not be found. \
Is it deployed?")
        elif commit_sha == "dirty":
            log("Dirty version is deployed. Commit information could not be \
fetched.")
        else:
            log("Currently deployed version: " + commit_sha)
            if not short:
                log("Running `git fetch --all`")
                call(["git", "fetch", "--all"])
                log_bold("Commit Info:")
                call([
                    "git",
                    "--no-pager",
                    "show",
                    "-s",
                    "--format=medium",
                    commit_sha
                ])
                log_bold("Branch Info:")
                call(["git", "branch", "-r", "--contains", commit_sha])
                log("")

    def _fetch_current_task_definition_tag(self):
        try:
            ecs_client = get_client_for('ecs', self.environment)
            service = self.ecs_service_names[0]
            task_arns = ecs_client.list_tasks(
                cluster=self.cluster_name,
                serviceName=service
            )['taskArns']
            tasks = ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=task_arns
            )['tasks']
            task_definition_arns = tasks[0]['taskDefinitionArn']
            task_definition = ecs_client.describe_task_definition(
                taskDefinition=task_definition_arns
            )
            image = task_definition['taskDefinition']['containerDefinitions'][0]['image']
            commit_sha = image.split('-repo:')[1]
            return commit_sha
        except Exception:
            return None

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
