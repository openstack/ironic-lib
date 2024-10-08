# Copyright 2011 Justin Santa Barbara
# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import copy
import errno
import os
import os.path
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg

from ironic_lib import exception
from ironic_lib.tests import base
from ironic_lib import utils

CONF = cfg.CONF


class BareMetalUtilsTestCase(base.IronicLibTestCase):

    def test_unlink(self):
        with mock.patch.object(os, "unlink", autospec=True) as unlink_mock:
            unlink_mock.return_value = None
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")

    def test_unlink_ENOENT(self):
        with mock.patch.object(os, "unlink", autospec=True) as unlink_mock:
            unlink_mock.side_effect = OSError(errno.ENOENT)
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")


class ExecuteTestCase(base.IronicLibTestCase):
    # Allow calls to utils.execute() and related functions
    block_execute = False

    @mock.patch.object(processutils, 'execute', autospec=True)
    @mock.patch.object(os.environ, 'copy', return_value={}, autospec=True)
    def test_execute_use_standard_locale_no_env_variables(self, env_mock,
                                                          execute_mock):
        utils.execute('foo', use_standard_locale=True)
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C'})

    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_execute_use_standard_locale_with_env_variables(self,
                                                            execute_mock):
        utils.execute('foo', use_standard_locale=True,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C',
                                                            'foo': 'bar'})

    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_execute_not_use_standard_locale(self, execute_mock):
        utils.execute('foo', use_standard_locale=False,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'foo': 'bar'})

    @mock.patch.object(utils, 'LOG', autospec=True)
    def _test_execute_with_log_stdout(self, log_mock, log_stdout=None):
        with mock.patch.object(
                processutils, 'execute', autospec=True) as execute_mock:
            execute_mock.return_value = ('stdout', 'stderr')
            if log_stdout is not None:
                utils.execute('foo', log_stdout=log_stdout)
            else:
                utils.execute('foo')
            execute_mock.assert_called_once_with('foo')
            name, args, kwargs = log_mock.debug.mock_calls[0]
            if log_stdout is False:
                self.assertEqual(1, log_mock.debug.call_count)
                self.assertNotIn('stdout', args[0])
            else:
                self.assertEqual(2, log_mock.debug.call_count)
                self.assertIn('stdout', args[0])

    def test_execute_with_log_stdout_default(self):
        self._test_execute_with_log_stdout()

    def test_execute_with_log_stdout_true(self):
        self._test_execute_with_log_stdout(log_stdout=True)

    def test_execute_with_log_stdout_false(self):
        self._test_execute_with_log_stdout(log_stdout=False)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_execute_command_not_found(self, execute_mock, log_mock):
        execute_mock.side_effect = FileNotFoundError
        self.assertRaises(FileNotFoundError, utils.execute, 'foo')
        execute_mock.assert_called_once_with('foo')
        name, args, kwargs = log_mock.debug.mock_calls[0]
        self.assertEqual(1, log_mock.debug.call_count)
        self.assertIn('not found', args[0])


class MkfsTestCase(base.IronicLibTestCase):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs(self, execute_mock):
        utils.mkfs('ext4', '/my/block/dev')
        utils.mkfs('msdos', '/my/msdos/block/dev')
        utils.mkfs('swap', '/my/swap/block/dev')

        expected = [mock.call('mkfs', '-t', 'ext4', '-F', '/my/block/dev',
                              use_standard_locale=True),
                    mock.call('mkfs', '-t', 'msdos', '/my/msdos/block/dev',
                              use_standard_locale=True),
                    mock.call('mkswap', '/my/swap/block/dev',
                              use_standard_locale=True)]
        self.assertEqual(expected, execute_mock.call_args_list)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs_with_label(self, execute_mock):
        utils.mkfs('ext4', '/my/block/dev', 'ext4-vol')
        utils.mkfs('msdos', '/my/msdos/block/dev', 'msdos-vol')
        utils.mkfs('swap', '/my/swap/block/dev', 'swap-vol')

        expected = [mock.call('mkfs', '-t', 'ext4', '-F', '-L', 'ext4-vol',
                              '/my/block/dev',
                              use_standard_locale=True),
                    mock.call('mkfs', '-t', 'msdos', '-n', 'msdos-vol',
                              '/my/msdos/block/dev',
                              use_standard_locale=True),
                    mock.call('mkswap', '-L', 'swap-vol',
                              '/my/swap/block/dev',
                              use_standard_locale=True)]
        self.assertEqual(expected, execute_mock.call_args_list)

    @mock.patch.object(utils, 'execute', autospec=True,
                       side_effect=processutils.ProcessExecutionError(
                           stderr=os.strerror(errno.ENOENT)))
    def test_mkfs_with_unsupported_fs(self, execute_mock):
        self.assertRaises(exception.FileSystemNotSupported,
                          utils.mkfs, 'foo', '/my/block/dev')

    @mock.patch.object(utils, 'execute', autospec=True,
                       side_effect=processutils.ProcessExecutionError(
                           stderr='fake'))
    def test_mkfs_with_unexpected_error(self, execute_mock):
        self.assertRaises(processutils.ProcessExecutionError, utils.mkfs,
                          'ext4', '/my/block/dev', 'ext4-vol')


class IsHttpUrlTestCase(base.IronicLibTestCase):

    def test_is_http_url(self):
        self.assertTrue(utils.is_http_url('http://127.0.0.1'))
        self.assertTrue(utils.is_http_url('https://127.0.0.1'))
        self.assertTrue(utils.is_http_url('HTTP://127.1.2.3'))
        self.assertTrue(utils.is_http_url('HTTPS://127.3.2.1'))
        self.assertFalse(utils.is_http_url('Zm9vYmFy'))
        self.assertFalse(utils.is_http_url('11111111'))


class ParseRootDeviceTestCase(base.IronicLibTestCase):

    def test_parse_root_device_hints_without_operators(self):
        root_device = {
            'wwn': '123456', 'model': 'FOO model', 'size': 12345,
            'serial': 'foo-serial', 'vendor': 'foo VENDOR with space',
            'name': '/dev/sda', 'wwn_with_extension': '123456111',
            'wwn_vendor_extension': '111', 'rotational': True,
            'hctl': '1:0:0:0', 'by_path': '/dev/disk/by-path/1:0:0:0'}
        result = utils.parse_root_device_hints(root_device)
        expected = {
            'wwn': 's== 123456', 'model': 's== foo%20model',
            'size': '== 12345', 'serial': 's== foo-serial',
            'vendor': 's== foo%20vendor%20with%20space',
            'name': 's== /dev/sda', 'wwn_with_extension': 's== 123456111',
            'wwn_vendor_extension': 's== 111', 'rotational': True,
            'hctl': 's== 1%3A0%3A0%3A0',
            'by_path': 's== /dev/disk/by-path/1%3A0%3A0%3A0'}
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_with_operators(self):
        root_device = {
            'wwn': 's== 123456', 'model': 's== foo MODEL', 'size': '>= 12345',
            'serial': 's!= foo-serial', 'vendor': 's== foo VENDOR with space',
            'name': '<or> /dev/sda <or> /dev/sdb',
            'wwn_with_extension': 's!= 123456111',
            'wwn_vendor_extension': 's== 111', 'rotational': True,
            'hctl': 's== 1:0:0:0', 'by_path': 's== /dev/disk/by-path/1:0:0:0'}

        # Validate strings being normalized
        expected = copy.deepcopy(root_device)
        expected['model'] = 's== foo%20model'
        expected['vendor'] = 's== foo%20vendor%20with%20space'
        expected['hctl'] = 's== 1%3A0%3A0%3A0'
        expected['by_path'] = 's== /dev/disk/by-path/1%3A0%3A0%3A0'

        result = utils.parse_root_device_hints(root_device)
        # The hints already contain the operators, make sure we keep it
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_string_compare_operator_name(self):
        root_device = {'name': 's== /dev/sdb'}
        # Validate strings being normalized
        expected = copy.deepcopy(root_device)
        result = utils.parse_root_device_hints(root_device)
        # The hints already contain the operators, make sure we keep it
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_no_hints(self):
        result = utils.parse_root_device_hints({})
        self.assertIsNone(result)

    def test_parse_root_device_hints_convert_size(self):
        for size in (12345, '12345'):
            result = utils.parse_root_device_hints({'size': size})
            self.assertEqual({'size': '== 12345'}, result)

    def test_parse_root_device_hints_invalid_size(self):
        for value in ('not-int', -123, 0):
            self.assertRaises(ValueError, utils.parse_root_device_hints,
                              {'size': value})

    def test_parse_root_device_hints_int_or(self):
        expr = '<or> 123 <or> 456 <or> 789'
        result = utils.parse_root_device_hints({'size': expr})
        self.assertEqual({'size': expr}, result)

    def test_parse_root_device_hints_int_or_invalid(self):
        expr = '<or> 123 <or> non-int <or> 789'
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'size': expr})

    def test_parse_root_device_hints_string_or_space(self):
        expr = '<or> foo <or> foo bar <or> bar'
        expected = '<or> foo <or> foo%20bar <or> bar'
        result = utils.parse_root_device_hints({'model': expr})
        self.assertEqual({'model': expected}, result)

    def _parse_root_device_hints_convert_rotational(self, values,
                                                    expected_value):
        for value in values:
            result = utils.parse_root_device_hints({'rotational': value})
            self.assertEqual({'rotational': expected_value}, result)

    def test_parse_root_device_hints_convert_rotational(self):
        self._parse_root_device_hints_convert_rotational(
            (True, 'true', 'on', 'y', 'yes'), True)

        self._parse_root_device_hints_convert_rotational(
            (False, 'false', 'off', 'n', 'no'), False)

    def test_parse_root_device_hints_invalid_rotational(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'rotational': 'not-bool'})

    def test_parse_root_device_hints_invalid_wwn(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'wwn': 123})

    def test_parse_root_device_hints_invalid_wwn_with_extension(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'wwn_with_extension': 123})

    def test_parse_root_device_hints_invalid_wwn_vendor_extension(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'wwn_vendor_extension': 123})

    def test_parse_root_device_hints_invalid_model(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'model': 123})

    def test_parse_root_device_hints_invalid_serial(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'serial': 123})

    def test_parse_root_device_hints_invalid_vendor(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'vendor': 123})

    def test_parse_root_device_hints_invalid_name(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'name': 123})

    def test_parse_root_device_hints_invalid_hctl(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'hctl': 123})

    def test_parse_root_device_hints_invalid_by_path(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'by_path': 123})

    def test_parse_root_device_hints_non_existent_hint(self):
        self.assertRaises(ValueError, utils.parse_root_device_hints,
                          {'non-existent': 'foo'})

    def test_extract_hint_operator_and_values_single_value(self):
        expected = {'op': '>=', 'values': ['123']}
        self.assertEqual(
            expected, utils._extract_hint_operator_and_values(
                '>= 123', 'size'))

    def test_extract_hint_operator_and_values_multiple_values(self):
        expected = {'op': '<or>', 'values': ['123', '456', '789']}
        expr = '<or> 123 <or> 456 <or> 789'
        self.assertEqual(
            expected, utils._extract_hint_operator_and_values(expr, 'size'))

    def test_extract_hint_operator_and_values_multiple_values_space(self):
        expected = {'op': '<or>', 'values': ['foo', 'foo bar', 'bar']}
        expr = '<or> foo <or> foo bar <or> bar'
        self.assertEqual(
            expected, utils._extract_hint_operator_and_values(expr, 'model'))

    def test_extract_hint_operator_and_values_no_operator(self):
        expected = {'op': '', 'values': ['123']}
        self.assertEqual(
            expected, utils._extract_hint_operator_and_values('123', 'size'))

    def test_extract_hint_operator_and_values_empty_value(self):
        self.assertRaises(
            ValueError, utils._extract_hint_operator_and_values, '', 'size')

    def test_extract_hint_operator_and_values_integer(self):
        expected = {'op': '', 'values': ['123']}
        self.assertEqual(
            expected, utils._extract_hint_operator_and_values(123, 'size'))

    def test__append_operator_to_hints(self):
        root_device = {'serial': 'foo', 'size': 12345,
                       'model': 'foo model', 'rotational': True}
        expected = {'serial': 's== foo', 'size': '== 12345',
                    'model': 's== foo model', 'rotational': True}

        result = utils._append_operator_to_hints(root_device)
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_or(self):
        expr = '<or> foo <or> foo bar <or> bar'
        expected = '<or> foo <or> foo%20bar <or> bar'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_in(self):
        expr = '<in> foo <in> foo bar <in> bar'
        expected = '<in> foo <in> foo%20bar <in> bar'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_op_space(self):
        expr = 's== test string with space'
        expected = 's== test%20string%20with%20space'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_op_no_space(self):
        expr = 's!= SpongeBob'
        expected = 's!= spongebob'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_no_op_space(self):
        expr = 'no operators'
        expected = 'no%20operators'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_no_op_no_space(self):
        expr = 'NoSpace'
        expected = 'nospace'
        result = utils._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_empty_value(self):
        self.assertRaises(
            ValueError, utils._normalize_hint_expression, '', 'size')


class MatchRootDeviceTestCase(base.IronicLibTestCase):

    def setUp(self):
        super(MatchRootDeviceTestCase, self).setUp()
        self.devices = [
            {'name': '/dev/sda', 'size': 64424509440, 'model': 'ok model',
             'serial': 'fakeserial'},
            {'name': '/dev/sdb', 'size': 128849018880, 'model': 'big model',
             'serial': 'veryfakeserial', 'rotational': 'yes'},
            {'name': '/dev/sdc', 'size': 10737418240, 'model': 'small model',
             'serial': 'veryveryfakeserial', 'rotational': False},
        ]

    def test_match_root_device_hints_one_hint(self):
        root_device_hints = {'size': '>= 70'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_rotational(self):
        root_device_hints = {'rotational': False}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_rotational_convert_devices_bool(self):
        root_device_hints = {'size': '>=100', 'rotational': True}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_multiple_hints(self):
        root_device_hints = {'size': '>= 50', 'model': 's==big model',
                             'serial': 's==veryfakeserial'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_multiple_hints2(self):
        root_device_hints = {
            'size': '<= 20',
            'model': '<or> model 5 <or> foomodel <or> small model <or>',
            'serial': 's== veryveryfakeserial'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_multiple_hints3(self):
        root_device_hints = {'rotational': False, 'model': '<in> small'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_no_operators(self):
        root_device_hints = {'size': '120', 'model': 'big model',
                             'serial': 'veryfakeserial'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_no_device_found(self):
        root_device_hints = {'size': '>=50', 'model': 's==foo'}
        dev = utils.match_root_device_hints(self.devices, root_device_hints)
        self.assertIsNone(dev)

    @mock.patch.object(utils.LOG, 'warning', autospec=True)
    def test_match_root_device_hints_empty_device_attribute(self, mock_warn):
        empty_dev = [{'name': '/dev/sda', 'model': ' '}]
        dev = utils.match_root_device_hints(empty_dev, {'model': 'foo'})
        self.assertIsNone(dev)
        self.assertTrue(mock_warn.called)

    def test_find_devices_all(self):
        root_device_hints = {'size': '>= 10'}
        devs = list(utils.find_devices_by_hints(self.devices,
                                                root_device_hints))
        self.assertEqual(self.devices, devs)

    def test_find_devices_none(self):
        root_device_hints = {'size': '>= 100500'}
        devs = list(utils.find_devices_by_hints(self.devices,
                                                root_device_hints))
        self.assertEqual([], devs)

    def test_find_devices_name(self):
        root_device_hints = {'name': 's== /dev/sda'}
        devs = list(utils.find_devices_by_hints(self.devices,
                                                root_device_hints))
        self.assertEqual([self.devices[0]], devs)


@mock.patch.object(utils, 'execute', autospec=True)
class GetRouteSourceTestCase(base.IronicLibTestCase):

    def test_get_route_source_ipv4(self, mock_execute):
        mock_execute.return_value = ('XXX src 1.2.3.4 XXX\n    cache', None)

        source = utils.get_route_source('XXX')
        self.assertEqual('1.2.3.4', source)

    def test_get_route_source_ipv6(self, mock_execute):
        mock_execute.return_value = ('XXX src 1:2::3:4 metric XXX\n    cache',
                                     None)

        source = utils.get_route_source('XXX')
        self.assertEqual('1:2::3:4', source)

    def test_get_route_source_ipv6_linklocal(self, mock_execute):
        mock_execute.return_value = (
            'XXX src fe80::1234:1234:1234:1234 metric XXX\n    cache', None)

        source = utils.get_route_source('XXX')
        self.assertIsNone(source)

    def test_get_route_source_ipv6_linklocal_allowed(self, mock_execute):
        mock_execute.return_value = (
            'XXX src fe80::1234:1234:1234:1234 metric XXX\n    cache', None)

        source = utils.get_route_source('XXX', ignore_link_local=False)
        self.assertEqual('fe80::1234:1234:1234:1234', source)

    def test_get_route_source_indexerror(self, mock_execute):
        mock_execute.return_value = ('XXX src \n    cache', None)

        source = utils.get_route_source('XXX')
        self.assertIsNone(source)


@mock.patch('shutil.rmtree', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
@mock.patch('tempfile.mkdtemp', autospec=True)
class MountedTestCase(base.IronicLibTestCase):

    def test_temporary(self, mock_temp, mock_execute, mock_rmtree):
        with utils.mounted('/dev/fake') as path:
            self.assertIs(path, mock_temp.return_value)
        mock_execute.assert_has_calls([
            mock.call("mount", '/dev/fake', mock_temp.return_value,
                      attempts=1, delay_on_retry=True),
            mock.call("umount", mock_temp.return_value,
                      attempts=3, delay_on_retry=True),
        ])
        mock_rmtree.assert_called_once_with(mock_temp.return_value)

    def test_with_dest(self, mock_temp, mock_execute, mock_rmtree):
        with utils.mounted('/dev/fake', '/mnt/fake') as path:
            self.assertEqual('/mnt/fake', path)
        mock_execute.assert_has_calls([
            mock.call("mount", '/dev/fake', '/mnt/fake',
                      attempts=1, delay_on_retry=True),
            mock.call("umount", '/mnt/fake',
                      attempts=3, delay_on_retry=True),
        ])
        self.assertFalse(mock_temp.called)
        self.assertFalse(mock_rmtree.called)

    def test_with_opts(self, mock_temp, mock_execute, mock_rmtree):
        with utils.mounted('/dev/fake', '/mnt/fake',
                           opts=['ro', 'foo=bar']) as path:
            self.assertEqual('/mnt/fake', path)
        mock_execute.assert_has_calls([
            mock.call("mount", '/dev/fake', '/mnt/fake', '-o', 'ro,foo=bar',
                      attempts=1, delay_on_retry=True),
            mock.call("umount", '/mnt/fake',
                      attempts=3, delay_on_retry=True),
        ])

    def test_with_type(self, mock_temp, mock_execute, mock_rmtree):
        with utils.mounted('/dev/fake', '/mnt/fake',
                           fs_type='iso9660') as path:
            self.assertEqual('/mnt/fake', path)
        mock_execute.assert_has_calls([
            mock.call("mount", '/dev/fake', '/mnt/fake', '-t', 'iso9660',
                      attempts=1, delay_on_retry=True),
            mock.call("umount", '/mnt/fake',
                      attempts=3, delay_on_retry=True),
        ])

    def test_failed_to_mount(self, mock_temp, mock_execute, mock_rmtree):
        mock_execute.side_effect = OSError
        self.assertRaises(OSError, utils.mounted('/dev/fake').__enter__)
        mock_execute.assert_called_once_with("mount", '/dev/fake',
                                             mock_temp.return_value,
                                             attempts=1,
                                             delay_on_retry=True)
        mock_rmtree.assert_called_once_with(mock_temp.return_value)

    def test_failed_to_unmount(self, mock_temp, mock_execute, mock_rmtree):
        mock_execute.side_effect = [('', ''),
                                    processutils.ProcessExecutionError]
        with utils.mounted('/dev/fake', '/mnt/fake') as path:
            self.assertEqual('/mnt/fake', path)
        mock_execute.assert_has_calls([
            mock.call("mount", '/dev/fake', '/mnt/fake',
                      attempts=1, delay_on_retry=True),
            mock.call("umount", '/mnt/fake',
                      attempts=3, delay_on_retry=True),
        ])
        self.assertFalse(mock_rmtree.called)


class ParseDeviceTagsTestCase(base.IronicLibTestCase):

    def test_empty(self):
        result = utils.parse_device_tags("\n\n")
        self.assertEqual([], list(result))

    def test_parse(self):
        tags = """
 PTUUID="00016a50" PTTYPE="dos" LABEL=""
TYPE="vfat" PART_ENTRY_SCHEME="gpt" PART_ENTRY_NAME="EFI System Partition"
        """
        result = list(utils.parse_device_tags(tags))
        self.assertEqual([
            {'PTUUID': '00016a50', 'PTTYPE': 'dos', 'LABEL': ''},
            {'TYPE': 'vfat', 'PART_ENTRY_SCHEME': 'gpt',
             'PART_ENTRY_NAME': 'EFI System Partition'}
        ], result)
