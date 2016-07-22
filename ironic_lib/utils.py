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

import copy
import errno
import logging
import os

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import strutils

from ironic_lib.common.i18n import _
from ironic_lib.common.i18n import _LE
from ironic_lib.common.i18n import _LW
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


VALID_ROOT_DEVICE_HINTS = set(('size', 'model', 'wwn', 'serial', 'vendor',
                               'wwn_with_extension', 'wwn_vendor_extension',
                               'name', 'rotational'))


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    :param \*cmd: positional arguments to pass to processutils.execute()
    :param use_standard_locale: keyword-only argument. True | False.
                                Defaults to False. If set to True,
                                execute command with standard locale
                                added to environment variables.
    :param log_stdout: keyword-only argument. True | False. Defaults
                       to True. If set to True, logs the output.
    :param \*\*kwargs: keyword arguments to pass to processutils.execute()
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
        LOG.debug('Command stdout is: "%s"' % result[0])
    LOG.debug('Command stderr is: "%s"' % result[1])
    return result


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
                LOG.exception(_LE('Failed to make file system. '
                                  'File system %s is not supported.'), fs)
                raise exception.FileSystemNotSupported(fs=fs)
            else:
                LOG.exception(_LE('Failed to create a file system '
                                  'in %(path)s. Error: %(error)s'),
                              {'path': path, 'error': e})


def unlink_without_raise(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return
        else:
            LOG.warning(_LW("Failed to unlink %(path)s, error: %(e)s"),
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

    invalid_hints = set(root_device) - VALID_ROOT_DEVICE_HINTS
    if invalid_hints:
        raise ValueError(
            _('The hints "%(invalid_hints)s" are invalid. '
              'Valid hints are: "%(valid_hints)s"') %
            {'invalid_hints': ', '.join(invalid_hints),
             'valid_hints': ', '.join(VALID_ROOT_DEVICE_HINTS)})

    if 'size' in root_device:
        try:
            size = int(root_device['size'])
        except ValueError:
            raise ValueError(
                _('Root device hint "size" is not an integer value. '
                  'Current value: %s') % root_device['size'])

        if size <= 0:
            raise ValueError(
                _('Root device hint "size" should be a positive integer. '
                  'Current value: %d') % size)

        root_device['size'] = size

    if 'rotational' in root_device:
        try:
            root_device['rotational'] = strutils.bool_from_string(
                root_device['rotational'], strict=True)
        except ValueError:
            raise ValueError(
                _('Root device hint "rotational" is not a Boolean value. '
                  'Current value: %s') % root_device['rotational'])

    return root_device
