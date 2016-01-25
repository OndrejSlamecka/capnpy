from capnpy import schema
from capnpy.compiler.structor import Structor


@schema.Node__Struct.__extend__
class Node__Struct:

    def emit_declaration(self, m):
        children = m.children[self.id]
        for child in children:
            child.emit_declaration(m)
        #
        ns = m.code.new_scope()
        ns.name = self.compile_name(m)
        ns.dotname = self.runtime_name(m)
        if m.pyx:
            ns.w("cdef class {name}(_Struct)")
        else:
            ns.w("class {name}(_Struct): pass")
            ns.w("{name}.__name__ = '{dotname}'")
        ns.w()

    def emit_definition(self, m):
        for child in m.children[self.id]:
            child.emit_definition(m)
        #
        ns = m.code.new_scope()
        ns.name = self.compile_name(m)
        ns.dotname = self.runtime_name(m)
        ns.data_size = self.struct.dataWordCount
        ns.ptrs_size = self.struct.pointerCount
        #
        if not m.pyx:
            # use the @extend decorator only in Pure Python mode: in pyx mode
            # it is (1) not allowed and (2) useless anyway, because we have
            # forward-declared the class, not defined it
            ns.w("@{name}.__extend__")
        #
        with ns.block("{cdef class} {name}(_Struct):"):
            ns.ww("""
                __static_data_size__ = {data_size}
                __static_ptrs_size__ = {ptrs_size}

            """)
            for child in m.children[self.id]:
                child.emit_reference_as_child(m)
            m.w()
            if self.struct.discriminantCount:
                self._emit_union_tag(m)
            if self.struct.fields is not None:
                for field in self.struct.fields:
                    field.emit(m, self)
                self._emit_ctors(m)
            self._emit_repr(m)
        ns.w()
        ns.w()

    def emit_reference_as_child(self, m):
        if self.is_nested(m) and not self.struct.isGroup:
            m.w('{shortname} = {name}', shortname=self.shortname(m),
                name=self.compile_name(m))

    def emit_delete_nested_from_globals(self, m):
        if self.is_nested(m) and not self.struct.isGroup:
            m.w("del globals()['{name}']", name=self.compile_name(m))
        for child in m.children[self.id]:
            child.emit_delete_nested_from_globals(m)

    def _emit_union_tag(self, m):
        # union tags are 16 bits, so *2
        tag_offset = self.struct.discriminantOffset * 2
        enum_items = [None] * self.struct.discriminantCount
        for field in self.struct.fields:
            if field.is_part_of_union():
                enum_items[field.discriminantValue] = m._field_name(field)
        enum_name = '%s.__tag__' % self.shortname(m)
        m.w("__tag_offset__ = %s" % tag_offset)
        m.declare_enum('__tag__', enum_name, enum_items)
        m.w()
        for i, item in enumerate(enum_items):
            m.w("def is_{item}(self): return self.which() == {i}", item=item, i=i)
        m.w()

    def _emit_ctors(self, m):
        if self.struct.discriminantCount:
            self._emit_ctors_union(m)
        else:
            self._emit_ctor_nounion(m)

    def _emit_ctor_nounion(self, m):
        ns = m.code.new_scope()
        ns.data_size = self.struct.dataWordCount
        ns.ptrs_size = self.struct.pointerCount
        ctor = Structor(m, '__new', ns.data_size, ns.ptrs_size, self.struct.fields)
        ctor.declare(m.code)
        ns.w()
        #
        with ns.def_('__init__', ['self'] + ctor.argnames):
            call = m.code.call('self.__new', ctor.argnames)
            ns.w('buf = {call}', call=call)
            ns.w('_Struct.__init__(self, buf, 0, {data_size}, {ptrs_size})')
        ns.w()

    def _emit_ctors_union(self, m):
        # suppose we have a tag whose members are 'circle' and 'square': we
        # create three ctors:
        #
        #     def __init__(self, x, y, square=undefined, circle=undefined):  ...
        #
        #     @classmethod
        #     def new_square(cls, x, y): ...
        #
        #     @classmethod
        #     def new_circle(cls, x, y): ...
        #
        # when calling __init__, one and only one of square and circle must be given. 
        #
        ns = m.code.new_scope()
        ns.data_size = self.struct.dataWordCount
        ns.ptrs_size = self.struct.pointerCount
        tag_offset = self.struct.discriminantOffset * 2
        #
        std_fields = [] # non-union fields
        tag_fields = [] # union fields
        for f in self.struct.fields:
            if f.is_part_of_union():
                tag_fields.append(f)
            else:
                std_fields.append(f)
        #
        # now, we create a separate ctor for each tag value
        for tag_field in tag_fields:
            fields = [tag_field] + std_fields
            tag_name  = m._field_name(tag_field)
            ctor_name = '__new_' + tag_name
            ctor = Structor(m, ctor_name, ns.data_size, ns.ptrs_size, fields,
                            tag_offset, tag_field.discriminantValue)
            ctor.declare(m.code)
            #
            ns.w('@classmethod')
            with ns.def_('new_' + tag_name, ['cls'] + ctor.argnames):
                call = m.code.call('cls.' + ctor_name, ctor.argnames)
                ns.w('buf = {call}', call=call)
                ns.w('return cls.from_buffer(buf, 0, {data_size}, {ptrs_size})')
            ns.w()
        #
        # finally, create the __init__
        # def __init__(cls, x, y, square=undefined, circle=undefined):
        #     if square is not undefined:
        #         self._assert_undefined(circle, 'circle', 'square')
        #         buf = cls.__new_squadre(x=x, y=y)
        #         _Struct.__init__(self, buf, 0, None)
        #         return
        #     if circle is not undefined:
        #         self._assert_undefined(square, 'square', 'circle')
        #         buf = cls.__new_circle(x=x, y=y)
        #         _Struct.__init__(self, buf, 0, None)
        #         return
        #     raise TypeError("one of the following args is required: square, circle")
        args = [m._field_name(f) for f in std_fields]
        for f in tag_fields:
            args.append('%s=_undefined' % m._field_name(f))
        with ns.block('def __init__(self, {arglist}):', arglist=m.code.args(args)):
            for tag_field in tag_fields:
                tag_field_name = m._field_name(tag_field)
                with ns.block('if {name} is not _undefined:', name=tag_field_name):
                    # emit the series of _assert_undefined, for each other tag field
                    for other_tag_field in tag_fields:
                        if other_tag_field is tag_field:
                            continue
                        ns.w('self._assert_undefined({fname}, "{fname}", "{myname}")',
                             fname=m._field_name(other_tag_field),
                             myname=tag_field_name)
                    #
                    # return cls.new_square(x=x, y=y)
                    args = [m._field_name(f) for f in std_fields]
                    args.append(m._field_name(tag_field))
                    args = ['%s=%s' % (arg, arg) for arg in args]
                    ns.w('buf = self.__new_{ctor}({args})',
                         ctor=tag_field_name, args=m.code.args(args))
                    ns.w('_Struct.__init__(self, buf, 0, {data_size}, {ptrs_size})')
                    ns.w('return')
            #
            tags = [m._field_name(f) for f in tag_fields]
            tags = ', '.join(tags)
            ns.w('raise TypeError("one of the following args is required: {tags}")',
                 tags=tags)
        ns.w()

    def _emit_repr(self, m):
        # def shortrepr(self):
        #     parts = []
        #     parts.append("x = %s" % self.x)
        #     parts.append("x = %s" % self.y)
        #     return "(%s)" % ", ".join(parts)
        #
        with m.block('def shortrepr(self):') as ns:
            fields = self.struct.fields or []
            ns.w('parts = []')
            for f in fields:
                ns.fname = f.name
                ns.fieldrepr = self._shortrepr_for_field(ns, f)
                ns.append = ns.format('parts.append("{fname} = %s" % {fieldrepr})')
                #
                if f.is_part_of_union() and f.is_pointer():
                    ns.defaultrepr = self._defaultrepr_for_type(f.slot.type)
                    ns.ww("""
                    if self.is_{fname}():
                        if self.has_{fname}():
                            {append}
                        else:
                            parts.append('{fname} = {defaultrepr}')
                    """)
                elif f.is_part_of_union():
                    ns.w("if self.is_{fname}(): {append}")
                elif f.is_pointer():
                    ns.w("if self.has_{fname}(): {append}")
                else:
                    ns.w("{append}")
            ns.w('return "(%s)" % ", ".join(parts)')

    def _shortrepr_for_field(self, ns, f):
        if f.is_float32():
            return ns.format('_float32_repr(self.{fname})')
        elif f.is_float64():
            return ns.format('_float64_repr(self.{fname})')
        if f.is_primitive() or f.is_enum():
            return ns.format('self.{fname}')
        elif f.is_bool():
            return ns.format('str(self.{fname}).lower()')
        elif f.is_void():
            return '"void"'
        elif f.is_text():
            return ns.format('_text_repr(self.{fname})')
        elif f.is_struct() or f.is_list() or f.is_group():
            return ns.format('self.{fname}.shortrepr()')
        else:
            return '"???"'

    def _defaultrepr_for_type(self, t):
        if t.is_struct():
            return '()'
        elif t.is_text() or t.is_data():
            return '""'
        elif t.is_list():
            return '[]'
        else:
            raise NotImplementedError("Unknown type")
