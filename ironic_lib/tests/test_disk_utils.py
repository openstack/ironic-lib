# Copyright 2014 Red Hat, Inc.
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

import base64
import gzip
import mock
import os
import shutil
import stat
import tempfile


from oslo_concurrency import processutils
from oslo_config import cfg
from oslotest import base as test_base
import requests

from ironic_lib import disk_partitioner
from ironic_lib import disk_utils
from ironic_lib import exception
from ironic_lib import utils

CONF = cfg.CONF


@mock.patch.object(utils, 'execute')
class ListPartitionsTestCase(test_base.BaseTestCase):

    def test_correct(self, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:1.00MiB:501MiB:500MiB:ext4::boot;
2:501MiB:476940MiB:476439MiB:::;
"""
        expected = [
            {'number': 1, 'start': 1, 'end': 501, 'size': 500,
             'filesystem': 'ext4', 'flags': 'boot'},
            {'number': 2, 'start': 501, 'end': 476940, 'size': 476439,
             'filesystem': '', 'flags': ''},
        ]
        execute_mock.return_value = (output, '')
        result = disk_utils.list_partitions('/dev/fake')
        self.assertEqual(expected, result)
        execute_mock.assert_called_once_with(
            'parted', '-s', '-m', '/dev/fake', 'unit', 'MiB', 'print',
            use_standard_locale=True, run_as_root=True)

    @mock.patch.object(disk_utils.LOG, 'warn')
    def test_incorrect(self, log_mock, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:XX1076MiB:---:524MiB:ext4::boot;
"""
        execute_mock.return_value = (output, '')
        self.assertEqual([], disk_utils.list_partitions('/dev/fake'))
        self.assertEqual(1, log_mock.call_count)


@mock.patch.object(disk_partitioner.DiskPartitioner, 'commit', lambda _: None)
class WorkOnDiskTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(WorkOnDiskTestCase, self).setUp()
        self.image_path = '/tmp/xyz/image'
        self.root_mb = 128
        self.swap_mb = 64
        self.ephemeral_mb = 0
        self.ephemeral_format = None
        self.configdrive_mb = 0
        self.dev = '/dev/fake'
        self.swap_part = '/dev/fake-part1'
        self.root_part = '/dev/fake-part2'

        self.mock_ibd_obj = mock.patch.object(
            disk_utils, 'is_block_device', autospec=True)
        self.mock_ibd = self.mock_ibd_obj.start()
        self.addCleanup(self.mock_ibd_obj.stop)
        self.mock_mp_obj = mock.patch.object(
            disk_utils, 'make_partitions', autospec=True)
        self.mock_mp = self.mock_mp_obj.start()
        self.addCleanup(self.mock_mp_obj.stop)
        self.mock_remlbl_obj = mock.patch.object(
            disk_utils, 'destroy_disk_metadata', autospec=True)
        self.mock_remlbl = self.mock_remlbl_obj.start()
        self.addCleanup(self.mock_remlbl_obj.stop)
        self.mock_mp.return_value = {'swap': self.swap_part,
                                     'root': self.root_part}

    def test_no_root_partition(self):
        self.mock_ibd.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid')
        self.mock_ibd.assert_called_once_with(self.root_part)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    def test_no_swap_partition(self):
        self.mock_ibd.side_effect = iter([True, False])
        calls = [mock.call(self.root_part),
                 mock.call(self.swap_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid')
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    def test_no_ephemeral_partition(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, ephemeral_mb, ephemeral_format,
                          self.image_path, 'fake-uuid')
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    @mock.patch.object(utils, 'unlink_without_raise')
    @mock.patch.object(disk_utils, '_get_configdrive')
    def test_no_configdrive_partition(self, mock_configdrive, mock_unlink):
        mock_configdrive.return_value = (10, 'fake-path')
        swap_part = '/dev/fake-part1'
        configdrive_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        configdrive_url = 'http://1.2.3.4/cd'
        configdrive_mb = 10

        self.mock_mp.return_value = {'swap': swap_part,
                                     'configdrive': configdrive_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(configdrive_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid',
                          preserve_ephemeral=False,
                          configdrive=configdrive_url,
                          boot_option="netboot")
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             configdrive_mb, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")
        mock_unlink.assert_called_once_with('fake-path')


@mock.patch.object(utils, 'execute')
class MakePartitionsTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(MakePartitionsTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.root_mb = 1024
        self.swap_mb = 512
        self.ephemeral_mb = 0
        self.configdrive_mb = 0

    def _get_parted_cmd(self, dev):
        return ['parted', '-a', 'optimal', '-s', dev,
                '--', 'unit', 'MiB', 'mklabel', 'msdos']

    def _get_parted_cmd_uefi(self, dev):
        return ['parted', '-a', 'optimal', '-s',
                dev, '--', 'unit', 'MiB', 'mklabel', 'gpt']

    def _test_make_partitions(self, mock_exc, boot_option):
        mock_exc.return_value = (None, None)
        disk_utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                                   self.ephemeral_mb, self.configdrive_mb,
                                   boot_option=boot_option)

        expected_mkpart = ['mkpart', 'primary', 'linux-swap', '1', '513',
                           'mkpart', 'primary', '', '513', '1537']
        if boot_option == "local":
            expected_mkpart.extend(['set', '2', 'boot', 'on'])
        self.dev = 'fake-dev'
        parted_cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        parted_call = mock.call(*parted_cmd, run_as_root=True,
                                check_exit_code=[0])
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, run_as_root=True,
                               check_exit_code=[0, 1])
        mock_exc.assert_has_calls([parted_call, fuser_call])

    def test_make_partitions(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="netboot")

    def test_make_partitions_local_boot(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local")

    def test_make_partitions_with_ephemeral(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = 'fake-dev'
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = (None, None)
        disk_utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                                   self.ephemeral_mb, self.configdrive_mb)

        parted_call = mock.call(*cmd, run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls([parted_call])

    def test_make_partitions_with_local_device(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = 'fake-dev'
        expected_result = {'ephemeral': 'fake-dev1',
                           'swap': 'fake-dev2',
                           'root': 'fake-dev3'}
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = (None, None)
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb)

        parted_call = mock.call(*cmd, run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)

    def test_make_partitions_with_iscsi_device(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = 'ip-10.10.1.10:abc-iscsi-xyz-lun-123'
        expected_result = {'ephemeral': self.dev + '-part1',
                           'swap': self.dev + '-part2',
                           'root': self.dev + '-part3'}
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = (None, None)
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb)

        parted_call = mock.call(*cmd, run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)

    def test_make_partitions_with_iscsi_device_uefi_local(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', 'fat32', '1', '201',
                           'set', '1', 'boot', 'on',
                           'mkpart', 'primary', '', '201', '2249',
                           'mkpart', 'primary', 'linux-swap', '2249', '2761',
                           'mkpart', 'primary', '', '2761', '3785']
        self.dev = 'ip-10.10.1.10:abc-iscsi-xyz-lun-123'
        expected_result = {'efi system partition': self.dev + '-part1',
                           'ephemeral': self.dev + '-part2',
                           'swap': self.dev + '-part3',
                           'root': self.dev + '-part4'}
        cmd = self._get_parted_cmd_uefi(self.dev) + expected_mkpart
        mock_exc.return_value = (None, None)
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb, boot_option='local', boot_mode='uefi')

        parted_call = mock.call(*cmd, run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)


@mock.patch.object(disk_utils, 'get_dev_block_size')
@mock.patch.object(utils, 'execute')
class DestroyMetaDataTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(DestroyMetaDataTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_destroy_disk_metadata(self, mock_exec, mock_gz):
        mock_gz.return_value = 64
        expected_calls = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', run_as_root=True,
                                    check_exit_code=[0],
                                    use_standard_locale=True),
                          mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', 'seek=28',
                                    run_as_root=True,
                                    check_exit_code=[0],
                                    use_standard_locale=True)]
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)
        self.assertTrue(mock_gz.called)

    def test_destroy_disk_metadata_get_dev_size_fail(self, mock_exec, mock_gz):
        mock_gz.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                   'bs=512', 'count=36', run_as_root=True,
                                   check_exit_code=[0],
                                   use_standard_locale=True)]
        self.assertRaises(processutils.ProcessExecutionError,
                          disk_utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)

    def test_destroy_disk_metadata_dd_fail(self, mock_exec, mock_gz):
        mock_exec.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                   'bs=512', 'count=36', run_as_root=True,
                                   check_exit_code=[0],
                                   use_standard_locale=True)]
        self.assertRaises(processutils.ProcessExecutionError,
                          disk_utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)
        self.assertFalse(mock_gz.called)


@mock.patch.object(utils, 'execute')
class GetDeviceBlockSizeTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(GetDeviceBlockSizeTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_get_dev_block_size(self, mock_exec):
        mock_exec.return_value = ("64", "")
        expected_call = [mock.call('blockdev', '--getsz', self.dev,
                                   run_as_root=True, check_exit_code=[0])]
        disk_utils.get_dev_block_size(self.dev)
        mock_exec.assert_has_calls(expected_call)


@mock.patch.object(disk_utils, 'dd')
@mock.patch.object(disk_utils, 'qemu_img_info')
@mock.patch.object(disk_utils, 'convert_image')
class PopulateImageTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(PopulateImageTestCase, self).setUp()

    def test_populate_raw_image(self, mock_cg, mock_qinfo, mock_dd):
        type(mock_qinfo.return_value).file_format = mock.PropertyMock(
            return_value='raw')
        disk_utils.populate_image('src', 'dst')
        mock_dd.assert_called_once_with('src', 'dst')
        self.assertFalse(mock_cg.called)

    def test_populate_qcow2_image(self, mock_cg, mock_qinfo, mock_dd):
        type(mock_qinfo.return_value).file_format = mock.PropertyMock(
            return_value='qcow2')
        disk_utils.populate_image('src', 'dst')
        mock_cg.assert_called_once_with('src', 'dst', 'raw', True)
        self.assertFalse(mock_dd.called)


@mock.patch.object(disk_utils, 'is_block_device', lambda d: True)
@mock.patch.object(disk_utils, 'block_uuid', lambda p: 'uuid')
@mock.patch.object(disk_utils, 'dd', lambda *_: None)
@mock.patch.object(disk_utils, 'convert_image', lambda *_: None)
@mock.patch.object(utils, 'mkfs', lambda *_: None)
# NOTE(dtantsur): destroy_disk_metadata resets file size, disabling it
@mock.patch.object(disk_utils, 'destroy_disk_metadata', lambda *_: None)
class RealFilePartitioningTestCase(test_base.BaseTestCase):
    """This test applies some real-world partitioning scenario to a file.

    This test covers the whole partitioning, mocking everything not possible
    on a file. That helps us assure, that we do all partitioning math properly
    and also conducts integration testing of DiskPartitioner.
    """

    def setUp(self):
        super(RealFilePartitioningTestCase, self).setUp()
        # NOTE(dtantsur): no parted utility on gate-ironic-python26
        try:
            utils.execute('parted', '--version')
        except OSError as exc:
            self.skipTest('parted utility was not found: %s' % exc)
        self.file = tempfile.NamedTemporaryFile(delete=False)
        # NOTE(ifarkas): the file needs to be closed, so fuser won't report
        #                any usage
        self.file.close()
        # NOTE(dtantsur): 20 MiB file with zeros
        utils.execute('dd', 'if=/dev/zero', 'of=%s' % self.file.name,
                      'bs=1', 'count=0', 'seek=20MiB')

    @staticmethod
    def _run_without_root(func, *args, **kwargs):
        """Make sure root is not required when using utils.execute."""
        real_execute = utils.execute

        def fake_execute(*cmd, **kwargs):
            kwargs['run_as_root'] = False
            return real_execute(*cmd, **kwargs)

        with mock.patch.object(utils, 'execute', fake_execute):
            return func(*args, **kwargs)

    def test_different_sizes(self):
        # NOTE(dtantsur): Keep this list in order with expected partitioning
        fields = ['ephemeral_mb', 'swap_mb', 'root_mb']
        variants = ((0, 0, 12), (4, 2, 8), (0, 4, 10), (5, 0, 10))
        for variant in variants:
            kwargs = dict(zip(fields, variant))
            self._run_without_root(disk_utils.work_on_disk,
                                   self.file.name, ephemeral_format='ext4',
                                   node_uuid='', image_path='path', **kwargs)
            part_table = self._run_without_root(
                disk_utils.list_partitions, self.file.name)
            for part, expected_size in zip(part_table, filter(None, variant)):
                self.assertEqual(expected_size, part['size'],
                                 "comparison failed for %s" % list(variant))

    def test_whole_disk(self):
        # 6 MiB ephemeral + 3 MiB swap + 9 MiB root + 1 MiB for MBR
        # + 1 MiB MAGIC == 20 MiB whole disk
        # TODO(dtantsur): figure out why we need 'magic' 1 more MiB
        # and why the is different on Ubuntu and Fedora (see below)
        self._run_without_root(disk_utils.work_on_disk, self.file.name,
                               root_mb=9, ephemeral_mb=6, swap_mb=3,
                               ephemeral_format='ext4', node_uuid='',
                               image_path='path')
        part_table = self._run_without_root(
            disk_utils.list_partitions, self.file.name)
        sizes = [part['size'] for part in part_table]
        # NOTE(dtantsur): parted in Ubuntu 12.04 will occupy the last MiB,
        # parted in Fedora 20 won't - thus two possible variants for last part
        self.assertEqual([6, 3], sizes[:2],
                         "unexpected partitioning %s" % part_table)
        self.assertIn(sizes[2], (9, 10))


@mock.patch.object(shutil, 'copyfileobj')
@mock.patch.object(requests, 'get')
class GetConfigdriveTestCase(test_base.BaseTestCase):

    @mock.patch.object(gzip, 'GzipFile')
    def test_get_configdrive(self, mock_gzip, mock_requests, mock_copy):
        mock_requests.return_value = mock.MagicMock(content='Zm9vYmFy')
        disk_utils._get_configdrive('http://1.2.3.4/cd',
                                    'fake-node-uuid')
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(gzip, 'GzipFile')
    def test_get_configdrive_base64_string(self, mock_gzip, mock_requests,
                                           mock_copy):
        disk_utils._get_configdrive('Zm9vYmFy', 'fake-node-uuid')
        self.assertFalse(mock_requests.called)
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_get_configdrive_bad_url(self, mock_requests, mock_copy):
        mock_requests.side_effect = requests.exceptions.RequestException
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils._get_configdrive,
                          'http://1.2.3.4/cd', 'fake-node-uuid')
        self.assertFalse(mock_copy.called)

    @mock.patch.object(base64, 'b64decode')
    def test_get_configdrive_base64_error(self, mock_b64, mock_requests,
                                          mock_copy):
        mock_b64.side_effect = TypeError
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils._get_configdrive,
                          'malformed', 'fake-node-uuid')
        mock_b64.assert_called_once_with('malformed')
        self.assertFalse(mock_copy.called)

    @mock.patch.object(gzip, 'GzipFile')
    def test_get_configdrive_gzip_error(self, mock_gzip, mock_requests,
                                        mock_copy):
        mock_requests.return_value = mock.MagicMock(content='Zm9vYmFy')
        mock_copy.side_effect = IOError
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils._get_configdrive,
                          'http://1.2.3.4/cd', 'fake-node-uuid')
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)


@mock.patch('time.sleep', lambda sec: None)
class OtherFunctionTestCase(test_base.BaseTestCase):

    @mock.patch.object(os, 'stat')
    @mock.patch.object(stat, 'S_ISBLK')
    def test_is_block_device_works(self, mock_is_blk, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_is_blk.return_value = True
        mock_os().st_mode = 10000
        self.assertTrue(disk_utils.is_block_device(device))
        mock_is_blk.assert_called_once_with(mock_os().st_mode)

    @mock.patch.object(os, 'stat')
    def test_is_block_device_raises(self, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_os.side_effect = OSError
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.is_block_device, device)
        mock_os.assert_has_calls([mock.call(device)] * 3)

    @mock.patch.object(os.path, 'getsize')
    @mock.patch.object(disk_utils, 'qemu_img_info')
    def test_get_image_mb(self, mock_qinfo, mock_getsize):
        mb = 1024 * 1024

        mock_getsize.return_value = 0
        type(mock_qinfo.return_value).virtual_size = mock.PropertyMock(
            return_value=0)
        self.assertEqual(0, disk_utils.get_image_mb('x', False))
        self.assertEqual(0, disk_utils.get_image_mb('x', True))
        mock_getsize.return_value = 1
        type(mock_qinfo.return_value).virtual_size = mock.PropertyMock(
            return_value=1)
        self.assertEqual(1, disk_utils.get_image_mb('x', False))
        self.assertEqual(1, disk_utils.get_image_mb('x', True))
        mock_getsize.return_value = mb
        type(mock_qinfo.return_value).virtual_size = mock.PropertyMock(
            return_value=mb)
        self.assertEqual(1, disk_utils.get_image_mb('x', False))
        self.assertEqual(1, disk_utils.get_image_mb('x', True))
        mock_getsize.return_value = mb + 1
        type(mock_qinfo.return_value).virtual_size = mock.PropertyMock(
            return_value=mb + 1)
        self.assertEqual(2, disk_utils.get_image_mb('x', False))
        self.assertEqual(2, disk_utils.get_image_mb('x', True))

    def test_is_iscsi_device_True(self):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        self.assertTrue(disk_utils.is_iscsi_device(device))

    def test_is_iscsi_device_False(self):
        device = '/dev/disk/by-path/fake-dev'
        self.assertFalse(disk_utils.is_iscsi_device(device))
