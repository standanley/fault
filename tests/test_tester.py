import magma as m
import fault
from bit_vector import BitVector
import random
import common


def test_tester_basic():
    circ = common.TestBasicCircuit
    tester = fault.Tester(circ)
    tester.poke(circ.I, 0)
    tester.expect(circ.O, 0)
    assert tester.serialize() == [[BitVector(0, 1), BitVector(0, 1)]]
    tester.eval()
    assert tester.serialize() == [[BitVector(0, 1), BitVector(0, 1)],
                                   [BitVector(0, 1), fault.AnyValue]]


def test_tester_clock():
    circ = common.TestBasicClkCircuit
    tester = fault.Tester(circ, circ.CLK)
    tester.poke(circ.I, 0)
    tester.expect(circ.O, 0)
    assert tester.serialize() == [
        [BitVector(0, 1), BitVector(0, 1), fault.AnyValue]
    ]
    tester.poke(circ.CLK, 0)
    assert tester.serialize() == [
        [BitVector(0, 1), BitVector(0, 1), BitVector(0, 1)]
    ]
    tester.step()
    assert tester.serialize() == [
        [BitVector(0, 1), BitVector(0, 1), BitVector(0, 1)],
        [BitVector(0, 1), fault.AnyValue, BitVector(1, 1)]
    ]


def test_tester_nested_arrays():
    circ = common.TestNestedArraysCircuit
    tester = fault.Tester(circ)
    expected = []
    for i in range(3):
        val = random.randint(0, (1 << 4) - 1)
        tester.poke(circ.I[i], val)
        tester.expect(circ.O[i], val)
        expected.append(val)
    assert tester.serialize() == [
         [fault.array.Array(expected, 3), fault.array.Array(expected, 3)]
    ]
