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

import collections

from ironic_lib import capabilities
from ironic_lib.tests import base


class ParseTestCase(base.IronicLibTestCase):
    def test_none(self):
        self.assertEqual({}, capabilities.parse(None))

    def test_from_dict(self):
        expected_dict = {"hello": "world"}
        self.assertDictEqual(expected_dict, capabilities.parse(expected_dict))

    def test_from_json_string(self):
        caps = '{"test": "world"}'
        self.assertDictEqual({"test": "world"}, capabilities.parse(caps))

    def test_from_old_format(self):
        caps = 'hello:test1,cat:meow'
        self.assertDictEqual({'hello': 'test1', 'cat': 'meow'},
                             capabilities.parse(caps))

    def test_from_old_format_with_malformed(self):
        caps = 'hello:test1,badformat'
        self.assertRaisesRegex(ValueError, 'Malformed capability',
                               capabilities.parse, caps)

    def test_from_old_format_skip_malformed(self):
        caps = 'hello:test1,badformat'
        self.assertDictEqual({'hello': 'test1'},
                             capabilities.parse(caps, skip_malformed=True))

    def test_no_old_format(self):
        caps = 'hello:test1,cat:meow'
        self.assertRaisesRegex(ValueError, 'Invalid JSON capabilities',
                               capabilities.parse, caps, compat=False)

    def test_unexpected_type(self):
        self.assertRaisesRegex(TypeError, 'Invalid capabilities',
                               capabilities.parse, 42)


class CombineTestCase(base.IronicLibTestCase):
    def test_combine(self):
        caps = capabilities.combine(
            collections.OrderedDict([('hello', None), ('cat', 'meow')]))
        self.assertEqual('hello:None,cat:meow', caps)

    def test_skip_none(self):
        caps = capabilities.combine(
            collections.OrderedDict([('hello', None), ('cat', 'meow')]),
            skip_none=True)
        self.assertEqual('cat:meow', caps)


class UpdateAndCombineTestCase(base.IronicLibTestCase):
    def test_from_dict(self):
        result = capabilities.update_and_combine(
            {'key1': 'old value', 'key2': 'value2'}, {'key1': 'value1'})
        self.assertIn(result, ['key1:value1,key2:value2',
                               'key2:value2,key1:value1'])

    def test_from_old_format(self):
        result = capabilities.update_and_combine(
            'key1:old value,key2:value2', {'key1': 'value1'})
        self.assertIn(result, ['key1:value1,key2:value2',
                               'key2:value2,key1:value1'])

    def test_skip_none(self):
        result = capabilities.update_and_combine(
            'key1:old value,key2:value2', {'key1': None}, skip_none=True)
        self.assertEqual('key2:value2', result)
