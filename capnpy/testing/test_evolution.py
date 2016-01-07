import py
from capnpy.testing.test_compiler import CompilerTest
from capnpy.message import loads, dumps

class TestEvolution(CompilerTest):

    def test_add_data_field(self):
        schema = """
            @0xbf5147cbbecf40c1;
            struct Old {
                x @0 :Int64;
                y @1 :Int64;
            }

            struct New {
                x @0 :Int64;
                y @1 :Int64;
                z @2 :Int64 = 42;
            }
        """
        mod = self.compile(schema)
        # 1. read an old object with a newer schema
        s = dumps(mod.Old(x=1, y=2))
        obj = loads(s, mod.New)
        assert obj.x == 1
        assert obj.y == 2
        assert obj.z == 42
        #
        # 2. read a new object with an older schema
        s = dumps(mod.New(x=1, y=2, z=3))
        obj = loads(s, mod.Old)
        assert obj.x == 1
        assert obj.y == 2
        assert obj._data_size == 3
        py.test.raises(AttributeError, "obj.z")