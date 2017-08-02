"""
Reimplementation of CPython's hashing algorithm for many builtin
types. The idea is that if you have C variables, you can compute fast hashes
*without* having to allocate real Python object
"""
cimport cython

cdef  extern from "Python.h":
    int PY_MAJOR_VERSION
cdef int PY3 = PY_MAJOR_VERSION == 3

cdef extern from "_hash.h":
    ctypedef struct _Py_HashSecret_t:
        long prefix
        long suffix
    _Py_HashSecret_t HashSecret

    ctypedef size_t Py_hash_t
    cdef Py_hash_t strhash_f(const void *src, Py_ssize_t len)
    long HASH_MASK


cpdef long strhash(bytes a, long start, long size):
    cdef long maxlen = len(a)
    if start >= maxlen or size == 0:
        return 0
    if size > maxlen:
        size = maxlen-start

    cdef const unsigned char* p = a
    p += start

    if PY3:
        return _strhash_3(p, size)
    return _strhash_2(p, size)

cpdef long inthash(long v):
    if PY3:
        return _inthash_3(v)
    return _inthash_2(v)

cpdef long longhash(unsigned long v):
    if PY3:
        return _longhash_3(v)
    return _longhash_2(v)


### Python 2 ##################################################
cdef inline long _strhash_2(const unsigned char* p, long size):
    #
    cdef long n = size
    cdef long x
    #
    x = HashSecret.prefix
    x ^= p[0]<<7
    while True:
        n -= 1
        if n < 0:
            break
        x = (1000003*x) ^ p[0]
        p += 1
    x ^= size
    x ^= HashSecret.suffix
    if x == -1:
        x = -2
    return x

cdef inline long _inthash_2(long v):
    if v == -1:
        return -2
    return v

cdef inline long _longhash_2(unsigned long v):
    return _inthash_2(<long>v)
### END Python 2 ###############################################

### Python 3 ###################################################
cdef inline long _strhash_3(const unsigned char* p, long size):
    return strhash_f(p, size)

cdef inline long _inthash_3(long v):
    if v == -9223372036854775808: # minlong
        return -4

    cdef sign = 1
    if v < 0:
        sign = -1
        v = -(v)

    v = (v & HASH_MASK) + (v >> 61)
    if v >= HASH_MASK:
        v -= HASH_MASK

    v *= sign
    if v == -1:
        return -2
    return v


cdef inline long _longhash_3(unsigned long v):
    v = (v & HASH_MASK) + (v >> 61)
    if v >= HASH_MASK:
        v -= HASH_MASK
    return v
### END Python 3 ###############################################


# tuple hashing algorithm. The magic numbers and the algorithm itself are
# taken from python/Objects/tupleobject.c:tuplehash

# Cython-only interface
cdef long tuplehash(long hashes[], long len):
    cdef long mult = 1000003
    cdef long x = 0x345678
    cdef long y
    while True:
        len -= 1
        if len < 0:
            break
        # equivalent to y = *hashes++
        y = hashes[0]
        hashes += 1
        #
        x = (x ^ y) * mult
        mult += <long>(82520 + len + len)
    #
    x += 97531
    if x == -1:
        x = -2
    return x

# Python interface, used by tests
from cpython cimport array
import array
cpdef long __tuplehash_for_tests(object hashes):
    cdef array.array a = array.array('l', hashes)
    return tuplehash(a.data.as_longs, len(a))
