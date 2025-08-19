"""
Test utility helper functions.

This module contains utility functions that are shared across multiple test files.
"""


import copy


def flatten_dict(d, parent_key="", sep="."):
    """
    Flatten a nested dictionary, joining keys with a specified separator.

    This function does not modify the original dictionary. It creates a deep copy
    of the dictionary before flattening.

    Args:
        d (dict): The dictionary to flatten.
        parent_key (str, optional): The base key to start with. Defaults to ''.
        sep (str, optional): The separator to use when joining keys. Defaults to '.'.

    Returns:
        dict: A flattened dictionary where nested keys are joined by the separator.

    Example:
        >>> flatten_dict({'a': 1, 'b': {'c': 2, 'd': {'e': 3}}})
        {'a': 1, 'b.c': 2, 'b.d.e': 3}

        >>> flatten_dict({'a': 1, 'b': {'c': 2}}, parent_key='config', sep='/')
        {'config/a': 1, 'config/b/c': 2}
    """
    d = copy.deepcopy(d)  # Make a deep copy to avoid mutating the original dictionary
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
