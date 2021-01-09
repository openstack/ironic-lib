# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# Copyright (c) 2012 NTT DOCOMO, INC.
# All Rights Reserved.
#
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

"""Utilities and helper functions."""

import contextlib
import copy
import errno
import ipaddress
import logging
import os
import re
import shutil
import tempfile
from urllib import parse as urlparse

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import specs_matcher
from oslo_utils import strutils
from oslo_utils import units
import tenacity

from ironic_lib.common.i18n import _
from ironic_lib import exception

utils_opts = [
    cfg.StrOpt('root_helper',
               default='sudo ironic-rootwrap /etc/ironic/rootwrap.conf',
               help='Command that is prefixed to commands that are run as '
                    'root. If not specified, no commands are run as root.'),
]

CONF = cfg.CONF
CONF.register_opts(utils_opts, group='ironic_lib')

LOG = logging.getLogger(__name__)

# A dictionary in the form {hint name: hint type}
VALID_ROOT_DEVICE_HINTS = {
    'size': int, 'model': str, 'wwn': str, 'serial': str, 'vendor': str,
    'wwn_with_extension': str, 'wwn_vendor_extension': str, 'name': str,
    'rotational': bool, 'hctl': str, 'by_path': str,
}


ROOT_DEVICE_HINTS_GRAMMAR = specs_matcher.make_grammar()


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    :param cmd: positional arguments to pass to processutils.execute()
    :param use_standard_locale: keyword-only argument. True | False.
                                Defaults to False. If set to True,
                                execute command with standard locale
                                added to environment variables.
    :param log_stdout: keyword-only argument. True | False. Defaults
                       to True. If set to True, logs the output.
    :param kwargs: keyword arguments to pass to processutils.execute()
    :returns: (stdout, stderr) from process execution
    :raises: UnknownArgumentError on receiving unknown arguments
    :raises: ProcessExecutionError
    :raises: OSError
    """

    use_standard_locale = kwargs.pop('use_standard_locale', False)
    if use_standard_locale:
        env = kwargs.pop('env_variables', os.environ.copy())
        env['LC_ALL'] = 'C'
        kwargs['env_variables'] = env

    log_stdout = kwargs.pop('log_stdout', True)

    # If root_helper config is not specified, no commands are run as root.
    run_as_root = kwargs.get('run_as_root', False)
    if run_as_root:
        if not CONF.ironic_lib.root_helper:
            kwargs['run_as_root'] = False
        else:
            kwargs['root_helper'] = CONF.ironic_lib.root_helper

    result = processutils.execute(*cmd, **kwargs)
    LOG.debug('Execution completed, command line is "%s"',
              ' '.join(map(str, cmd)))
    if log_stdout:
        LOG.debug('Command stdout is: "%s"', result[0])
    LOG.debug('Command stderr is: "%s"', result[1])
    return result


def try_execute(*cmd, **kwargs):
    """The same as execute but returns None on error.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    Instead of raising an exception on failure, this method simply
    returns None in case of failure.

    :param cmd: positional arguments to pass to processutils.execute()
    :param kwargs: keyword arguments to pass to processutils.execute()
    :raises: UnknownArgumentError on receiving unknown arguments
    :returns: tuple of (stdout, stderr) or None in some error cases
    """
    try:
        return execute(*cmd, **kwargs)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.debug('Command failed: %s', e)


def mkfs(fs, path, label=None):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        args = ['mkswap']
    else:
        args = ['mkfs', '-t', fs]
    # add -F to force no interactive execute on non-block device.
    if fs in ('ext3', 'ext4'):
        args.extend(['-F'])
    if label:
        if fs in ('msdos', 'vfat'):
            label_opt = '-n'
        else:
            label_opt = '-L'
        args.extend([label_opt, label])
    args.append(path)
    try:
        execute(*args, run_as_root=True, use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        with excutils.save_and_reraise_exception() as ctx:
            if os.strerror(errno.ENOENT) in e.stderr:
                ctx.reraise = False
                LOG.exception('Failed to make file system. '
                              'File system %s is not supported.', fs)
                raise exception.FileSystemNotSupported(fs=fs)
            else:
                LOG.exception('Failed to create a file system '
                              'in %(path)s. Error: %(error)s',
                              {'path': path, 'error': e})


def unlink_without_raise(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return
        else:
            LOG.warning("Failed to unlink %(path)s, error: %(e)s",
                        {'path': path, 'e': e})


def dd(src, dst, *args):
    """Execute dd from src to dst.

    :param src: the input file for dd command.
    :param dst: the output file for dd command.
    :param args: a tuple containing the arguments to be
        passed to dd command.
    :raises: processutils.ProcessExecutionError if it failed
        to run the process.
    """
    LOG.debug("Starting dd process.")
    execute('dd', 'if=%s' % src, 'of=%s' % dst, *args,
            use_standard_locale=True, run_as_root=True, check_exit_code=[0])


def is_http_url(url):
    url = url.lower()
    return url.startswith('http://') or url.startswith('https://')


def list_opts():
    """Entry point for oslo-config-generator."""
    return [('ironic_lib', utils_opts)]


def _extract_hint_operator_and_values(hint_expression, hint_name):
    """Extract the operator and value(s) of a root device hint expression.

    A root device hint expression could contain one or more values
    depending on the operator. This method extracts the operator and
    value(s) and returns a dictionary containing both.

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A dictionary containing:

        :op: The operator. An empty string in case of None.
        :values: A list of values stripped and converted to lowercase.
    """
    expression = str(hint_expression).strip().lower()
    if not expression:
        raise ValueError(
            _('Root device hint "%s" expression is empty') % hint_name)

    # parseString() returns a list of tokens which the operator (if
    # present) is always the first element.
    ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
    if len(ast) <= 1:
        # hint_expression had no operator
        return {'op': '', 'values': [expression]}

    op = ast[0]
    return {'values': [v.strip() for v in re.split(op, expression) if v],
            'op': op}


def _normalize_hint_expression(hint_expression, hint_name):
    """Normalize a string type hint expression.

    A string-type hint expression contains one or more operators and
    one or more values: [<op>] <value> [<op> <value>]*. This normalizes
    the values by url-encoding white spaces and special characters. The
    operators are not normalized. For example: the hint value of "<or>
    foo bar <or> bar" will become "<or> foo%20bar <or> bar".

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A normalized string.
    """
    hdict = _extract_hint_operator_and_values(hint_expression, hint_name)
    result = hdict['op'].join([' %s ' % urlparse.quote(t)
                               for t in hdict['values']])
    return (hdict['op'] + result).strip()


def _append_operator_to_hints(root_device):
    """Add an equal (s== or ==) operator to the hints.

    For backwards compatibility, for root device hints where no operator
    means equal, this method adds the equal operator to the hint. This is
    needed when using oslo.utils.specs_matcher methods.

    :param root_device: The root device hints dictionary.
    """
    for name, expression in root_device.items():
        # NOTE(lucasagomes): The specs_matcher from oslo.utils does not
        # support boolean, so we don't need to append any operator
        # for it.
        if VALID_ROOT_DEVICE_HINTS[name] is bool:
            continue

        expression = str(expression)
        ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
        if len(ast) > 1:
            continue

        op = 's== %s' if VALID_ROOT_DEVICE_HINTS[name] is str else '== %s'
        root_device[name] = op % expression

    return root_device


def parse_root_device_hints(root_device):
    """Parse the root_device property of a node.

    Parses and validates the root_device property of a node. These are
    hints for how a node's root device is created. The 'size' hint
    should be a positive integer. The 'rotational' hint should be a
    Boolean value.

    :param root_device: the root_device dictionary from the node's property.
    :returns: a dictionary with the root device hints parsed or
              None if there are no hints.
    :raises: ValueError, if some information is invalid.

    """
    if not root_device:
        return

    root_device = copy.deepcopy(root_device)

    invalid_hints = set(root_device) - set(VALID_ROOT_DEVICE_HINTS)
    if invalid_hints:
        raise ValueError(
            _('The hints "%(invalid_hints)s" are invalid. '
              'Valid hints are: "%(valid_hints)s"') %
            {'invalid_hints': ', '.join(invalid_hints),
             'valid_hints': ', '.join(VALID_ROOT_DEVICE_HINTS)})

    for name, expression in root_device.items():
        hint_type = VALID_ROOT_DEVICE_HINTS[name]
        if hint_type is str:
            if not isinstance(expression, str):
                raise ValueError(
                    _('Root device hint "%(name)s" is not a string value. '
                      'Hint expression: %(expression)s') %
                    {'name': name, 'expression': expression})
            root_device[name] = _normalize_hint_expression(expression, name)

        elif hint_type is int:
            for v in _extract_hint_operator_and_values(expression,
                                                       name)['values']:
                try:
                    integer = int(v)
                except ValueError:
                    raise ValueError(
                        _('Root device hint "%(name)s" is not an integer '
                          'value. Current value: %(expression)s') %
                        {'name': name, 'expression': expression})

                if integer <= 0:
                    raise ValueError(
                        _('Root device hint "%(name)s" should be a positive '
                          'integer. Current value: %(expression)s') %
                        {'name': name, 'expression': expression})

        elif hint_type is bool:
            try:
                root_device[name] = strutils.bool_from_string(
                    expression, strict=True)
            except ValueError:
                raise ValueError(
                    _('Root device hint "%(name)s" is not a Boolean value. '
                      'Current value: %(expression)s') %
                    {'name': name, 'expression': expression})

    return _append_operator_to_hints(root_device)


def find_devices_by_hints(devices, root_device_hints):
    """Find all devices that match the root device hints.

    Try to find devices that match the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String) Device serial number
        :wwn: (String) Unique storage identifier
        :wwn_with_extension: (String): Unique storage identifier with
                             the vendor extension appended
        :wwn_vendor_extension: (String): United vendor storage identifier
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: A generator with all matching devices as dictionaries.
    """
    LOG.debug('Trying to find devices from "%(devs)s" that match the '
              'device hints "%(hints)s"',
              {'devs': ', '.join([d.get('name') for d in devices]),
               'hints': root_device_hints})
    parsed_hints = parse_root_device_hints(root_device_hints)
    for dev in devices:
        device_name = dev.get('name')

        for hint in parsed_hints:
            hint_type = VALID_ROOT_DEVICE_HINTS[hint]
            device_value = dev.get(hint)
            hint_value = parsed_hints[hint]

            if hint_type is str:
                try:
                    device_value = _normalize_hint_expression(device_value,
                                                              hint)
                except ValueError:
                    LOG.warning(
                        'The attribute "%(attr)s" of the device "%(dev)s" '
                        'has an empty value. Skipping device.',
                        {'attr': hint, 'dev': device_name})
                    break

            if hint == 'size':
                # Since we don't support units yet we expect the size
                # in GiB for now
                device_value = device_value / units.Gi

            LOG.debug('Trying to match the device hint "%(hint)s" '
                      'with a value of "%(hint_value)s" against the same '
                      'device\'s (%(dev)s) attribute with a value of '
                      '"%(dev_value)s"', {'hint': hint, 'dev': device_name,
                                          'hint_value': hint_value,
                                          'dev_value': device_value})

            # NOTE(lucasagomes): Boolean hints are not supported by
            # specs_matcher.match(), so we need to do the comparison
            # ourselves
            if hint_type is bool:
                try:
                    device_value = strutils.bool_from_string(device_value,
                                                             strict=True)
                except ValueError:
                    LOG.warning('The attribute "%(attr)s" (with value '
                                '"%(value)s") of device "%(dev)s" is not '
                                'a valid Boolean. Skipping device.',
                                {'attr': hint, 'value': device_value,
                                 'dev': device_name})
                    break
                if device_value == hint_value:
                    continue

            elif specs_matcher.match(device_value, hint_value):
                continue

            LOG.debug('The attribute "%(attr)s" (with value "%(value)s") '
                      'of device "%(dev)s" does not match the hint %(hint)s',
                      {'attr': hint, 'value': device_value,
                       'dev': device_name, 'hint': hint_value})
            break
        else:
            yield dev


def match_root_device_hints(devices, root_device_hints):
    """Try to find a device that matches the root device hints.

    Try to find a device that matches the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String) Device serial number
        :wwn: (String) Unique storage identifier
        :wwn_with_extension: (String): Unique storage identifier with
                             the vendor extension appended
        :wwn_vendor_extension: (String): United vendor storage identifier
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: The first device to match all the hints or None.
    """
    try:
        dev = next(find_devices_by_hints(devices, root_device_hints))
    except StopIteration:
        LOG.warning('No device found that matches the root device hints %s',
                    root_device_hints)
    else:
        LOG.info('Root device found! The device "%s" matches the root '
                 'device hints %s', dev, root_device_hints)
        return dev


def wait_for_disk_to_become_available(device):
    """Wait for a disk device to become available.

    Waits for a disk device to become available for use by
    waiting until all process locks on the device have been
    released.

    Timeout and iteration settings come from the configuration
    options used by the in-library disk_partitioner:
    ``check_device_interval`` and ``check_device_max_retries``.

    :params device: The path to the device.
    :raises: IronicException If the disk fails to become
        available.
    """
    pids = ['']
    stderr = ['']
    interval = CONF.disk_partitioner.check_device_interval
    max_retries = CONF.disk_partitioner.check_device_max_retries

    def _wait_for_disk():
        # A regex is likely overkill here, but variations in fuser
        # means we should likely use it.
        fuser_pids_re = re.compile(r'\d+')

        # There are 'psmisc' and 'busybox' versions of the 'fuser' program. The
        # 'fuser' programs differ in how they output data to stderr.  The
        # busybox version does not output the filename to stderr, while the
        # standard 'psmisc' version does output the filename to stderr.  How
        # they output to stdout is almost identical in that only the PIDs are
        # output to stdout, with the 'psmisc' version adding a leading space
        # character to the list of PIDs.
        try:
            # NOTE(ifarkas): fuser returns a non-zero return code if none of
            #                the specified files is accessed.
            # NOTE(TheJulia): fuser does not report LVM devices as in use
            #                 unless the LVM device-mapper device is the
            #                 device that is directly polled.
            # NOTE(TheJulia): The -m flag allows fuser to reveal data about
            #                 mounted filesystems, which should be considered
            #                 busy/locked. That being said, it is not used
            #                 because busybox fuser has a different behavior.
            # NOTE(TheJuia): fuser outputs a list of found PIDs to stdout.
            #                All other text is returned via stderr, and the
            #                output to a terminal is merged as a result.
            out, err = execute('fuser', device, check_exit_code=[0, 1],
                               run_as_root=True)

            if not out and not err:
                return True

            stderr[0] = err
            # NOTE: findall() returns a list of matches, or an empty list if no
            # matches
            pids[0] = fuser_pids_re.findall(out)

        except processutils.ProcessExecutionError as exc:
            LOG.warning('Failed to check the device %(device)s with fuser:'
                        ' %(err)s', {'device': device, 'err': exc})
        return False

    retry = tenacity.retry(
        retry=tenacity.retry_if_result(lambda r: not r),
        stop=tenacity.stop_after_attempt(max_retries),
        wait=tenacity.wait_fixed(interval),
        reraise=True)
    try:
        retry(_wait_for_disk)()
    except tenacity.RetryError:
        if pids[0]:
            raise exception.IronicException(
                _('Processes with the following PIDs are holding '
                  'device %(device)s: %(pids)s. '
                  'Timed out waiting for completion.')
                % {'device': device, 'pids': ', '.join(pids[0])})
        else:
            raise exception.IronicException(
                _('Fuser exited with "%(fuser_err)s" while checking '
                  'locks for device %(device)s. Timed out waiting for '
                  'completion.')
                % {'device': device, 'fuser_err': stderr[0]})


def get_route_source(dest, ignore_link_local=True):
    """Get the IP address to send packages to destination."""
    try:
        out, _err = execute('ip', 'route', 'get', dest)
    except (EnvironmentError, processutils.ProcessExecutionError) as e:
        LOG.warning('Cannot get route to host %(dest)s: %(err)s',
                    {'dest': dest, 'err': e})
        return

    try:
        source = out.strip().split('\n')[0].split('src')[1].split()[0]
        if (ipaddress.ip_address(source).is_link_local
                and ignore_link_local):
            LOG.debug('Ignoring link-local source to %(dest)s: %(rec)s',
                      {'dest': dest, 'rec': out})
            return
        return source
    except (IndexError, ValueError):
        LOG.debug('No route to host %(dest)s, route record: %(rec)s',
                  {'dest': dest, 'rec': out})


@contextlib.contextmanager
def mounted(source, dest=None, opts=None, fs_type=None):
    """A context manager for a temporary mount.

    :param source: A device to mount.
    :param dest: Mount destination. If not specified, a temporary directory
        will be created and removed afterwards. An existing destination is
        not removed.
    :param opts: Mount options (``-o`` argument).
    :param fs_type: File system type (``-t`` argument).
    :returns: A generator yielding the destination.
    """
    params = []
    if opts:
        params.extend(['-o', ','.join(opts)])
    if fs_type:
        params.extend(['-t', fs_type])

    if dest is None:
        dest = tempfile.mkdtemp()
        clean_up = True
    else:
        clean_up = False

    mounted = False
    try:
        execute("mount", source, dest, *params, run_as_root=True)
        mounted = True
        yield dest
    finally:
        if mounted:
            try:
                execute("umount", dest, run_as_root=True)
            except (EnvironmentError,
                    processutils.ProcessExecutionError) as exc:
                LOG.warning(
                    'Unable to unmount temporary location %(dest)s: %(err)s',
                    {'dest': dest, 'err': exc})
                # NOTE(dtantsur): don't try to remove a still mounted location
                clean_up = False

        if clean_up:
            try:
                shutil.rmtree(dest)
            except EnvironmentError as exc:
                LOG.warning(
                    'Unable to remove temporary location %(dest)s: %(err)s',
                    {'dest': dest, 'err': exc})
