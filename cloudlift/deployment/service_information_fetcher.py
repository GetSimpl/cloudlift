
from subprocess import call

from click import confirm, edit, prompt

from cloudlift.exceptions import UnrecoverableException

from cloudlift.config import get_client_for
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.config.logging import log, log_bold, log_err, log_intent, log_warning


class ServiceInformationFetcher(object):
    def __init__(self, name, environment):
        self.name = name
        self.environment = environment
        self.cluster_name = get_cluster_name(environment)
        self.ecs_client = get_client_for('ecs', self.environment)
        self.ec2_client = get_client_for('ec2', self.environment)
        self.init_stack_info()

    def init_stack_info(self):
        self.stack_name = get_service_stack_name(self.environment, self.name)
        try:
            stack = get_client_for(
                'cloudformation',
                self.environment).describe_stacks(
                    StackName=self.stack_name
                )['Stacks'][0]
            service_name_list = list(
                filter(
                    lambda x: x['OutputKey'].endswith('EcsServiceName'),
                    stack['Outputs']
                )
            )
            self.ecs_display_names = [
                svc_name['OutputKey'] for svc_name in service_name_list
            ]
            self.ecs_service_names = [
                svc_name['OutputValue'] for svc_name in service_name_list
            ]
        except Exception:
            self.ecs_service_names = []
            log_warning("Could not determine services.")

    def get_current_version(self):
        commit_sha = self._fetch_current_task_definition_tag()
        if commit_sha is None or commit_sha == 'dirty':
            log_warning("Currently deployed tag could not be found or is dirty,\
resetting to master")
            commit_sha = "master"
        return commit_sha

    def log_ips(self):
        for service in self.ecs_service_names:
            task_arns = self.ecs_client.list_tasks(
                cluster=self.cluster_name,
                serviceName=service
            )['taskArns']
            tasks = self.ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=task_arns
            )['tasks']
            container_instance_arns = [
                task['containerInstanceArn'] for task in tasks
            ]
            container_instances = self.ecs_client.describe_container_instances(
                cluster=self.cluster_name,
                containerInstances=container_instance_arns
            )['containerInstances']
            ecs_instance_ids = [
                container['ec2InstanceId'] for container in container_instances
            ]
            ec2_reservations = self.ec2_client.describe_instances(
                InstanceIds=ecs_instance_ids
            )['Reservations']
            log_bold(service,)
            for reservation in ec2_reservations:
                instances = reservation['Instances']
                ips = [instance['PrivateIpAddress'] for instance in instances]
                [log_intent(ip) for ip in ips]
            log("")

    def check_service_name(self, component):
        component = "-" + component + "-"
        for svc in self.ecs_service_names:
            if component in svc:
                return svc
        raise UnrecoverableException("Mentioned service does not exist.")


    def get_instance_ids(self, component):
        instance_ids = {}
        if not component:
            log_bold("List of services running")
            for svc in self.ecs_display_names:
                print(svc.split('EcsServiceName')[0])
            component = prompt("Choose an ecs service", default=self.ecs_display_names[0].split('EcsServiceName')[0])
            self.ecs_service_names =[ self.check_service_name(component) ]
        else:
            self.ecs_service_names = [ self.check_service_name(component) ]
            print("finding instances the service is running on")
        for service in self.ecs_service_names:
            task_arns = self.ecs_client.list_tasks(
                cluster=self.cluster_name,
                serviceName=service
            )['taskArns']
            tasks = self.ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=task_arns
            )['tasks']
            container_instance_arns = [
                task['containerInstanceArn'] for task in tasks
            ]
            container_instances = self.ecs_client.describe_container_instances(
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
            service = self.ecs_service_names[0]
            task_arns = self.ecs_client.list_tasks(
                cluster=self.cluster_name,
                serviceName=service
            )['taskArns']
            tasks = self.ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=task_arns
            )['tasks']
            task_definition_arns = tasks[0]['taskDefinitionArn']
            task_definition = self.ecs_client.describe_task_definition(
                taskDefinition=task_definition_arns
            )
            # get the container definitions other than sidecars
            main_container_definitions = []
            for container_definition in task_definition['taskDefinition']['containerDefinitions']:
                if not container_definition['name'].endswith('-sidecar'):
                    main_container_definitions.append(container_definition)
            image = main_container_definitions[0]['image']
            commit_sha = image.split('-repo:')[1]
            return commit_sha
        except Exception:
            return None
