import base64
import multiprocessing
import os
import subprocess
import sys
from time import sleep

from botocore.exceptions import ClientError
from stringcase import spinalcase

from config import region as region_service
from config.account import get_account_id
from config.region import (ECR_REGION, get_client_for,
                           get_region_for_environment, session_for_ecr)
from config.stack import get_cluster_name, get_service_stack_name
from deployment import deployer
from deployment.ecs import EcsClient
from deployment.logging import log_bold, log_err, log_intent, log_warning

DEPLOYMENT_COLORS = ['blue', 'magenta', 'white', 'cyan']


class ServiceUpdater(object):
    def __init__(self, name, environment, env_sample_file, version=None,
                 working_dir='.'):
        self.name = name
        self.environment = environment
        if env_sample_file is not None:
            self.env_sample_file = env_sample_file
        else:
            self.env_sample_file = './env.sample'
        self.version = version
        self.ecr_client = session_for_ecr().client('ecr')
        self.cluster_name = get_cluster_name(environment)
        self.working_dir = working_dir

    def run(self):
        log_warning("Deploying to {self.region}".format(**locals()))
        self.init_stack_info()
        if not os.path.exists(self.env_sample_file):
            log_err('env.sample not found. Exiting.')
            exit(1)
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(self.version))
        log_bold("Checking image in ECR")
        self.upload_artefacts()
        log_bold("Initiating deployment\n")
        ecs_client = EcsClient(None, None, self.region)

        jobs = []
        for index, service_name in enumerate(self.ecs_service_names):
            log_bold("Starting to deploy " + service_name)
            color = DEPLOYMENT_COLORS[index % 3]
            image_url = self.ecr_image_uri
            image_url += (':' + self.version)
            process = multiprocessing.Process(
                target=deployer.deploy_new_version,
                args=(
                    ecs_client,
                    self.cluster_name,
                    service_name,
                    self.version,
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
            sys.exit(1)

    def upload_image(self, additional_tags):
        image_name = spinalcase(self.name) + ':' + self.version
        ecr_image_name = self.ecr_image_uri + ':' + self.version
        self.ensure_repository()
        self._push_image(image_name, ecr_image_name)

        for new_tag in additional_tags:
            self._add_image_tag(self.version, new_tag)

    def _build_image(self, image_name):
        log_bold("Building docker image " + image_name)
        subprocess.check_call([
            "docker",
            "build",
            "-t",
            image_name,
            self.working_dir
        ])
        log_bold("Built " + image_name)

    def upload_artefacts(self):
        self.ensure_repository()
        self.ensure_image_in_ecr()

    def ensure_repository(self):
        try:
            self.ecr_client.create_repository(repositoryName=self.repo_name)
            log_intent('Repo created with name: '+self.repo_name)
        except Exception as ex:
            if type(ex).__name__ == 'RepositoryAlreadyExistsException':
                log_intent('Repo exists with name: '+self.repo_name)
            else:
                raise ex

    def _login_to_ecr(self):
        log_intent("Attempting login...")
        auth_token_res = self.ecr_client.get_authorization_token()
        user, auth_token = base64.b64decode(
            auth_token_res['authorizationData'][0]['authorizationToken']
        ).decode("utf-8").split(':')
        ecr_url = auth_token_res['authorizationData'][0]['proxyEndpoint']
        subprocess.check_call(["docker", "login", "-u", user,
                               "-p", auth_token, ecr_url])
        log_intent('Docker login to ECR succeeded.')

    def _find_commit_sha(self, version=None):
        log_intent("Finding commit SHA")
        try:
            version_to_find = version or "HEAD"
            commit_sha = subprocess.check_output(
                ["git", "rev-list", "-n", "1", version_to_find]
            ).strip().decode("utf-8")
            log_intent("Found commit SHA " + commit_sha)
            return commit_sha
        except:
            log_err("Commit SHA not found. Given version is not a git tag, \
branch or commit SHA")
            exit(1)

    def _push_image(self, local_name, ecr_name):
        try:
            subprocess.check_call(["docker", "tag", local_name, ecr_name])
        except:
            log_err("Local image was not found.")
            exit(1)
        self._login_to_ecr()
        subprocess.check_call(["docker", "push", ecr_name])
        subprocess.check_call(["docker", "rmi", ecr_name])
        log_intent('Pushed the image (' + local_name + ') to ECR sucessfully.')

    def _add_image_tag(self, existing_tag, new_tag):
        try:
            image_manifest = self.ecr_client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[
                    {'imageTag': existing_tag}
                ])['images'][0]['imageManifest']
            self.ecr_client.put_image(
                repositoryName=self.repo_name,
                imageTag=new_tag,
                imageManifest=image_manifest
            )
        except:
            log_err("Unable to add additional tag " + str(new_tag))

    def _find_image_in_ecr(self, tag):
        try:
            return self.ecr_client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[{'imageTag': tag}]
            )['images'][0]
        except:
            return None

    def ensure_image_in_ecr(self):
        if self.version:
            try:
                commit_sha = self._find_commit_sha(self.version)
            except:
                commit_sha = self.version
            log_intent("Using commit hash " + commit_sha + " to find image")
            image = self._find_image_in_ecr(commit_sha)
            if not image:
                log_err("Image for given version could not be found.")
                log_warning("Please build, tag and upload the image for the \
commit " + commit_sha)
                exit(1)
        else:
            dirty = subprocess.check_output(
                ["git", "status", "--short"]
            ).decode("utf-8")
            if dirty:
                self.version = 'dirty'
                log_intent("Version parameter was not provided. Determined \
version to be " + self.version + " based on current status")
                image = None
            else:
                self.version = self._find_commit_sha()
                log_intent("Version parameter was not provided. Determined \
version to be " + self.version + " based on current status")
                image = self._find_image_in_ecr(self.version)

            if image:
                log_intent("Image found in ECR")
            else:
                log_bold("Image not found in ECR. Building image")
                image_name = spinalcase(self.name) + ':' + self.version
                ecr_name = self.ecr_image_uri + ':' + self.version
                self._build_image(image_name)
                self._push_image(image_name, ecr_name)
                image = self._find_image_in_ecr(self.version)

        try:
            image_manifest = image['imageManifest']
            self.ecr_client.put_image(
                repositoryName=self.repo_name,
                imageTag=self.version,
                imageManifest=image_manifest
            )
        except Exception:
            pass

    @property
    def ecr_image_uri(self):
        return str(self.account_id) + ".dkr.ecr." + ECR_REGION + \
            ".amazonaws.com/" + self.repo_name

    @property
    def repo_name(self):
        return self.name + '-repo'

    @property
    def region(self):
        return get_region_for_environment(self.environment)

    @property
    def account_id(self):
        return get_account_id()

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
                log_err(str(client_error))
            exit(1)
