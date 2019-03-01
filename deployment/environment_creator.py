import sys
from time import sleep

from botocore.exceptions import ClientError

from config.environment_configuration import EnvironmentConfiguration
from config.region import get_client_for
from config.stack import get_cluster_name
from deployment.changesets import create_change_set
from deployment.cluster_template_generator import ClusterTemplateGenerator
from deployment.logging import log, log_bold, log_err
from deployment.progress import get_stack_events, print_new_events


class EnvironmentCreator(object):

    def __init__(self, environment):
        self.environment = environment
        environment_configuration = EnvironmentConfiguration(
            self.environment
        )
        environment_configuration.update_config()
        self.configuration = environment_configuration.get_config()[self.environment]
        self.cluster_name = get_cluster_name(environment)
        self.client = get_client_for('cloudformation', self.environment)
        self.key_name = self.configuration['cluster']['key_name']

    def run(self):
        try:
            log("Check if stack already exists for " + self.cluster_name)
            environment_stack = self.client.describe_stacks(
                StackName=self.cluster_name
            )['Stacks'][0]
            log(self.cluster_name + " stack exists. ID: " +
                environment_stack['StackId'])
            log_err("Cannot create environment with duplicate name: " +
                    self.cluster_name)
        except Exception:
            log(self.cluster_name +
                " stack does not exist. Creating new stack.")
            # When creating a cluster, desired_instance count is same
            # as min_instance count
            environment_stack_template_body = ClusterTemplateGenerator(
                self.environment,
                self.configuration
            ).generate_cluster()
            self.existing_events = get_stack_events(
                self.client,
                self.cluster_name
            )
            environment_stack = self.client.create_stack(
                StackName=self.cluster_name,
                TemplateBody=environment_stack_template_body,
                Parameters=[
                    {
                        'ParameterKey': 'KeyPair',
                        'ParameterValue': self.key_name,
                    },
                    {
                        'ParameterKey': 'Environment',
                        'ParameterValue': self.environment,
                    }
                ],
                OnFailure='DO_NOTHING',
                Capabilities=['CAPABILITY_NAMED_IAM'],
            )
            log_bold("Submitted to cloudformation. Checking progress...")
            self.__print_progress()
            log_bold(self.cluster_name+" stack created. ID: " +
                     environment_stack['StackId'])

    def run_update(self, update_ecs_agents):
        if update_ecs_agents:
            self.__run_ecs_container_agent_udpate()
        try:
            log("Initiating environment stack update.")
            environment_stack_template_body = ClusterTemplateGenerator(
                self.environment,
                self.configuration,
                self.__get_desired_count()
            ).generate_cluster()
            log("Template generation complete.")
            change_set = create_change_set(
                self.client,
                environment_stack_template_body,
                self.cluster_name,
                self.key_name,
                self.environment
            )
            self.existing_events = get_stack_events(
                self.client,
                self.cluster_name
            )
            log_bold("Executing changeset. Checking progress...")
            self.client.execute_change_set(
                ChangeSetName=change_set['ChangeSetId']
            )
            self.__print_progress()
        except ClientError as e:
            log_err("No updates are to be performed")
        except Exception as e:
            raise e
            # log_err("Something went wrong")
            # TODO: Describe error here.

    def __get_desired_count(self):
        try:
            auto_scaling_client = get_client_for(
                'autoscaling',
                self.environment
            )
            cloudformation_client = get_client_for(
                'cloudformation',
                self.environment
            )
            cfn_resources = cloudformation_client.list_stack_resources(
                StackName=self.cluster_name
            )
            auto_scaling_group_name = list(
                filter(
                    lambda x: x['ResourceType'] == "AWS::AutoScaling::AutoScalingGroup",
                    cfn_resources['StackResourceSummaries']
                )
            )[0]['PhysicalResourceId']
            response = auto_scaling_client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[auto_scaling_group_name]
            )
            return response['AutoScalingGroups'][0]['DesiredCapacity']
        except Exception:
            log_err("Unable to fetch desired instance count.")
            exit(1)


    def __print_progress(self):
        while True:
            response = self.client.describe_stacks(StackName=self.cluster_name)
            if "IN_PROGRESS" not in response['Stacks'][0]['StackStatus']:
                break
            all_events = get_stack_events(self.client, self.cluster_name)
            print_new_events(all_events, self.existing_events)
            self.existing_events = all_events
            sleep(5)
        log_bold("Finished and Status: %s" % (response['Stacks'][0]['StackStatus']))

    def __run_ecs_container_agent_udpate(self):
        log("Initiating agent update")
        ecs_client = get_client_for('ecs', self.environment)
        response = ecs_client.list_container_instances(
            cluster=self.cluster_name
        )
        container_instance_arns = response['containerInstanceArns']
        for container_instance_arn in response['containerInstanceArns']:
            try:
                response = ecs_client.update_container_agent(
                    cluster=self.cluster_name,
                    containerInstance=container_instance_arn
                )
            except ClientError as exception:
                if "There is no update available for your container agent." in str(exception):
                    log("There is no update available for your container agent " + container_instance_arn)
                elif "Agent update is already in progress." in str(exception):
                    log("Agent update is already in progress " + container_instance_arn)
                else:
                    raise exception

        while True:
            sleep(1)
            response = ecs_client.describe_container_instances(
                cluster=self.cluster_name,
                containerInstances=container_instance_arns
            )
            update_statuses = map(
                lambda x: {
                    "arn": x['containerInstanceArn'],
                    "status": x.get('agentUpdateStatus', 'UPDATED')
                },
                response['containerInstances']
            )
            finished = True
            status_string = '\r'
            for status in update_statuses:
                status_string += status['arn'] + ":\033[92m" + \
                    status['status'] + " \033[0m"
                if status['status'] != 'UPDATED':
                    finished = False
            sys.stdout.write(status_string)
            sys.stdout.flush()

            if finished:
                print("")
                break
