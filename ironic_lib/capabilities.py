#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Code for working with capabilities."""

import json
import logging

from ironic_lib.common.i18n import _

LOG = logging.getLogger(__name__)


def _parse_old_format(cap_str, skip_malformed=True):
    """Extract capabilities from string.

    :param cap_str: A string in the key1:value1,key2:value2 format.
    :param skip_malformed: Whether to skip malformed items or raise ValueError.
    :return: a dictionary
    """
    capabilities = {}

    for node_capability in cap_str.split(','):
        parts = node_capability.split(':', 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            capabilities[parts[0]] = parts[1]
        else:
            if skip_malformed:
                LOG.warning("Ignoring malformed capability '%s'. "
                            "Format should be 'key:val'.", node_capability)
            else:
                raise ValueError(
                    _("Malformed capability %s. Format should be 'key:val'")
                    % node_capability)

    return capabilities


def parse(capabilities, compat=True, skip_malformed=False):
    """Extract capabilities from provided object.

    The capabilities value can either be a dict, or a json str, or
    a key1:value1,key2:value2 formatted string (if compat is True).
    If None, an empty dictionary is returned.

    :param capabilities: The capabilities value. Can either be a dict, or
                         a json str, or a key1:value1,key2:value2 formatted
                         string (if compat is True).
    :param compat: Whether to parse the old format key1:value1,key2:value2.
    :param skip_malformed: Whether to skip malformed items or raise ValueError.
    :returns: A dictionary with the capabilities if found and well formatted,
              otherwise an empty dictionary.
    :raises: TypeError if the capabilities are of invalid type.
    :raises: ValueError on a malformed capability if skip_malformed is False
             or on invalid JSON with compat is False.
    """
    if capabilities is None:
        return {}
    elif isinstance(capabilities, str):
        try:
            return json.loads(capabilities)
        except (ValueError, TypeError) as exc:
            if compat:
                return _parse_old_format(capabilities,
                                         skip_malformed=skip_malformed)
            else:
                raise ValueError(
                    _('Invalid JSON capabilities %(value)s: %(error)s')
                    % {'value': capabilities, 'error': exc})
    elif not isinstance(capabilities, dict):
        raise TypeError(
            _('Invalid capabilities, expected a string or a dict, got %s')
            % capabilities)
    else:
        return capabilities


def combine(capabilities_dict, skip_none=False):
    """Combine capabilities into the old format.

    :param capabilities_dict: Capabilities as a mapping.
    :param skip_none: If True, skips all items with value of None.
    :returns: Capabilities as a string key1:value1,key2:value2.
    """
    return ','.join(["%s:%s" % (key, value)
                     for key, value in capabilities_dict.items()
                     if not skip_none or value is not None])


def update_and_combine(capabilities, new_values, skip_malformed=False,
                       skip_none=False):
    """Parses capabilities, updated them with new values and re-combines.

    :param capabilities: The capabilities value. Can either be a dict, or
                         a json str, or a key1:value1,key2:value2 formatted
                         string (if compat is True).
    :param new_values: New values as a dictionary.
    :param skip_malformed: Whether to skip malformed items or raise ValueError.
    :param skip_none: If True, skips all items with value of None.
    :returns: Capabilities in the old format (key1:value1,key2:value2).
    :raises: TypeError if the capabilities are of invalid type.
    :raises: ValueError on a malformed capability if skip_malformed is False.
    """
    if not isinstance(new_values, dict):
        raise TypeError(
            _("Cannot update capabilities. The new capabilities should be in "
              "a dictionary. Provided value is %s") % new_values)

    capabilities = parse(capabilities, skip_malformed=skip_malformed)
    capabilities.update(new_values)
    return combine(capabilities, skip_none=skip_none)
