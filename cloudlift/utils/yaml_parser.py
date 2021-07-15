from pathlib import Path
import ruamel.yaml

from cloudlift.config.logging import log_err

yaml = ruamel.yaml.YAML()


@yaml.register_class
class Flatten(list):
   yaml_tag = u'!flatten'
   def __init__(self, *args):
      self.items = args

   @classmethod
   def from_yaml(cls, constructor, node):
       x = cls(*constructor.construct_sequence(node, deep=True))
       return x

   def __iter__(self):
       for item in self.items:
           if isinstance(item, list):
               for nested_item in item:
                   yield nested_item
           else:
               yield item

access_roles_data = None


def load_access_file(access_file):
    global access_roles_data
    if not access_file:
        return

    if access_roles_data is None:
        file = Path(access_file)
        if not file.is_file():
            log_err(f"Access file ({access_file}) is missing")
            return

        try:
            access_roles_data = yaml.load(file)
        except Exception as e:
            log_err(f"Error parsing access_file: {e}")
            return

    return access_roles_data


def config_keys(access_role, access_file):
    if not access_file:
        return []

    data = load_access_file(access_file)

    if access_role not in data:
        return []

    return data[access_role]['resources']['environment_variables']