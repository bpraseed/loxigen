# Copyright 2013, Big Switch Networks, Inc.
#
# LoxiGen is licensed under the Eclipse Public License, version 1.0 (EPL), with
# the following special exception:
#
# LOXI Exception
#
# As a special exception to the terms of the EPL, you may distribute libraries
# generated by LoxiGen (LoxiGen Libraries) under the terms of your choice, provided
# that copyright and licensing notices generated by LoxiGen are not altered or removed
# from the LoxiGen Libraries and the notice provided below is (i) included in
# the LoxiGen Libraries, if distributed in source code form and (ii) included in any
# documentation for the LoxiGen Libraries, if distributed in binary form.
#
# Notice: "Copyright 2013, Big Switch Networks, Inc. This library was generated by the LoxiGen Compiler."
#
# You may not use this file except in compliance with the EPL or LOXI Exception. You may obtain
# a copy of the EPL at:
#
# http://www.eclipse.org/legal/epl-v10.html
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# EPL for the specific language governing permissions and limitations
# under the EPL.

from itertools import chain
import logging
import re
import sys

from collections import namedtuple, OrderedDict
from generic_utils import find, memoize, OrderedSet
from loxi_ir import ir_offset
import loxi_front_end.frontend_ir as frontend_ir

logger = logging.getLogger(__name__)

# This module is intended to be imported like this: from loxi_ir import *
# All public names are prefixed with 'OF'.
__all__ = [
    'OFVersion',
    'OFProtocol',
    'OFClass',
    'OFUnifiedClass',
    'OFDataMember',
    'OFTypeMember',
    'OFDiscriminatorMember',
    'OFLengthMember',
    'OFFieldLengthMember',
    'OFPadMember',
    'OFEnum',
    'OFEnumEntry'
]

"""
One version of the OpenFlow protocol
@param version Official dotted version number (e.g., "1.0", "1.3")
@param wire_version Integer wire version (1 for 1.0, 4 for 1.3)
"""
class OFVersion(namedtuple("OFVersion", ("version", "wire_version"))):
    @property
    @memoize
    def constant(self):
        """ return this version as an uppercase string suitable
            for use as a c constant, e.g., "VERSION_1_3"
        """
        return self.constant_version(prefix="VERSION_")

    @property
    @memoize
    def short_constant(self):
        """ return this version as an uppercase string suitable
            for use as a c constant, e.g., "OF_"
        """
        return self.constant_version(prefix="OF_")

    def constant_version(self, prefix="VERSION_"):
        return prefix + self.version.replace(".", "_")

    def __repr__(self):
        return "OFVersion(%s)" % self.version

    def __str__(self):
        return self.version

    def __cmp__(self, other):
        return cmp(self.wire_version, other.wire_version)

"""
One version of the OpenFlow protocol

Combination of multiple OFInput objects.

@param wire_version
@param classes List of OFClass objects
@param enums List of Enum objects
"""
class OFProtocol(namedtuple('OFProtocol', ['version', 'classes', 'enums'])):
    def __init__(self, version, classes, enums):
        super(OFProtocol, self).__init__(self, version, classes, enums)
        assert version is None or isinstance(version, OFVersion)

    def class_by_name(self, name):
        return find(lambda ofclass: ofclass.name == name, self.classes)

    def enum_by_name(self, name):
        return find(lambda enum: enum.name == name, self.enums)

"""
An OpenFlow class

All compound objects like messages, actions, instructions, etc are
uniformly represented by this class.

The members are in the same order as on the wire.

@param name
@param superclass_name of this classes' super class
@param members List of *Member objects
@param params optional dictionary of parameters
"""
class OFClass(namedtuple('OFClass', ['name', 'superclass', 'members', 'virtual', 'params', 'is_fixed_length', 'base_length'])):
    def __init__(self, *a, **kw):
        super(OFClass, self).__init__(self, *a, **kw)
        # Back reference will be added by assignment
        self.protocol = None

    def member_by_name(self, name):
        return find(lambda m: hasattr(m, "name") and m.name == name, self.members)

    @property
    def discriminator(self):
        return find(lambda m: type(m) == OFDiscriminatorMember, self.members)

    def is_instanceof(self, super_class_name):
        if self.name == super_class_name:
            return True
        elif self.superclass is None:
            return False
        else:
            return self.superclass.is_instanceof(super_class_name)

    def is_subclassof(self, super_class_name):
        return self.name != super_class_name and self.is_instanceof(super_class_name)

    @property
    def is_message(self):
        return self.is_instanceof("of_header")

    @property
    def is_oxm(self):
        return self.is_instanceof("of_oxm")

    @property
    def is_action(self):
        return self.is_instanceof("of_action")

    @property
    def is_action_id(self):
        return self.is_instanceof("of_action_id")

    @property
    def is_instruction(self):
        return self.is_instanceof("of_instruction")

    def __hash__(self):
        return hash((self.name, self.protocol.wire_version if self.protocol else None))

    @property
    def length(self):
        if self.is_fixed_length:
            return self.base_length
        else:
            raise Exception("Not a fixed length class: {}".format(self.name))

    @property
    def length_member(self):
        return find(lambda m: type(m) == OFLengthMember, self.members)

    @property
    def has_internal_alignment(self):
        return self.params.get('length_includes_align') == 'True'

    @property
    def has_external_alignment(self):
        return self.params.get('length_includes_align') == 'False'

    @property
    def has_type_members(self):
        return find(lambda m: isinstance(m, OFTypeMember), self.members) is not None

""" one class unified across openflow versions. Keeps around a map version->versioned_class """
class OFUnifiedClass(OFClass):
    def __new__(cls, version_classes, *a, **kw):
        return super(OFUnifiedClass, cls).__new__(cls, *a, **kw)

    def __init__(self, version_classes, *a, **kw):
        super(OFUnifiedClass, self).__init__(*a, **kw)
        self.version_classes = version_classes

    def class_by_version(self, version):
        return self.version_classes[version]



""" A mixin for member classes. Keeps around the back reference of_class (for assignment by
    build_protocol, and additional methods shared across Members. """
class MemberMixin(object):
    def __init__(self, *a, **kw):
        super(MemberMixin, self).__init__(*a, **kw)
        # Back reference will be added by assignment in build_protocol below
        self.of_class = None

    @property
    def length(self):
        if self.is_fixed_length:
            return self.base_length
        else:
            raise Exception("Not a fixed length member: {}.{} [{}]".format(
                self.of_class.name,
                self.name if hasattr("self", "name") else "(unnnamed)",
                type(self).__name__))

"""
Normal field

@param name
@param oftype C-like type string

Example: packet_in.buffer_id
"""
class OFDataMember(namedtuple('OFDataMember', ['name', 'oftype', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
Field that declares that this is an abstract super-class and
that the sub classes will be discriminated based on this field.
E.g., 'type' is the discriminator member of the abstract superclass
of_action.

@param name
"""
class OFDiscriminatorMember (namedtuple('OFDiscriminatorMember', ['name', 'oftype', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
Field used to determine the type of an OpenFlow object

@param name
@param oftype C-like type string
@param value Fixed type value

Example: packet_in.type, flow_add._command
"""
class OFTypeMember (namedtuple('OFTypeMember', ['name', 'oftype', 'value', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
Field with the length of the containing object

@param name
@param oftype C-like type string

Example: packet_in.length, action_output.len
"""
class OFLengthMember (namedtuple('OFLengthMember', ['name', 'oftype', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
Field with the length of another field in the containing object

@param name
@param oftype C-like type string
@param field_name Peer field whose length this field contains

Example: packet_out.actions_len (only usage)
"""
class OFFieldLengthMember (namedtuple('OFFieldLengthMember', ['name', 'oftype', 'field_name', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
Zero-filled padding

@param length Length in bytes

Example: packet_in.pad
"""
class OFPadMember (namedtuple('OFPadMember', ['pad_length', 'is_fixed_length', 'base_length', 'offset']), MemberMixin):
    pass

"""
An OpenFlow enumeration

All values are Python ints.

@param name
@param entries List of OFEnumEntry objects in input order
@params dict of optional params. Currently defined:
       - wire_type: the low_level type of the enum values (uint8,...)
"""
class OFEnum(namedtuple('OFEnum', ['name', 'entries', 'params'])):
    def __init__(self, *a, **kw):
        super(OFEnum, self).__init__(*a, **kw)
        # Back reference will be added by assignment
        self.protocol = None

    @property
    def values(self):
        return [(e.name, e.value) for e in self.entries]

    @property
    def is_bitmask(self):
        return "bitmask" in self.params and self.params['bitmask']

    @property
    def wire_type(self):
        return self.params['wire_type'] if 'wire_type' in self.params else self.name

class OFEnumEntry(namedtuple('OFEnumEntry', ['name', 'value', 'params'])):
    def __init__(self, *a, **kw):
        super(OFEnumEntry, self).__init__(*a, **kw)
        # Back reference will be added by assignment
        self.enum = None

class RedefinedException(Exception):
    pass

class ClassNotFoundException(Exception):
    pass

class DependencyCycleException(Exception):
    pass

def build_protocol(version, ofinputs):
    name_frontend_classes = OrderedDict()
    name_frontend_enums = OrderedDict()

    for ofinput in ofinputs:
        for c in ofinput.classes:
            name = c.name
            if name in name_frontend_classes:
                raise RedefinedException("Error parsing {}. Class {} redefined (already defined in {})"
                        .format(ofinput.filename, name,
                            name_frontend_classes[name][1].filename))
            else:
                name_frontend_classes[name] = (c, ofinput)
        for e in ofinput.enums:
            name = e.name
            if name in name_frontend_enums:
                raise RedefinedException("Error parsing {}. Enum {} redefined (already defined in {})"
                        .format(ofinput.filename, name,
                            name_frontend_enums[name][1].filename))
            else:
                name_frontend_enums[name] = (e, ofinput)

    name_enums = {}
    for fe, _ in name_frontend_enums.values():
        entries = tuple(OFEnumEntry(name=e.name, value=e.value,
                        params=e.params) for e in fe.entries)
        enum = OFEnum(name=fe.name,
                      entries=entries,
                      params=fe.params)
        for e in entries:
            e.enum = enum
        name_enums[enum.name] = enum

    name_classes = OrderedDict()
    build_touch_classes = OrderedSet()

    def convert_member_properties(props):
        return { name if name != "length" else "pad_length" : value for name, value in props.items() }

    def build_member(of_class, fe_member, length_info):
        if isinstance(fe_member, frontend_ir.OFVersionMember):
            member = OFTypeMember(offset = length_info.offset,
                                  base_length = length_info.base_length,
                                  is_fixed_length=length_info.is_fixed_length,
                                  value = version.wire_version,
                                  **convert_member_properties(fe_member._asdict()))
        else:
            ir_class = globals()[type(fe_member).__name__]
            member = ir_class(offset = length_info.offset,
                              base_length = length_info.base_length,
                              is_fixed_length=length_info.is_fixed_length,
                              **convert_member_properties(fe_member._asdict()))
        member.of_class = of_class
        return member

    def build_class(name):
        if name in name_classes:
            return name_classes[name]
        if name in build_touch_classes:
            raise DependencyCycleException( "Dependency cycle: {}"
                    .format(" -> ".join(list(build_touch_classes) + [name])))
        if not name in name_frontend_classes:
            raise ClassNotFoundException("Class not found: {}".format(name))

        build_touch_classes.add(name)

        fe, _ = name_frontend_classes[name]

        superclass = build_class(fe.superclass) if fe.superclass else None

        # make sure members on which we depend are built first (for calc_length)
        for m in fe.members:
            if not hasattr(m, "oftype"):
                continue
            for m_name in re.sub(r'_t$', '', m.oftype), m.oftype:
                logger.debug("Checking {}".format(m_name))
                if m_name in name_frontend_classes:
                    build_class(m_name)

        base_length, is_fixed_length, member_lengths = \
           ir_offset.calc_lengths(version, fe, name_classes, name_enums)

        members = []
        c = OFClass(name=fe.name, superclass=superclass,
                members=members, virtual=fe.virtual, params=fe.params,
                is_fixed_length=is_fixed_length, base_length=base_length)

        members.extend( build_member(c, fe_member, member_lengths[fe_member])
                  for fe_member in fe.members)

        name_classes[name] = c
        build_touch_classes.remove(name)
        return c

    def build_id_class(orig_name, base_name):
        name = base_name + '_id' + orig_name[len(base_name):]
        if name in name_classes:
            return name_classes[name]
        orig_fe, _ = name_frontend_classes[orig_name]

        if orig_fe.superclass:
            superclass_name = base_name + '_id' + orig_fe.superclass[len(base_name):]
            superclass = build_id_class(orig_fe.superclass, base_name)
        else:
            superclass_name = None
            superclass = None

        ofc_members = []
        for m in orig_fe.members:
            if not isinstance(m, frontend_ir.OFDataMember) and not isinstance(m, frontend_ir.OFPadMember):
                ofc_members.append(m)

        fe = frontend_ir.OFClass(
            name=name,
            superclass=superclass_name,
            members=ofc_members,
            virtual=orig_fe.virtual,
            params={})

        base_length, is_fixed_length, member_lengths = \
           ir_offset.calc_lengths(version, fe, name_classes, name_enums)
        assert fe.virtual or is_fixed_length

        members = []
        c = OFClass(name=fe.name, superclass=superclass,
                members=members, virtual=fe.virtual, params=fe.params,
                is_fixed_length=is_fixed_length, base_length=base_length)

        members.extend( build_member(c, fe_member, member_lengths[fe_member])
                  for fe_member in fe.members)

        name_classes[name] = c
        return c

    id_class_roots = ["of_action", "of_instruction"]

    for name in sorted(name_frontend_classes.keys()):
        c = build_class(name)

        # Build ID classes for OF 1.3+
        if version.wire_version >= 4:
            for root in id_class_roots:
                if c.is_instanceof(root):
                    build_id_class(name, root)

    protocol = OFProtocol(version=version, classes=tuple(name_classes.values()), enums=tuple(name_enums.values()))
    for e in chain(protocol.classes, protocol.enums):
        e.protocol = protocol
    return protocol
