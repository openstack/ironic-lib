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

import logging
import os

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils
from oslo_utils import units
import tenacity

from ironic_lib.common.i18n import _
from ironic_lib import utils


opts = [
    cfg.IntOpt('image_convert_memory_limit',
               default=2048,
               help='Memory limit for "qemu-img convert" in MiB. Implemented '
                    'via the address space resource limit.'),
    cfg.IntOpt('image_convert_attempts',
               default=3,
               help='Number of attempts to convert an image.'),
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(opts, group='disk_utils')

# Limit the memory address space to 1 GiB when running qemu-img
QEMU_IMG_LIMITS = None


def _qemu_img_limits():
    global QEMU_IMG_LIMITS
    if QEMU_IMG_LIMITS is None:
        QEMU_IMG_LIMITS = processutils.ProcessLimits(
            address_space=CONF.disk_utils.image_convert_memory_limit
            * units.Mi)
    return QEMU_IMG_LIMITS


def _retry_on_res_temp_unavailable(exc):
    if (isinstance(exc, processutils.ProcessExecutionError)
            and ('Resource temporarily unavailable' in exc.stderr
                 or 'Cannot allocate memory' in exc.stderr)):
        return True
    return False


def image_info(path):
    """Return an object containing the parsed output from qemu-img info."""
    if not os.path.exists(path):
        raise FileNotFoundError(_("File %s does not exist") % path)

    out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
                             'qemu-img', 'info', path,
                             '--output=json',
                             prlimit=_qemu_img_limits())
    return imageutils.QemuImgInfo(out, format='json')


@tenacity.retry(
    retry=tenacity.retry_if_exception(_retry_on_res_temp_unavailable),
    stop=tenacity.stop_after_attempt(CONF.disk_utils.image_convert_attempts),
    reraise=True)
def convert_image(source, dest, out_format, run_as_root=False, cache=None,
                  out_of_order=False, sparse_size=None):
    """Convert image to other format."""
    cmd = ['qemu-img', 'convert', '-O', out_format]
    if cache is not None:
        cmd += ['-t', cache]
    if sparse_size is not None:
        cmd += ['-S', sparse_size]
    if out_of_order:
        cmd.append('-W')
    cmd += [source, dest]
    # NOTE(TheJulia): Statically set the MALLOC_ARENA_MAX to prevent leaking
    # and the creation of new malloc arenas which will consume the system
    # memory. If limited to 1, qemu-img consumes ~250 MB of RAM, but when
    # another thread tries to access a locked section of memory in use with
    # another thread, then by default a new malloc arena is created,
    # which essentially balloons the memory requirement of the machine.
    # Default for qemu-img is 8 * nCPU * ~250MB (based on defaults +
    # thread/code/process/library overhead. In other words, 64 GB. Limiting
    # this to 3 keeps the memory utilization in happy cases below the overall
    # threshold which is in place in case a malicious image is attempted to
    # be passed through qemu-img.
    env_vars = {'MALLOC_ARENA_MAX': '3'}
    try:
        utils.execute(*cmd, run_as_root=run_as_root,
                      prlimit=_qemu_img_limits(),
                      use_standard_locale=True,
                      env_variables=env_vars)
    except processutils.ProcessExecutionError as e:
        if ('Resource temporarily unavailable' in e.stderr
            or 'Cannot allocate memory' in e.stderr):
            LOG.debug('Failed to convert image, retrying. Error: %s', e)
            # Sync disk caches before the next attempt
            utils.execute('sync')
        raise


def list_opts():
    """Entry point for oslo-config-generator."""
    return [('disk_utils', opts)]
