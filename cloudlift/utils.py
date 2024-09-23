import re
from stringcase import pascalcase
from cloudlift.exceptions import UnrecoverableException

def generate_pascalcase_name(name: str, max_length: int = 32) -> str:
    pascal_case = pascalcase(name)
    pascalcase_name = re.sub(r"[\W_]+", "", pascal_case)
    if len(pascalcase_name) > max_length:
        raise UnrecoverableException(
            f"Name {name} is too long. Max length is {max_length}, got pascalcase length of {len(pascalcase_name)}"
        )
    return pascalcase_name
