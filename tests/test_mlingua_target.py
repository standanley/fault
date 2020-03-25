import magma as m
import fault
import tempfile
import pytest
from pathlib import Path
from .common import pytest_sim_params, TestBasicCircuit
from fault.real_type import RealIn, RealOut, Real

def plot(xs, ys):
    import matplotlib.pyplot as plt
    plt.plot(xs, ys, '*')
    plt.grid()
    plt.show()

def pytest_generate_tests(metafunc):
    #pytest_sim_params(metafunc, 'verilator', 'system-verilog')
    #pytest_sim_params(metafunc, 'spice')
    pytest_sim_params(metafunc, 'system-verilog')

#@pytest.mark.skip(reason='Not yet implemented')
def test_system_verilog(target, simulator):
    print('target, sim', target, simulator)
    # TODO delete the next line; my iverilog is just broken so I can't test it
    simulator = 'ncsim'
    
    # class RealPwl(Real):
    #     pass
    # RealPwlIn = m.In(RealPwl)
    
    circ = m.DeclareCircuit(
        'mlingua_add',
        'a_val', RealIn,
        'b_val', RealIn,
        'c_val', RealOut,
    )
    
    #print(circ.a_val, type(circ.a_val))
    #print(circ.b_val, type(circ.b_val))
    #asdf
    
    for p in [circ.a_val, circ.b_val, circ.c_val]:
        p.representation = 'mlingua'
    
    tester = fault.Tester(circ)
    #tester.zero_inputs()
    tester.poke(circ.a_val, 0.0)
    tester.delay(100e-9)
    tester.poke(circ.a_val, 5.0)
    #tester.eval()
    #tester.expect(circ.O, 1)

    ## register clock
    #tester.poke(circ.I, 0, delay={
    #    'freq': 0.125,
    #    'duty_cycle': 0.625,
    #    # take default initial_value of 0
    #    })

    #tester.expect(circ.O, 1)

    #tester.print("%08x", circ.O)
    
    #with tempfile.TemporaryDirectory(dir=".") as _dir:
    #with open('build/') as _dir:
    
    # set up some mLingua things
    defines = {'NCVLOG':True, 'DAVE_TIMEUNIT':'1fs'}
    inc_dirs = ['${mLINGUA_DIR}/samples', 
                '${mLINGUA_DIR}/samples/prim', 
                '${mLINGUA_DIR}/samples/stim',  
                '${mLINGUA_DIR}/samples/meas',
                '${mLINGUA_DIR}/samples/misc']
    flags = ['+libext+.sv',
             '+libext+.vp',
             '-loadpli1 ${mLINGUA_DIR}/samples/pli/libpli.so:dave_boot']
    # for mLingua to work the following file needs to be imported at the top of the tb
    # Path('${mLINGUA_DIR}/samples/mLingua_pwl.vh').resolve()
    
    ext_libs = [Path('tests/verilog/mlingua_add.sv').resolve()]
    #flags.append('-Wno-fatal')
    
    if True:
        _dir = 'build'
        if target == "verilator":
            assert False
            tester.compile_and_run(target, directory=_dir, flags=["-Wno-fatal"])
        else:
            tester.compile_and_run(target,
                                   directory=_dir,
                                   simulator=simulator,
                                   defines=defines,
                                   inc_dirs=inc_dirs,
                                   flags=flags,
                                   ext_libs=ext_libs,
                                   ext_model_file=True)
    print('JUST FINISHED COMPILENANDRUN')


#@pytest.mark.skip(reason='Turn this back on later')
def test_sin_spice(vsup=1.5, vil_rel=0.4, vih_rel=0.6,
    vol_rel=0.1, voh_rel=0.9):
    # TODO make pytest choose target/simulator
    target = 'spice'
    simulator = 'ngspice'
    


    # declare circuit
    myinv = m.DeclareCircuit(
        'myinv',
        'in_', fault.RealIn,
        'out', fault.RealOut,
        'vdd', fault.RealIn,
        'vss', fault.RealIn
    )

    # wrap if needed
    if target == 'verilog-ams':
        dut = fault.VAMSWrap(myinv)
    else:
        dut = myinv

    # define the test
    tester = fault.Tester(dut)
    tester.poke(dut.vdd, vsup)
    tester.poke(dut.vss, 0)
    freq = 1e3
    tester.poke(dut.in_, 0, delay = {
        'type': 'sin',
        'freq': freq,
        'amplitude': 0.4,
        'offset': 0.6,
        'phase_degrees': 90
        })

    num_reads = 100
    xs = []
    dt = 1/(freq * 50)
    gets = []
    for k in range(num_reads):
        gets.append(tester.get_value(dut.in_))
        tester.delay(dt)
        xs.append(k*dt)

    #for k in [.4, .5, .6]:
    #    in_ = k * vsup
    #    tester.poke(dut.in_, in_)
    #    # We might not know the expected value now but will want to check later
    #    tester.expect(dut.out, 0, save_for_later=True)

    

    # set options
    kwargs = dict(
        target=target,
        simulator=simulator,
        model_paths=[Path('tests/spice/myinv.sp').resolve()],
        vsup=vsup,
        tmp_dir=True,
        clock_step_delay = 0
    )
    if target == 'verilog-ams':
        kwargs['use_spice'] = ['myinv']

    # run the simulation
    tester.compile_and_run(**kwargs)

    ys = []
    for k in range(num_reads):
        value = gets[k].value
        ys.append(value)
        print('%2d\t'%k, value)

    #plot(xs, ys)