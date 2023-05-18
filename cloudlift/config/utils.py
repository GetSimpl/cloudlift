"""
utilities for handling malformed JSON configurations
"""

import json
import os
import tempfile
import copy
from click import confirm, edit, style

from cloudlift.config import DecimalEncoder
from cloudlift.version import VERSION
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.logging import log_bold, log_err, log_warning
from cloudlift.config import DecimalEncoder, print_json_changes



class ConfigUtils:
    def __init__(self, current_configuration=None, changes_validation_function=None):
        self.current_configuration = current_configuration
        self.changes_validation_function = changes_validation_function
        self.temp_file = None
        self.inject_version = False

    def fault_tolerant_edit_config(self, current_configuration=None, changes_validation_function=None, inject_version=False):
        if current_configuration:
            self.current_configuration = current_configuration
        if changes_validation_function:
            self.changes_validation_function = changes_validation_function
        if inject_version:
            self.inject_version = inject_version
        updated_configuration = edit(
            json.dumps(
                self.current_configuration,
                indent=4,
                sort_keys=True,
                cls=DecimalEncoder
            )
        )
        if updated_configuration is None:
            log_warning("No changes made.")
        else:
            try:
                updated_configuration = json.loads(updated_configuration)
            except json.JSONDecodeError as error:
                return self._handle_json_decode_error(updated_configuration)

            try:
                self._validate_schema(updated_configuration)
            except UnrecoverableException as error:
                log_err(str(error))
                choice = confirm("The faulty configuration has been saved temporarily. Would you like to reopen it for editing?")
                if choice:
                    return self._edit_temp_config(updated_configuration)
                return

        return updated_configuration

    def _validate_schema(self, configuration):
        config_to_validate = copy.deepcopy(configuration)
        if self.inject_version:
            config_to_validate['cloudlift_version'] = VERSION
        self.changes_validation_function(config_to_validate)
        

    def _get_temp_config_file_name(self):
        prefix = f"temp_config_{VERSION}_"
        suffix = ".json"
        temp_dir = tempfile.gettempdir()
        temp_file = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=temp_dir)
        self.temp_file = temp_file[1]
        os.close(temp_file[0])
        return self.temp_file

    def _edit_temp_config(self, updated_configuration):
        temp_file = self.temp_file or self._get_temp_config_file_name()

        if updated_configuration is not None and not os.path.getsize(temp_file) > 0:
            with open(temp_file, "w") as file:
                if isinstance(updated_configuration, str):
                    file.write(updated_configuration)
                else:
                    file.write(
                        json.dumps(
                            updated_configuration, indent=4, sort_keys=True, cls=DecimalEncoder
                        )
                    )

        edit_status = edit(filename=temp_file)

        if edit_status and edit_status != 0:
            log_err("Error occurred while editing the configuration. Changes aborted.")
            return

        tmp_file_content = open(temp_file, "r").read()

        try:
            updated_configuration = json.loads(tmp_file_content)
        except (json.JSONDecodeError, TypeError):
            return self._handle_json_decode_error(tmp_file_content)

        return self._edit_config_with_temp_changes(updated_configuration)

    def _edit_config_with_temp_changes(self, updated_configuration):
        try:
            self._validate_schema(updated_configuration)
        except UnrecoverableException as error:
            log_err(str(error))
            choice = confirm("The faulty configuration has been saved temporarily. Would you like to reopen it for editing?")
            if choice:
                return self._edit_temp_config(updated_configuration)
            return

        return updated_configuration

    def _handle_json_decode_error(self, updated_configuration):
        try:
            json.loads(updated_configuration)  # Validate JSON to get detailed error message
        except json.JSONDecodeError as error:
            error_details = f"Error in the JSON configuration: {error.msg} (line {error.lineno}, column {error.colno})"
            log_err("\n" + error_details)

            if isinstance(updated_configuration, str):
                highlighted_config, error_line = self._highlight_error_location(
                    updated_configuration, error.lineno, error.colno
                )
                log_err(f"Invalid JSON content:\n{highlighted_config}")
            else:
                highlighted_config, error_line = self._highlight_error_location(
                    json.dumps(updated_configuration, indent=4, sort_keys=True, cls=DecimalEncoder),
                    error.lineno,
                    error.colno,
                )
                log_err(f"Invalid JSON configuration:\n{highlighted_config}")

            line_number = error.lineno
            line = self._get_line_by_number(updated_configuration, line_number)
            log_err(f"Error occurred in line {line_number}: {line}")

            choice = confirm(
                "The faulty configuration has been saved temporarily. Would you like to reopen it for editing?"
            )
            if choice:
                return self._edit_temp_config(updated_configuration)


    def _highlight_error_location(self, json_content, error_line, error_column):
        lines = json_content.splitlines()
        line_numbers = range(1, len(lines) + 1)
        highlighted_lines = []
        for line_number, line in zip(line_numbers, lines):
            highlighted_line = line
            if line_number == error_line:
                highlighted_line = self._highlight_error_position(line, error_column)
            highlighted_lines.append((line_number, highlighted_line))
        return (
            "\n".join(
                [
                    f"{line_number}: {line_content}"
                    for line_number, line_content in highlighted_lines
                ]
            ),
            lines[error_line - 1],
        )


    def _highlight_error_position(self, line, error_column):
        highlighted_line = ""
        for i, char in enumerate(line):
            if i == error_column - 1:
                highlighted_line += style(char, fg="red")
            else:
                highlighted_line += char
        return highlighted_line


    def _get_line_by_number(self, content, line_number):
        lines = content.splitlines()
        if 1 <= line_number <= len(lines):
            return lines[line_number - 1]
        return ""
