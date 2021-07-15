import os
from concurrent.futures import ThreadPoolExecutor
import time

import boto3

from cloudlift.config import get_account_id, get_cluster_name, \
    ServiceConfiguration, get_region_for_environment
from cloudlift.config.logging import log_bold, log_intent, log_warning
from cloudlift.deployment import deployer, ServiceInformationFetcher
from cloudlift.deployment.ecs import EcsClient
from cloudlift.exceptions import UnrecoverableException
from cloudlift.deployment.ecr import ECR
from cloudlift.utils.yaml_parser import load_access_file
from stringcase import spinalcase

DEPLOYMENT_COLORS = ['blue', 'magenta', 'white', 'cyan']
DEPLOYMENT_CONCURRENCY = int(os.environ.get('CLOUDLIFT_DEPLOYMENT_CONCURRENCY', 4))


class ServiceUpdater(object):
    def __init__(self, name, environment='', env_sample_file='', timeout_seconds=None, version=None,
                 build_args=None, dockerfile=None, ssh=None, cache_from=None,
                 deployment_identifier=None, access_file=None, working_dir='.'):
        self.name = name
        self.environment = environment
        self.deployment_identifier = deployment_identifier
        self.env_sample_file = env_sample_file
        self.timeout_seconds = timeout_seconds
        self.version = version
        self.ecr_client = boto3.session.Session(region_name=self.region).client('ecr')
        self.cluster_name = get_cluster_name(environment)
        self.service_configuration = ServiceConfiguration(service_name=name, environment=environment).get_config()
        self.service_info_fetcher = ServiceInformationFetcher(self.name, self.environment, self.service_configuration)
        self.access_file = access_file
        if not self.service_info_fetcher.stack_found:
            raise UnrecoverableException(
                "error finding stack in ServiceUpdater: {}-{}".format(self.name, self.environment))
        ecr_repo_config = self.service_configuration.get('ecr_repo')
        self.ecr = ECR(
            self.region,
            ecr_repo_config.get('name', spinalcase(self.name + '-repo')),
            ecr_repo_config.get('account_id', get_account_id()),
            ecr_repo_config.get('assume_role_arn', None),
            version,
            build_args,
            dockerfile,
            working_dir,
            ssh,
            cache_from
        )

    def run(self):
        start_time = time.time()
        log_warning("Deploying to {self.region}".format(**locals()))
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(self.version) +
                   " | deployment_identifier: " + self.deployment_identifier)
        log_bold("Checking image in ECR")
        self.ecr.upload_artefacts()
        log_bold("Initiating deployment\n")
        ecs_client = EcsClient(None, None, self.region)

        image_url = self.ecr.image_uri
        target = deployer.deploy_new_version
        kwargs = dict(client=ecs_client, cluster_name=self.cluster_name,
                      service_name=self.name, sample_env_file_path=self.env_sample_file,
                      timeout_seconds=self.timeout_seconds, env_name=self.environment,
                      ecr_image_uri=image_url, deployment_identifier=self.deployment_identifier,
                      access_file=self.access_file,
                      )
        if self.access_file:
            load_access_file(self.access_file)
        self.run_job_for_all_services("Deploy", target, kwargs)
        log_bold("Deployment completed in {:.2f} seconds".format(time.time()-start_time))

    def revert(self):
        target = deployer.revert_deployment
        ecs_client = EcsClient(None, None, self.region)
        kwargs = dict(client=ecs_client, cluster_name=self.cluster_name, timeout_seconds=self.timeout_seconds,
                      deployment_identifier=self.deployment_identifier)
        self.run_job_for_all_services("Revert", target, kwargs)

    def upload_to_ecr(self, additional_tags):
        self.ecr.upload_artefacts()
        self.ecr.add_tags(additional_tags)

    def run_job_for_all_services(self, job_name, target, kwargs):
        jobs = []
        service_info = self.service_info_fetcher.service_info
        with ThreadPoolExecutor(max_workers=DEPLOYMENT_CONCURRENCY) as executor:
            for index, ecs_service_logical_name in enumerate(service_info):
                ecs_service_info = service_info[ecs_service_logical_name]
                log_bold(f"Starting {job_name} of " + ecs_service_info['ecs_service_name'])
                color = DEPLOYMENT_COLORS[index % 3]
                services_configuration = self.service_configuration['services']
                kwargs_copy = kwargs.copy()
                kwargs_copy.update(dict(ecs_service_name=ecs_service_info['ecs_service_name'],
                                   secrets_name=ecs_service_info.get('secrets_name'),
                                   ecs_service_logical_name=ecs_service_logical_name,
                                   color=color,
                                   service_configuration=services_configuration.get(ecs_service_logical_name),
                                   region=self.region,
                                   ))
                jobs.append(executor.submit(target, **kwargs_copy))
        log_bold(f"Waiting for {job_name} to complete.")
        with ThreadPoolExecutor(max_workers=DEPLOYMENT_CONCURRENCY) as executor:
            results = [executor.submit(job.result().wait_for_finish) for job in jobs]
        for result in results:
            if result.exception() is not None:
                raise UnrecoverableException(f"{job_name} failed")

    @property
    def region(self):
        return get_region_for_environment(self.environment)
