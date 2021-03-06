import tempfile
import magma as m
import fault
from hwtypes import BitVector
import random
from fault.actions import Poke, Expect, Eval, Step, Print, Peek
from fault.random import random_bv
import pytest
import shutil
from .common import (TestBasicCircuit, TestPeekCircuit,
                     TestDoubleNestedArraysCircuit, TestBasicClkCircuit,
                     TestNestedArraysCircuit, TestTupleCircuit,
                     define_simple_circuit, outlines)


def pytest_generate_tests(metafunc):
    if "target" in metafunc.fixturenames:
        targets = [(fault.verilator_target.VerilatorTarget, None)]
        if shutil.which("irun"):
            targets.append(
                (fault.system_verilog_target.SystemVerilogTarget, "ncsim"))
        if shutil.which("vcs"):
            targets.append(
                (fault.system_verilog_target.SystemVerilogTarget, "vcs"))
        metafunc.parametrize("target,simulator", targets)


def run(circ, actions, Target, simulator, flags=None, disp_type='on_error'):
    # set defaults
    if flags is None:
        flags = []

    # run the simulation
    with tempfile.TemporaryDirectory(dir=".") as tempdir:
        if Target == fault.verilator_target.VerilatorTarget:
            target = Target(circ, directory=f"{tempdir}/", flags=flags,
                            disp_type=disp_type)
        else:
            target = Target(circ, directory=f"{tempdir}/", simulator=simulator,
                            disp_type=disp_type)
        if Target == fault.system_verilog_target.SystemVerilogTarget:
            target.run(actions)
        else:
            target.run(actions)


def test_target_basic(target, simulator):
    """
    Test basic workflow with a simple circuit.
    """
    circ = TestBasicCircuit
    actions = (Poke(circ.I, 0), Eval(), Expect(circ.O, 0))
    run(circ, actions, target, simulator)


def test_target_peek(target, simulator):
    circ = TestPeekCircuit
    actions = []
    for i in range(3):
        x = random_bv(3)
        actions.append(Poke(circ.I, x))
        actions.append(Eval())
        actions.append(Expect(circ.O0, Peek(circ.O1)))
    run(circ, actions, target, simulator)


def test_target_nested_arrays_by_element(target, simulator):
    circ = TestNestedArraysCircuit
    expected = [random.randint(0, (1 << 4) - 1) for i in range(3)]
    actions = []
    for i, val in enumerate(expected):
        actions.append(Poke(circ.I[i], val))
    actions.append(Eval())
    for i, val in enumerate(expected):
        actions.append(Expect(circ.O[i], val))
    run(circ, actions, target, simulator)


def test_target_nested_arrays_bulk(target, simulator):
    circ = TestNestedArraysCircuit
    expected = [random.randint(0, (1 << 4) - 1) for i in range(3)]
    actions = []
    for i in range(3):
        actions.append(Poke(circ.I[i], expected[i]))
    actions.append(Eval())
    for i in range(3):
        actions.append(Expect(circ.O[i], expected[i]))
    run(circ, actions, target, simulator)


def test_target_double_nested_arrays_bulk(target, simulator):
    circ = TestDoubleNestedArraysCircuit
    expected = [[random.randint(0, (1 << 4) - 1) for i in range(3)]
                for _ in range(2)]
    actions = []
    actions.append(Poke(circ.I, expected))
    actions.append(Eval())
    actions.append(Expect(circ.O, expected))
    run(circ, actions, target, simulator)


def test_target_clock(capsys, target, simulator):
    circ = TestBasicClkCircuit
    actions = [
        Poke(circ.I, 0),
        Print("%x\n", circ.I),
        Expect(circ.O, 0),
        Poke(circ.CLK, 0),
        Print("%x\n", circ.O),
        Step(circ.CLK, 1),
        Poke(circ.I, BitVector[1](1)),
        Eval(),
        Print("%x\n", circ.O),
    ]
    run(circ, actions, target, simulator, flags=["-Wno-lint"],
        disp_type='realtime')
    messages = outlines(capsys)

    if target == fault.verilator_target.VerilatorTarget:
        assert messages[-4] == "0"
        assert messages[-3] == "0"
        assert messages[-2] == "1"
    else:
        if simulator == "ncsim":
            assert messages[-7] == "0"
            assert messages[-6] == "0"
            assert messages[-5] == "1"
        elif simulator == "vcs":
            assert messages[-10] == "0"
            assert messages[-9] == "0"
            assert messages[-8] == "1"
        else:
            raise NotImplementedError(f"Unsupported simulator: {simulator}")


def test_print_nested_arrays(capsys, target, simulator):
    circ = TestNestedArraysCircuit
    actions = [
        Poke(circ.I, [BitVector[4](i) for i in range(3)]),
    ] + [Print("%x\n", i) for i in circ.I] + [
        Eval(),
        Expect(circ.O, [BitVector[4](i) for i in range(3)]),
    ] + [Print("%x\n", i) for i in circ.O] + [
        Poke(circ.I, [BitVector[4](4 - i) for i in range(3)]),
        Eval(),
    ] + [Print("%x\n", i) for i in circ.O]

    run(circ, actions, target, simulator, flags=["-Wno-lint"],
        disp_type='realtime')
    messages = outlines(capsys)
    if target == fault.verilator_target.VerilatorTarget:
        actual = "\n".join(messages[-10:-1])
    else:
        if simulator == "ncsim":
            actual = "\n".join(messages[-13:-4])
        elif simulator == "vcs":
            actual = "\n".join(messages[-16:-7])
        else:
            raise NotImplementedError(f"Unsupported simulator: {simulator}")
    assert actual == """\
0
1
2
0
1
2
4
3
2"""


def test_print_double_nested_arrays(capsys, target, simulator):
    circ = TestDoubleNestedArraysCircuit
    actions = [
        Poke(circ.I, [[BitVector[4](i + j * 3) for i in range(3)]
                      for j in range(2)]),
    ] + [Print("%x\n", j) for i in circ.I for j in i] + [
        Eval(),
        Expect(circ.O, [[BitVector[4](i + j * 3) for i in range(3)]
                        for j in range(2)]),
    ] + [Print("%x\n", j) for i in circ.O for j in i] + [
        Poke(circ.I, [[BitVector[4](i + (j + 1) * 3) for i in range(3)]
                      for j in range(2)]),
        Eval(),
    ] + [Print("%x\n", j) for i in circ.O for j in i]
    run(circ, actions, target, simulator, flags=["-Wno-lint"],
        disp_type='realtime')
    messages = outlines(capsys)
    if target == fault.verilator_target.VerilatorTarget:
        actual = "\n".join(messages[-19:-1])
    else:
        if simulator == "ncsim":
            actual = "\n".join(messages[-22:-4])
        elif simulator == "vcs":
            actual = "\n".join(messages[-25:-7])
        else:
            raise NotImplementedError(f"Unsupported simulator: {simulator}")
    assert actual == """\
0
1
2
3
4
5
0
1
2
3
4
5
3
4
5
6
7
8\
""", out


def test_target_tuple(target, simulator):
    circ = TestTupleCircuit
    actions = [
        Poke(circ.I.a, 5),
        Poke(circ.I.b, 11),
        Eval(),
        Expect(circ.O.a, 5),
        Expect(circ.O.b, 11),
    ]
    run(circ, actions, target, simulator)


# @pytest.mark.parametrize("width", range(1, 33))
# Select random subset of range to speed up test, TODO: Maybe actually make
# this random
@pytest.mark.parametrize("width", [1, 4, 5, 7, 8, 11, 13, 16, 19, 22, 24, 27,
                                   31, 32])
def test_target_sint_sign_extend(width, target, simulator):
    circ = define_simple_circuit(
        m.SInt[width], f"test_target_sint_sign_extend_{width}")
    actions = [
        Poke(circ.I, -2),
        Eval(),
        Expect(circ.O, -2),
    ]
    run(circ, actions, target, simulator)
