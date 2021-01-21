import functools

import boto3
import click
from botocore.exceptions import ClientError

from cloudlift.config import highlight_production, ServiceConfiguration
from cloudlift.config.logging import log_err
from cloudlift.deployment import EnvironmentCreator, editor
from cloudlift.deployment.configs import deduce_name
from cloudlift.deployment.service_creator import ServiceCreator
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.deployment.service_updater import ServiceUpdater
from cloudlift.exceptions import UnrecoverableException
from cloudlift.version import VERSION


def _require_environment(func):
    @click.option('--environment', '-e', prompt='environment',
                  help='environment')
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if kwargs['environment'] == 'production' or kwargs['environment'] == 'prod':
            highlight_production()
        return func(*args, **kwargs)

    return wrapper


def _require_name(func):
    @click.option('--name', help='Your service name, give the name of \
repo')
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if kwargs['name'] is None:
            kwargs['name'] = deduce_name(None)
        return func(*args, **kwargs)

    return wrapper


class CommandWrapper(click.Group):
    def __call__(self, *args, **kwargs):
        try:
            return self.main(*args, **kwargs)
        except UnrecoverableException as e:
            log_err(e.value)
            exit(1)


@click.group(cls=CommandWrapper)
@click.version_option(version=VERSION, prog_name="cloudlift")
def cli():
    """
        Cloudlift is built by Simpl developers to make it easier to launch \
        dockerized services in AWS ECS.
    """
    try:
        boto3.client('cloudformation')
    except ClientError:
        log_err("Could not connect to AWS!")
        log_err("Ensure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY & \
AWS_DEFAULT_REGION env vars are set OR run 'aws configure'")
        exit(1)


@cli.command(help="Create a new service. This can contain multiple \
ECS services")
@_require_environment
@_require_name
@click.option('--version', default=None,
              help='local image version tag')
@click.option("--build-arg", type=(str, str), multiple=True, help="These args are passed to docker build command "
                                                                  "as --build-args. Supports multiple.\
                                                                   Please leave space between name and value")
@click.option('--dockerfile', default=None, help='The Dockerfile path used to build')
@click.option('--env_sample_file', default='env.sample', help='env sample file path')
@click.option('--ssh', default=None, help='SSH agent socket or keys to expose to the docker build')
@click.option('--cache-from', multiple=True, help='Images to consider as cache sources')
def create_service(name, environment, version, build_arg, dockerfile, env_sample_file, ssh, cache_from):
    ServiceCreator(name, environment, env_sample_file).create(
        version=version, build_arg=dict(build_arg), dockerfile=dockerfile, ssh=ssh, cache_from=list(cache_from),
    )


@cli.command(help="Update existing service.")
@_require_environment
@_require_name
@click.option('--env_sample_file', default='env.sample', help='env sample file path')
def update_service(name, environment, env_sample_file):
    ServiceCreator(name, environment, env_sample_file).update()


@cli.command(help="Create a new environment")
@click.option('--environment', '-e', prompt='environment',
              help='environment')
def create_environment(environment):
    EnvironmentCreator(environment).run()


@cli.command(help="Update environment")
@_require_environment
@click.option('--update_ecs_agents',
              is_flag=True,
              help='Update ECS container agents')
def update_environment(environment, update_ecs_agents):
    EnvironmentCreator(environment).run_update(update_ecs_agents)


@cli.command(help="Command used to create or update the configuration \
in parameter store")
@_require_name
@_require_environment
@click.option('--sidecar', help='Choose which sidecar to edit the configuration. Defaults to the main container ' +
                                'if not provided')
def edit_config(name, environment, sidecar):
    editor.edit_config(name, environment, sidecar)


@cli.command()
@_require_environment
@_require_name
@click.option('--deployment_identifier', type=str, required=True,
              help='Unique identifier for deployment which can be used for reverting')
@click.option('--timeout_seconds', default=600, help='The deployment timeout')
@click.option('--version', default=None,
              help='local image version tag')
@click.option("--build-arg", type=(str, str), multiple=True, help="These args are passed to docker build command "
                                                                  "as --build-args. Supports multiple.\
                                                                   Please leave space between name and value")
@click.option('--dockerfile', default=None, help='The Dockerfile path used to build')
@click.option('--env_sample_file', default='env.sample', help='env sample file path')
@click.option('--ssh', default=None, help='SSH agent socket or keys to expose to the docker build')
@click.option('--cache-from', multiple=True, help='Images to consider as cache sources')
def deploy_service(name, environment, timeout_seconds, version, build_arg, dockerfile, env_sample_file, ssh,
                   cache_from,
                   deployment_identifier):
    ServiceUpdater(
        name,
        environment=environment,
        env_sample_file=env_sample_file,
        timeout_seconds=timeout_seconds,
        version=version,
        build_args=dict(build_arg),
        dockerfile=dockerfile,
        ssh=ssh,
        cache_from=list(cache_from), deployment_identifier=deployment_identifier
    ).run()


@cli.command()
@_require_environment
@_require_name
@click.option('--deployment_identifier', type=str, required=True,
              help='Unique identifier for deployment which can be used for reverting')
@click.option('--timeout_seconds', default=600, help='The deployment timeout')
def revert_service(name, environment, timeout_seconds, deployment_identifier):
    ServiceUpdater(name, environment, deployment_identifier=deployment_identifier,
                   timeout_seconds=timeout_seconds).revert()


@cli.command()
@_require_name
@_require_environment
@click.option('--additional_tags', default=[], multiple=True,
              help='Additional tags for the image apart from commit SHA')
@click.option("--build-arg", type=(str, str), multiple=True, help="These args are passed to docker build command "
                                                                  "as --build-args. Supports multiple.\
                                                                   Please leave space between name and value")
@click.option('--dockerfile', default=None, help='The Dockerfile path used to build')
@click.option('--env_sample_file', default='env.sample', help='env sample file path')
@click.option('--ssh', default=None, help='SSH agent socket or keys to expose to the docker build')
@click.option('--cache-from', multiple=True, help='Images to consider as cache sources')
def upload_to_ecr(name, environment, additional_tags, build_arg, dockerfile, env_sample_file, ssh, cache_from):
    ServiceUpdater(name, environment=environment, env_sample_file=env_sample_file,
                   build_args=dict(build_arg), dockerfile=dockerfile,
                   ssh=ssh, cache_from=list(cache_from)).upload_to_ecr(additional_tags)


@cli.command(help="Get commit information of currently deployed code \
from commit hash")
@_require_environment
@_require_name
@click.option('--image', is_flag=True, help='Print image with version')
@click.option('--git', is_flag=True, help='Prints the git revision part of the image')
def get_version(name, environment, image, git):
    ServiceInformationFetcher(
        name,
        environment,
        ServiceConfiguration(service_name=name, environment=environment).get_config(),
    ).get_version(print_image=image, print_git=git)


if __name__ == '__main__':
    cli()
