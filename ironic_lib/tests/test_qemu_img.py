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

import os
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils

from ironic_lib import qemu_img
from ironic_lib.tests import base
from ironic_lib import utils

CONF = cfg.CONF


class ImageInfoTestCase(base.IronicLibTestCase):

    @mock.patch.object(os.path, 'exists', return_value=False, autospec=True)
    def test_image_info_path_doesnt_exist(self, path_exists_mock):
        self.assertRaises(FileNotFoundError, qemu_img.image_info, 'noimg')
        path_exists_mock.assert_called_once_with('noimg')

    @mock.patch.object(utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    @mock.patch.object(imageutils, 'QemuImgInfo', autospec=True)
    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test_image_info_path_exists(self, path_exists_mock,
                                    image_info_mock, execute_mock):
        qemu_img.image_info('img')
        path_exists_mock.assert_called_once_with('img')
        execute_mock.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', 'img',
                                             '--output=json',
                                             prlimit=mock.ANY)
        image_info_mock.assert_called_once_with('out', format='json')


class ConvertImageTestCase(base.IronicLibTestCase):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image(self, execute_mock):
        qemu_img.convert_image('source', 'dest', 'out_format')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', 'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_flags(self, execute_mock):
        qemu_img.convert_image('source', 'dest', 'out_format',
                               cache='directsync', out_of_order=True,
                               sparse_size='0')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', '-t', 'directsync',
            '-S', '0', '-W', 'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries(self, execute_mock):
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_alternate_error(self, execute_mock):
        ret_err = 'Failed to allocate memory: Cannot allocate memory\n'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_and_fails(self, execute_mock):
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_just_fails(self, execute_mock):
        ret_err = 'Aliens'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
        ])
