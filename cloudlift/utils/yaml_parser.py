from pathlib import Path
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

def config_keys(access_role, access_file):
    data = yaml.load(Path(access_file))
    return data[access_role]['resources']['environment_variables']