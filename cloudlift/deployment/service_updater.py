import base64
import multiprocessing
import os
import subprocess
import boto3
from time import sleep

from botocore.exceptions import ClientError

from cloudlift.deployment.ecr_client import EcrClient
from cloudlift.exceptions import UnrecoverableException
from stringcase import spinalcase, capitalcase

from cloudlift.config import get_account_id
from cloudlift.config import (get_client_for,
                              get_region_for_environment)
from cloudlift.config import get_cluster_name, get_service_stack_name
from cloudlift.deployment import deployer
from cloudlift.deployment.ecs import EcsClient
from cloudlift.config.logging import log_bold, log_err, log_intent, log_warning
from cloudlift.deployment.ecs import DeployAction

DEPLOYMENT_COLORS = ['blue', 'magenta', 'white', 'cyan']


class ServiceUpdater(object):
    def __init__(self, name, environment, env_sample_file, version=None,
                 build_args=None, working_dir='.'):
        self.name = name
        self.environment = environment
        if env_sample_file is not None:
            self.env_sample_file = env_sample_file
        else:
            self.env_sample_file = './env.sample'
        self.version = version
        self.ecr_client = boto3.session.Session(region_name=self.region).client('ecr')
        self.cluster_name = get_cluster_name(environment)
        self.working_dir = working_dir
        self.build_args = build_args

    def run(self):
        log_warning("Deploying to {self.region}".format(**locals()))
        self.init_stack_info()
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        ecr_client = EcrClient(self.name, self.version, self.region, self.build_args)
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(ecr_client.version))
        log_bold("Checking image in ECR")
        ecr_client.build_and_upload_image()
        log_bold("Initiating deployment\n")
        ecs_client = EcsClient(None, None, self.region)

        jobs = []
        for index, service_name in enumerate(self.ecs_service_names):
            log_bold("Starting to deploy " + service_name)
            color = DEPLOYMENT_COLORS[index % 3]
            image_url = ecr_client.ecr_image_uri
            print(image_url)
            image_url += (':' + ecr_client.version)
            process = multiprocessing.Process(
                target=deployer.deploy_new_version,
                args=(
                    ecs_client,
                    self.cluster_name,
                    service_name,
                    ecr_client.version,
                    self.name,
                    self.env_sample_file,
                    self.environment,
                    color,
                    image_url
                )
            )
            jobs.append(process)
            process.start()

        exit_codes = []
        while True:
            sleep(1)
            exit_codes = [proc.exitcode for proc in jobs]
            if None not in exit_codes:
                break

        if any(exit_codes) != 0:
            raise UnrecoverableException("Deployment failed")

    def upload_image(self, additional_tags):
        EcrClient(self.name, self.version, self.region, self.build_args).upload_image(additional_tags)

    def update_task_defn(self):
        log_warning("Update task definition to {self.region}".format(**locals()))
        self.init_stack_info()
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        ecr_client = EcrClient(self.name, self.version, self.region, self.build_args)
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(ecr_client.version))
        log_bold("Checking image in ECR")
        ecr_client.build_and_upload_image()
        log_bold("Initiating deployment\n")
        ecs_client = EcsClient(None, None, self.region)

        service_name = self.ecs_service_names[0]
        deployment = DeployAction(ecs_client, self.cluster_name, service_name)
        env_config = deployer.build_config(self.environment, self.name, self.env_sample_file)
        image_url = ecr_client.ecr_image_uri
        image_url += (':' + ecr_client.version)

        task_defn_family = "".join(list(map(capitalcase, self.name.split('-')))) + "Family"
        task_defns = ecs_client.list_task_definitions(task_defn_family)
        deployer.update_task_defn(deployment, env_config, ecr_client.version, 'white', image_url, task_defns[0])

    @property
    def region(self):
        return get_region_for_environment(self.environment)

    def init_stack_info(self):
        try:
            self.stack_name = get_service_stack_name(self.environment, self.name)
            stack = get_client_for(
                'cloudformation',
                self.environment
            ).describe_stacks(
                StackName=self.stack_name
            )['Stacks'][0]
            self.ecs_service_names = [
                service_name['OutputValue'] for service_name in list(
                    filter(
                        lambda x: x['OutputKey'].endswith('EcsServiceName'),
                        stack['Outputs']
                    )
                )
            ]
        except ClientError as client_error:
            err = str(client_error)
            if "Stack with id %s does not exist" % self.stack_name in err:
                log_err(
                    "%s cluster not found. Create the environment cluster using `create_environment` command." % self.environment)
            else:
                raise UnrecoverableException(str(client_error))
