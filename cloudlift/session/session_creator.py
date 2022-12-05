import functools
import operator
import re
from click import prompt

from cloudlift.exceptions import UnrecoverableException

from cloudlift.config import get_client_for, get_region_for_environment
from cloudlift.config import mfa
from cloudlift.config.logging import log, log_bold, log_err
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from awscli.clidriver import create_clidriver

class SessionCreator(object):
  def __init__(self, name, environment):
    self.name = name
    self.environment = environment
    self.sts_client = get_client_for("sts", self.environment)

  def start_session(self, mfa_code, component):
    user_id = (self.sts_client.get_caller_identity()['Arn'].split("/")[0]).split(":")[-1]
    if user_id == "user":
      if mfa_code == None:
        mfa_code = prompt("MFA code")
      mfa.do_mfa_login(mfa_code, get_region_for_environment(self.environment))
      target_instance = self._get_target_instance(component)
    elif user_id == "assumed-role":
      target_instance = self._get_target_instance(component)
    self._initiate_session(target_instance)

  def _get_target_instance(self, component):
    service_instance_ids = ServiceInformationFetcher(self.name, self.environment).get_instance_ids(component)
    if not service_instance_ids:
      raise UnrecoverableException("Couldn't find instances. Exiting.")
    instance_ids = list(set(functools.reduce(operator.add,service_instance_ids.values())))
    log("Found " + str(len(instance_ids)) + " instances to start session")
    return instance_ids[0]


  def _initiate_session(self, target_instance):
    log_bold("Starting session in " + target_instance)
    try:
      driver = create_clidriver()
      driver.main(["ssm", "start-session", "--target", target_instance])
    except:
      raise UnrecoverableException("Failed to start session")
