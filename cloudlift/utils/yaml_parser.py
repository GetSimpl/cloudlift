from pathlib import Path
from os import path
import ruamel.yaml

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
    if not path.isfile(access_file):
        return None
    global access_roles_data
    if access_roles_data is None:
        access_roles_data = yaml.load(Path(access_file))
    return access_roles_data

def config_keys(access_role, access_file):
    if not access_file:
        return None
    data = load_access_file(access_file)
    if data is None:
        return None
    return data[access_role]['resources']['environment_variables']