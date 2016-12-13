import attr
import io
import itertools
import functools
import struct


_gen_id = functools.partial(next, itertools.count())


class Incomplete(Exception):
    """
    Not enough data.
    """


@attr.s
class ClaimableByteBuffer(object):
    _bio = attr.ib(default=attr.Factory(io.BytesIO))
    _total = attr.ib(init=False, default=0)
    _claimed = attr.ib(init=False, default=0)

    def write(self, value):
        position = self._bio.tell()
        self._bio.seek(0, 2)
        self._bio.write(value)
        self._bio.seek(position)
        self._total += len(value)

    def unclaimed(self):
        return self._total - self._claimed

    def claim(self, amount):
        self._claimed = max(self._total, self._claimed + amount)
        return self._bio.read(amount)


class Container(object):

    def __init__(self, **kwargs):
        self._fields = []
        for name, value in kwargs.iteritems():
            self._fields.append(name)
            setattr(self, name, value)

    def __eq__(self, other):
        if not isinstance(other, Container):
            return False
        if other._fields != self._fields:
            return False
        return all(getattr(other, field) == getattr(self, field)
                   for field in self._fields)


@attr.s(frozen=True)
class _NullContext(object):
    """
    An empty context.
    """

_the_null_context = _NullContext()


@attr.s
class FormatField(object):
    _packer = attr.ib(convert=struct.Struct)
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _the_null_context

    def _feed(self, context, byte_buffer):
        if byte_buffer.unclaimed() < self._packer.size:
            raise Incomplete
        return self._packer.unpack(byte_buffer.claim(self._packer.size))

    def _emit(self, byte_buffer, *values):
        byte_buffer.write(self._packer.pack(*values))


@attr.s
class UBInt8(object):
    _field = attr.ib(init=False, default=FormatField('>b'))
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _the_null_context

    def _feed(self, context, byte_buffer):
        return self._field._feed(context, byte_buffer)[0]

    def _emit(self, byte_buffer, value):
        self._field._emit(byte_buffer, value)


@attr.s
class UBInt16(object):
    _field = attr.ib(init=False, default=FormatField('>h'))
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _the_null_context

    def _feed(self, context, byte_buffer):
        return self._field._feed(context, byte_buffer)[0]

    def _emit(self, byte_buffer, value):
        self._field._emit(byte_buffer, value)


@attr.s
class UBInt24(object):
    _field = attr.ib(init=False, default=FormatField('>bbb'))
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _the_null_context

    def _feed(self, context, byte_buffer):
        high, medium, low = self._field._feed(context, byte_buffer)
        return high << 16 | medium << 8 | low

    def _emit(self, byte_buffer, value):
        high = (value & 0xFF0000) >> 16
        medium = (value & 0x00FF00) >> 8
        low = value & 0x0000FF
        self._field._emit(byte_buffer, high, medium, low)


@attr.s
class _StructContext(object):
    position = attr.ib(default=0)
    parsed = attr.ib(default=attr.Factory(list))
    children = attr.ib(default=attr.Factory(dict))


@attr.s
class Struct(object):
    members = attr.ib()
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _StructContext()

    def _feed(self, context, byte_buffer):
        for idx in range(context.position, len(self.members)):
            name, dap = self.members[idx]
            parsed = _feed(dap, context.children, byte_buffer)
            context.parsed.append(parsed)
            context.position += 1
        return Container(
            **{name: parsed for name, parsed in
               zip((name for name, _ in self.members),
                   context.parsed)})

    def _emit(self, byte_buffer, container):
        for name, dap in self.members:
            dap._emit(byte_buffer, getattr(container, name))


@attr.s
class _SequenceContext(object):
    position = attr.ib(default=0)
    parsed = attr.ib(default=attr.Factory(list))
    children = attr.ib(default=attr.Factory(dict))


@attr.s
class Sequence(object):
    _MISSING = "MISSING"

    members = attr.ib()
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _SequenceContext()

    def _feed(self, context, byte_buffer):
        for idx in range(context.position, len(self.members)):
            dap = self.members[idx]
            parsed = _feed(dap, context.children, byte_buffer)
            context.parsed.append(parsed)
            context.position += 1
        return context.parsed

    def _emit(self, byte_buffer, values):
        members_iterator = iter(self.members)
        values_iterator = iter(values)
        for dap, value in zip(members_iterator, values_iterator):
            dap._emit(byte_buffer, value)


@attr.s
class _LayerContext(object):
    parsed = attr.ib(default=0)
    children = attr.ib(default=attr.Factory(dict))


@attr.s
class Layer(object):
    _upper = attr.ib()
    _lower = attr.ib()
    _id = attr.ib(default=attr.Factory(_gen_id))

    def _prepare_context(self):
        return _LayerContext()

    def _feed(self, context, byte_buffer):
        if not context.parsed:
            context.parsed = _feed(self._lower, context.children, byte_buffer)
        return _feed(self._upper, context.children, byte_buffer)

    def _emit(self, byte_buffer, values):
        self._lower(byte_buffer, self._upper.emit(byte_buffer, values))


@attr.s
class Translate(object):
    _inward = attr.ib()
    _outward = attr.ib()


def _feed(dap, pending, byte_buffer):
    context = pending.get(dap._id)
    if context is None:
        pending[dap._id] = context = dap._prepare_context()
    return dap._feed(context, byte_buffer)


@attr.s
class FeedContext(object):
    byte_buffer = attr.ib(default=attr.Factory(ClaimableByteBuffer))
    children = attr.ib(default=attr.Factory(dict))


def feed(dap, data, context):
    context.byte_buffer.write(data)
    return _feed(dap, context.children, context.byte_buffer)


def emit(dap, value):
    byte_buffer = io.BytesIO()
    dap._emit(byte_buffer, value)
    return byte_buffer.getvalue()
