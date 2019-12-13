import warnings
from fault.verilog_target import VerilogTarget, verilog_name
import magma as m
from pathlib import Path
import fault.actions as actions
from hwtypes import (BitVector, AbstractBitVectorMeta, AbstractBit,
                     AbstractBitVector)
import fault.value_utils as value_utils
from fault.select_path import SelectPath
from fault.wrapper import PortWrapper
from fault.subprocess_run import subprocess_run
import fault
import fault.expression as expression
from fault.real_type import RealKind
import os
from numbers import Number


src_tpl = """\
module {circuit_name}_tb;
{declarations}

    {circuit_name} #(
        {param_list}
    ) dut (
        {port_list}
    );

    initial begin
{initial_body}
        #20 $finish;
    end

endmodule
"""


class SystemVerilogTarget(VerilogTarget):
    def __init__(self, circuit, circuit_name=None, directory="build/",
                 skip_compile=None, magma_output="coreir-verilog",
                 magma_opts=None, include_verilog_libraries=None,
                 simulator=None, timescale="1ns/1ns", clock_step_delay=5,
                 num_cycles=10000, dump_waveforms=True, dump_vcd=None,
                 no_warning=False, sim_env=None, ext_model_file=None,
                 ext_libs=None, defines=None, flags=None, inc_dirs=None,
                 ext_test_bench=False, top_module=None, ext_srcs=None,
                 use_input_wires=False, parameters=None, disp_type='on_error',
                 waveform_file=None):
        """
        circuit: a magma circuit

        circuit_name: the name of the circuit (default is circuit.name)

        directory: directory to use for generating collateral, buildling, and
                   running simulator

        skip_compile: (boolean) whether or not to compile the magma circuit

        magma_output: Set the output parameter to m.compile
                      (default coreir-verilog)

        magma_opts: Options dictionary for `magma.compile` command

        simulator: "ncsim", "vcs", "iverilog", or "vivado"

        timescale: Set the timescale for the verilog simulation
                   (default 1ns/1ns)

        clock_step_delay: Set the number of steps to delay for each step of the
                          clock

        sim_env: Environment variable definitions to use when running the
                 simulator.  If not provided, the value from os.environ will
                 be used.

        ext_model_file: If True, don't include the assumed model name in the
                        list of Verilog sources.  The assumption is that the
                        user has already taken care of this via
                        include_verilog_libraries.

        ext_libs: List of external files that should be treated as "libraries",
                  meaning that the simulator will look in them for module
                  definitions but not try to compile them otherwise.

        defines: Dictionary mapping Verilog DEFINE variable names to their
                 values.  If any value is None, that define simply defines
                 the variable without giving it a specific value.

        flags: List of additional arguments that should be passed to the
               simulator.

        inc_dirs: List of "include directories" to search for the `include
                  statement.

        ext_test_bench: If True, do not compile testbench actions into a
                        SystemVerilog testbench and instead simply run a
                        simulation of an existing (presumably manually
                        created) testbench.  Can be used to get started
                        integrating legacy testbenches into the fault
                        framework.

        top_module: Name of the top module in the design.  If the value is
                    None and ext_test_bench is False, then top_module will
                    automatically be filled with the name of the module
                    containing the generated testbench code.

        ext_srcs: Shorter alias for "include_verilog_libraries" argument.
                  If both "include_verilog_libraries" and ext_srcs are
                  specified, then the sources from include_verilog_libraries
                  will be processed first.

        use_input_wires: If True, drive DUT inputs through wires that are in
                         turn assigned to a reg.

        parameters: Dictionary of parameters to be defined for the DUT.

        disp_type: 'on_error', 'realtime'.  If 'on_error', only print if there
                   is an error.  If 'realtime', print out STDOUT as lines come
                   in, then print STDERR after the process completes.

        dump_waveforms: Enable tracing of internal values

        waveform_file: name of file to dump waveforms (default is
                       "waveform.vcd" for ncsim and "waveform.vpd" for vcs)
        """
        # set default for list of external sources
        if include_verilog_libraries is None:
            include_verilog_libraries = []
        if ext_srcs is None:
            ext_srcs = []
        include_verilog_libraries = include_verilog_libraries + ext_srcs

        # set default for there being an external model file
        if ext_model_file is None:
            ext_model_file = ext_test_bench

        # set default for whether magma compilation should happen
        if skip_compile is None:
            skip_compile = ext_model_file

        # set default for magma compilation options
        magma_opts = magma_opts if magma_opts is not None else {}

        # call the super constructor
        super().__init__(circuit, circuit_name, directory, skip_compile,
                         include_verilog_libraries, magma_output,
                         magma_opts)

        # sanity check
        if simulator is None:
            raise ValueError("Must specify simulator when using system-verilog"
                             " target")
        if simulator not in {"vcs", "ncsim", "iverilog", "vivado"}:
            raise ValueError(f"Unsupported simulator {simulator}")

        # save settings
        self.simulator = simulator
        self.timescale = timescale
        self.clock_step_delay = clock_step_delay
        self.num_cycles = num_cycles
        self.dump_waveforms = dump_waveforms
        if dump_vcd is not None:
            warnings.warn("tester.compile_and_run parameter dump_vcd is "
                          "deprecated; use dump_waveforms instead.",
                          DeprecationWarning)
            self.dump_waveforms = dump_vcd
        self.no_warning = no_warning
        self.declarations = []
        self.sim_env = sim_env
        self.ext_model_file = ext_model_file
        self.ext_libs = ext_libs if ext_libs is not None else []
        self.defines = defines if defines is not None else {}
        self.flags = flags if flags is not None else []
        self.inc_dirs = inc_dirs if inc_dirs is not None else []
        self.ext_test_bench = ext_test_bench
        self.top_module = top_module
        self.use_input_wires = use_input_wires
        self.parameters = parameters if parameters is not None else {}
        self.disp_type = disp_type
        self.waveform_file = waveform_file
        if self.waveform_file is None and self.dump_waveforms:
            if self.simulator == "vcs":
                self.waveform_file = "waveforms.vpd"
            elif self.simulator in {"ncsim", "iverilog", "vivado"}:
                self.waveform_file = "waveforms.vcd"
            else:
                raise NotImplementedError(self.simulator)

    def add_decl(self, *decls):
        self.declarations.extend(decls)

    def make_name(self, port):
        if isinstance(port, PortWrapper):
            port = port.select_path
        if isinstance(port, SelectPath):
            if len(port) > 2:
                name = f"dut.{port.system_verilog_path}"
            else:
                # Top level ports assign to the external reg
                name = verilog_name(port[-1].name)
        elif isinstance(port, fault.WrappedVerilogInternalPort):
            name = f"dut.{port.path}"
        else:
            name = verilog_name(port.name)
        return name

    def process_peek(self, value):
        if isinstance(value.port, fault.WrappedVerilogInternalPort):
            return f"dut.{value.port.path}"
        else:
            return f"{value.port.name}"

    def make_var(self, i, action):
        if isinstance(action._type, AbstractBitVectorMeta):
            self.declarations.append(
                f"reg [{action._type.size - 1}:0] {action.name};")
            return []
        raise NotImplementedError(action._type)

    def make_file_scan_format(self, i, action):
        var_args = ", ".join(f"{var.name}" for var in action.args)
        return [f"$fscanf({action.file.name_without_ext}_file, "
                f"\"{action._format}\", {var_args});"]

    def process_value(self, port, value):
        if isinstance(value, BitVector):
            value = f"{len(value)}'d{value.as_uint()}"
        elif isinstance(port, m.SIntType) and value < 0:
            port_len = len(port)
            value = BitVector[port_len](value).as_uint()
            value = f"{port_len}'d{value}"
        elif value is fault.UnknownValue:
            value = "'X"
        elif value is fault.HiZ:
            value = "'Z"
        elif isinstance(value, actions.Peek):
            value = self.process_peek(value)
        elif isinstance(value, PortWrapper):
            value = f"dut.{value.select_path.system_verilog_path}"
        elif isinstance(value, actions.FileRead):
            new_value = f"{value.file.name_without_ext}_in"
            value = new_value
        elif isinstance(value, expression.Expression):
            value = f"({self.compile_expression(value)})"
        return value

    def compile_expression(self, value):
        if isinstance(value, expression.BinaryOp):
            left = self.compile_expression(value.left)
            right = self.compile_expression(value.right)
            op = value.op_str
            return f"{left} {op} {right}"
        elif isinstance(value, expression.UnaryOp):
            operand = self.compile_expression(value.operand)
            op = value.op_str
            return f"{op} {operand}"
        elif isinstance(value, PortWrapper):
            return f"dut.{value.select_path.system_verilog_path}"
        elif isinstance(value, actions.Peek):
            return self.process_peek(value)
        elif isinstance(value, actions.Var):
            value = value.name
        return value

    def make_poke(self, i, action):
        name = self.make_name(action.port)
        # For now we assume that verilog can handle big ints
        value = self.process_value(action.port, action.value)
        # Build up the poke action, including delay
        retval = []
        retval += [f'{name} = {value};']
        if action.delay is not None:
            retval += [f'#({action.delay}*1s);']
        return retval

    def make_delay(self, i, action):
        return [f'#({action.time}*1s);']

    def make_print(self, i, action):
        # build up argument list for the $write command
        args = []
        args.append(f'"{action.format_str}"')
        for port in action.ports:
            if isinstance(port, (Number, AbstractBit, AbstractBitVector)):
                args.append(f'{port}')
            else:
                args.append(f'{self.make_name(port)}')
        args = ', '.join(args)
        return [f'$write({args});']

    def make_loop(self, i, action):
        self.declarations.append(f"integer {action.loop_var};")
        code = []
        code.append(f"for ({action.loop_var} = 0;"
                    f" {action.loop_var} < {action.n_iter};"
                    f" {action.loop_var}++) begin")

        for inner_action in action.actions:
            # TODO: Handle relative offset of sub-actions
            inner_code = self.generate_action_code(i, inner_action)
            code += ["    " + x for x in inner_code]

        code.append("end")
        return code

    def make_file_open(self, i, action):
        if action.file.mode not in {"r", "w"}:
            raise NotImplementedError(action.file.mode)
        name = action.file.name_without_ext
        bit_size = action.file.chunk_size * 8 - 1
        self.declarations.append(
            f"reg [{bit_size}:0] {name}_in;")
        self.declarations.append(f"integer {name}_file;")
        code = f"""\
{name}_file = $fopen(\"{action.file.name}\", \"{action.file.mode}\");
if (!{name}_file) $error("Could not open file {action.file.name}: %0d", {name}_file);
"""  # noqa
        return code.splitlines()

    def make_file_close(self, i, action):
        return [f"$fclose({action.file.name_without_ext}_file);"]

    def make_file_read(self, i, action):
        decl = f"integer __i;"
        if decl not in self.declarations:
            self.declarations.append(decl)
        if action.file.endianness == "big":
            loop_expr = f"__i = {action.file.chunk_size - 1}; __i >= 0; __i--"
        else:
            loop_expr = f"__i = 0; __i < {action.file.chunk_size}; __i++"
        code = f"""\
{action.file.name_without_ext}_in = 0;
for ({loop_expr}) begin
    {action.file.name_without_ext}_in |= $fgetc({action.file.name_without_ext}_file) << (8 * __i);
end
"""  # noqa
        return code.splitlines()

    def make_file_write(self, i, action):
        # figure out how to loop over bytes to be written
        value = self.make_name(action.value)
        mask_size = action.file.chunk_size * 8
        decl = f"integer __i;"
        if decl not in self.declarations:
            self.declarations.append(decl)
        if action.file.endianness == "big":
            loop_expr = f"__i = {action.file.chunk_size - 1}; __i >= 0; __i--"
        else:
            loop_expr = f"__i = 0; __i < {action.file.chunk_size}; __i++"

        # build up the loop expression
        code = []
        code += [f'for ({loop_expr}) begin']
        file_fd = f'{action.file.name_without_ext}_file'
        byte_expr = f"({value} >> (8 * __i)) & {mask_size}'hFF"
        if self.simulator == 'iverilog':
            code += [f'    $fputc({byte_expr}, {file_fd});']
        else:
            code += [f'    $fwrite({file_fd}, "%c", {byte_expr});']
        code += ['end']

        # return the loop expression
        return code

    def make_expect(self, i, action):
        # don't do anything if any value is OK
        if value_utils.is_any(action.value):
            return []

        # determine the exact name of the signal
        name = self.make_name(action.port)

        # TODO: add something like "make_read_name" and "make_write_name"
        # so that reading inout signals has more uniform behavior across
        # expect, peek, etc.
        if actions.is_inout(action.port):
            name = self.input_wire(name)

        # determine the name of the signal for debugging purposes
        if isinstance(action.port, SelectPath):
            debug_name = action.port[-1].name
        elif isinstance(action.port, fault.WrappedVerilogInternalPort):
            debug_name = name
        else:
            debug_name = action.port.name

        # determine the value to be checked
        value = self.process_value(action.port, action.value)

        # determine the condition and error body
        err_hdr = ''
        err_hdr += f'Failed on action={i} checking port {debug_name}'
        if action.traceback is not None:
            err_hdr += f' with traceback {action.traceback}'
        if action.above is not None:
            if action.below is not None:
                # must be in range
                cond = f'({action.above} <= {name}) && ({name} <= {action.below})'  # noqa
                err_msg = 'Expected %0f to %0f, got %0f'
                err_args = [action.above, action.below, name]
            else:
                # must be above
                cond = f'{action.above} <= {name}'
                err_msg = 'Expected above %0f, got %0f'
                err_args = [action.above, name]
        else:
            if action.below is not None:
                # must be below
                cond = f'{name} <= {action.below}'
                err_msg = 'Expected below %0f, got %0f'
                err_args = [action.below, name]
            else:
                # equality comparison
                if action.strict:
                    cond = f'{name} === {value}'
                else:
                    cond = f'{name} == {value}'
                err_msg = 'Expected %x, got %x'
                err_args = [value, name]

        # construct the body of the $error call
        err_fmt_str = f'"{err_hdr}.  {err_msg}."'
        err_body = [err_fmt_str] + err_args
        err_body = ','.join([str(elem) for elem in err_body])

        # return a snippet of verilog implementing the assertion
        retval = []
        retval += [f'if (!({cond})) begin']
        retval += [self.make_line(f'$error({err_body});', tabs=1)]
        retval += ['end']
        return retval

    def make_eval(self, i, action):
        # Emulate eval by inserting a delay
        return ['#1;']

    def make_step(self, i, action):
        name = verilog_name(action.clock.name)
        code = []
        for step in range(action.steps):
            code.append(f"#{self.clock_step_delay} {name} ^= 1;")
        return code

    def make_while(self, i, action):
        code = []
        cond = self.compile_expression(action.loop_cond)

        code.append(f"while ({cond}) begin")

        for inner_action in action.actions:
            # TODO: Handle relative offset of sub-actions
            inner_code = self.generate_action_code(i, inner_action)
            code += ["    " + x for x in inner_code]

        code.append("end")

        return code

    def make_if(self, i, action):
        code = []
        cond = self.compile_expression(action.cond)

        code.append(f"if ({cond}) begin")

        for inner_action in action.actions:
            # TODO: Handle relative offset of sub-actions
            inner_code = self.generate_action_code(i, inner_action)
            code += ["    " + x for x in inner_code]

        code.append("end")

        if action.else_actions:
            code[-1] += " else begin"
            for inner_action in action.else_actions:
                # TODO: Handle relative offset of sub-actions
                inner_code = self.generate_action_code(i, inner_action)
                code += ["    " + x for x in inner_code]

            code.append("end")

        return code

    def generate_recursive_port_code(self, name, type_, power_args):
        port_list = []
        if isinstance(type_, m.ArrayKind):
            for j in range(type_.N):
                result = self.generate_port_code(
                    name + "_" + str(j), type_.T, power_args
                )
                port_list.extend(result)
        elif isinstance(type_, m.TupleKind):
            for k, t in zip(type_.Ks, type_.Ts):
                result = self.generate_port_code(
                    name + "_" + str(k), t, power_args
                )
                port_list.extend(result)
        return port_list

    def generate_port_code(self, name, type_, power_args):
        is_array_of_bits = isinstance(type_, m.ArrayKind) and \
            not isinstance(type_.T, m.BitKind)
        if is_array_of_bits or isinstance(type_, m.TupleKind):
            return self.generate_recursive_port_code(name, type_, power_args)
        else:
            width_str = ""
            connect_to = f"{name}"
            if isinstance(type_, m.ArrayKind) and \
                    isinstance(type_.T, m.BitKind):
                width_str = f"[{len(type_) - 1}:0] "
            if isinstance(type_, RealKind):
                t = "real"
            elif name in power_args.get("supply0s", []):
                t = "supply0"
            elif name in power_args.get("supply1s", []):
                t = "supply1"
            elif name in power_args.get("tris", []):
                t = "tri"
            elif type_.isoutput():
                t = "wire"
            elif type_.isinout() or (type_.isinput() and self.use_input_wires):
                # declare a reg and assign it to a wire
                # that wire will then be connected to the
                # DUT pin
                connect_to = self.input_wire(name)
                decls = [f'reg {width_str}{name};',
                         f'wire {width_str}{connect_to};',
                         f'assign {connect_to}={name};']
                decls = [self.make_line(decl, tabs=1) for decl in decls]
                self.add_decl(*decls)

                # set the signal type to None to avoid re-declaring
                # connect_to
                t = None
            elif type_.isinput():
                t = "reg"
            else:
                raise NotImplementedError()

            # declare the signal that will be connected to the pin, if needed
            if t is not None:
                decl = self.make_line(f'{t} {width_str}{connect_to};', tabs=1)
                self.add_decl(decl)

            # return the wiring statement describing how the testbench signal
            # is connected to the DUT
            return [f".{name}({connect_to})"]

    def generate_code(self, actions, power_args, tab='    '):
        initial_body = ""
        port_list = []
        for name, type_ in self.circuit.IO.ports.items():
            result = self.generate_port_code(name, type_, power_args)
            port_list.extend(result)

        if self.dump_waveforms and self.simulator == "vcs":
            initial_body += f"""
        $vcdplusfile("{self.waveform_file}");
        $vcdpluson();
        $vcdplusmemon();
"""
        elif self.dump_waveforms and self.simulator in {"iverilog", "vivado"}:
            # https://iverilog.fandom.com/wiki/GTKWAVE
            initial_body += f"""
        $dumpfile("{self.waveform_file}");
        $dumpvars(0, dut);
"""

        for i, action in enumerate(actions):
            code = self.generate_action_code(i, action)
            for line in code:
                initial_body += f"        {line}\n"

        param_list = [f'.{name}({value})'
                      for name, value in self.parameters.items()]

        src = src_tpl.format(
            declarations="\n".join(self.declarations),
            initial_body=initial_body,
            port_list=f',\n{2*tab}'.join(port_list),
            param_list=f',\n{2*tab}'.join(param_list),
            circuit_name=self.circuit_name
        )

        return src

    def run(self, actions, power_args=None):
        # set defaults
        power_args = power_args if power_args is not None else {}

        # assemble list of sources files
        vlog_srcs = []
        if not self.ext_test_bench:
            tb_file = self.write_test_bench(actions=actions,
                                            power_args=power_args)
            vlog_srcs += [tb_file]
        if not self.ext_model_file:
            vlog_srcs += [self.verilog_file]
        vlog_srcs += self.include_verilog_libraries

        # generate simulator commands
        if self.simulator == 'ncsim':
            # Compile and run simulation
            cmd_file = self.write_ncsim_tcl()
            sim_cmd = self.ncsim_cmd(sources=vlog_srcs, cmd_file=cmd_file)
            sim_err_str = None
            # Skip "bin_cmd"
            bin_cmd = None
            bin_err_str = None
        elif self.simulator == 'vivado':
            # Compile and run simulation
            cmd_file = self.write_vivado_tcl(sources=vlog_srcs)
            sim_cmd = self.vivado_cmd(cmd_file=cmd_file)
            sim_err_str = ['CRITICAL WARNING', 'ERROR', 'Fatal', 'Error']
            # Skip "bin_cmd"
            bin_cmd = None
            bin_err_str = None
        elif self.simulator == 'vcs':
            # Compile simulation
            # TODO: what error strings are expected at this stage?
            sim_cmd, bin_file = self.vcs_cmd(sources=vlog_srcs)
            sim_err_str = None
            # Run simulation
            bin_cmd = [bin_file]
            bin_err_str = 'Error'
        elif self.simulator == 'iverilog':
            # Compile simulation
            sim_cmd, bin_file = self.iverilog_cmd(sources=vlog_srcs)
            sim_err_str = ['syntax error', 'I give up.']
            # Run simulation
            bin_cmd = ['vvp', '-N', bin_file]
            bin_err_str = 'ERROR'
        else:
            raise NotImplementedError(self.simulator)

        # add any extra flags
        sim_cmd += self.flags

        # compile the simulation
        subprocess_run(sim_cmd, cwd=self.directory, env=self.sim_env,
                       err_str=sim_err_str, disp_type=self.disp_type)

        # run the simulation binary (if applicable)
        if bin_cmd is not None:
            subprocess_run(bin_cmd, cwd=self.directory, env=self.sim_env,
                           err_str=bin_err_str, disp_type=self.disp_type)

    def write_test_bench(self, actions, power_args):
        # determine the path of the testbench file
        tb_file = self.directory / Path(f'{self.circuit_name}_tb.sv')
        tb_file = tb_file.absolute()

        # generate source code of test bench
        src = self.generate_code(actions, power_args)

        # If there's an old test bench file, ncsim might not recompile based on
        # the timestamp (1s granularity), see
        # https://github.com/StanfordAHA/lassen/issues/111
        # so we check if the new/old file have the same timestamp and edit them
        # to force an ncsim recompile
        check_timestamp = os.path.isfile(tb_file)
        if check_timestamp:
            check_timestamp = True
            old_stat_result = os.stat(tb_file)
            old_times = (old_stat_result.st_atime, old_stat_result.st_mtime)
        with open(tb_file, "w") as f:
            f.write(src)
        if check_timestamp:
            new_stat_result = os.stat(tb_file)
            new_times = (new_stat_result.st_atime, new_stat_result.st_mtime)
            if old_times[0] <= new_times[0] or new_times[1] <= old_times[1]:
                new_times = (old_times[0] + 1, old_times[1] + 1)
                os.utime(tb_file, times=new_times)

        # return the path to the testbench location
        return tb_file

    @staticmethod
    def input_wire(name):
        return f'__{name}_wire'

    @staticmethod
    def make_line(text, tabs=0, tab='    ', nl='\n'):
        return f'{tabs*tab}{text}{nl}'

    def write_ncsim_tcl(self):
        # construct the TCL commands to run the Incisive/Xcelium simulation
        tcl_cmds = []
        if self.dump_waveforms:
            tcl_cmds += [f'database -open -vcd vcddb -into {self.waveform_file} -default -timescale ps']  # noqa
            tcl_cmds += [f'probe -create -all -vcd -depth all']
        tcl_cmds += [f'run {self.num_cycles}ns']
        tcl_cmds += [f'quit']

        # write the command file
        cmd_file = Path(f'{self.circuit_name}_cmd.tcl')
        with open(self.directory / cmd_file, 'w') as f:
            f.write('\n'.join(tcl_cmds))

        # return the path to the command file
        return cmd_file

    def write_vivado_tcl(self, sources=None, proj_name='project', proj_dir=None,
                         proj_part=None):
        # set defaults
        if sources is None:
            sources = []
        if proj_dir is None:
            proj_dir = f'{proj_name}'

        # build up a list of commands to run a simulation with Vivado
        tcl_cmds = []

        # create the project
        create_proj = f'create_project -force {proj_name} {proj_dir}'
        if proj_part is not None:
            create_proj += f' -part "{proj_part}"'
        tcl_cmds += [create_proj]

        # add source files and library files
        vlog_add_files = []
        vlog_add_files += [f'{src}' for src in sources]
        vlog_add_files += [f'{lib}' for lib in self.ext_libs]
        if len(vlog_add_files) > 0:
            vlog_add_files = ' '.join(vlog_add_files)
            tcl_cmds += [f'add_files "{vlog_add_files}"']

        # add include file search paths
        if len(self.inc_dirs) > 0:
            vlog_inc_dirs = ' '.join(f'{dir_}' for dir_ in self.inc_dirs)
            tcl_cmds += [f'set_property include_dirs "{vlog_inc_dirs}" [get_fileset sim_1]']  # noqa

        # add verilog `defines
        vlog_defs = []
        for key, val in self.defines.items():
            if val is not None:
                vlog_defs += [f'{key}={val}']
            else:
                vlog_defs += [f'{key}']
        if len(vlog_defs) > 0:
            vlog_defs = ' '.join(vlog_defs)
            tcl_cmds += [f'set_property -name "verilog_define" -value {{{vlog_defs}}} -objects [get_fileset sim_1]']  # noqa

        # set the name of the top module
        if self.top_module is None and not self.ext_test_bench:
            top = f'{self.circuit_name}_tb'
        else:
            top = self.top_module
        if top is not None:
            tcl_cmds += [f'set_property -name top -value {top} -objects [get_fileset sim_1]']  # noqa
        else:
            # have Vivado pick the top module automatically if not specified
            tcl_cmds += [f'update_compile_order -fileset sim_1']

        # run until $finish (as opposed to running for a certain amount of time)
        tcl_cmds += [f'set_property -name "xsim.simulate.runtime" -value "-all" -objects [get_fileset sim_1]']  # noqa

        # run the simulation
        tcl_cmds += ['launch_simulation']

        # write the command file
        cmd_file = Path(f'{self.circuit_name}_cmd.tcl')
        with open(self.directory / cmd_file, 'w') as f:
            f.write('\n'.join(tcl_cmds))

        # return the path to the command file
        return cmd_file

    def def_args(self, prefix):
        retval = []
        for key, val in self.defines.items():
            def_arg = f'{prefix}{key}'
            if val is not None:
                def_arg += f'={val}'
            retval += [def_arg]
        return retval

    def ncsim_cmd(self, sources, cmd_file):
        cmd = []

        # binary name
        cmd += ['irun']

        # determine the name of the top module
        if self.top_module is None and not self.ext_test_bench:
            top = f'{self.circuit_name}_tb'
        else:
            top = self.top_module

        # send name of top module to the simulator
        if top is not None:
            cmd += ['-top', f'{top}']

        # timescale
        cmd += ['-timescale', f'{self.timescale}']

        # TCL commands
        cmd += ['-input', f'{cmd_file}']

        # source files
        cmd += [f'{src}' for src in sources]

        # library files
        for lib in self.ext_libs:
            cmd += ['-v', f'{lib}']

        # include directory search path
        for dir_ in self.inc_dirs:
            cmd += ['-incdir', f'{dir_}']

        # define variables
        cmd += self.def_args(prefix='+define+')

        # misc flags
        cmd += ['-access', '+rwc']
        cmd += ['-notimingchecks']
        if self.no_warning:
            cmd += ['-neverwarn']

        # return arg list
        return cmd

    def vivado_cmd(self, cmd_file):
        cmd = []

        # binary name
        cmd += ['vivado']

        # run from an external script
        cmd += ['-mode', 'batch']

        # specify path to script
        cmd += ['-source', f'{cmd_file}']

        # turn off annoying output
        cmd += ['-nolog']
        cmd += ['-nojournal']

        # return arg list
        return cmd

    def vcs_cmd(self, sources):
        cmd = []

        # binary name
        cmd += ['vcs']

        # timescale
        cmd += [f'-timescale={self.timescale}']

        # source files
        cmd += [f'{src}' for src in sources]

        # library files
        for lib in self.ext_libs:
            cmd += ['-v', f'{lib}']

        # include directory search path
        for dir_ in self.inc_dirs:
            cmd += [f'+incdir+{dir_}']

        # define variables
        cmd += self.def_args(prefix='+define+')

        # misc flags
        cmd += ['-sverilog']
        cmd += ['-full64']
        cmd += ['+v2k']
        cmd += ['-LDFLAGS']
        cmd += ['-Wl,--no-as-needed']
        if self.dump_waveforms:
            cmd += ['+vcs+vcdpluson', '-debug_pp']

        # return arg list and binary file location
        return cmd, './simv'

    def iverilog_cmd(self, sources):
        cmd = []

        # binary name
        cmd += ['iverilog']

        # output file
        bin_file = f'{self.circuit_name}_tb'
        cmd += [f'-o{bin_file}']

        # look for *.v and *.sv files, if we're using library directories
        if len(self.ext_libs) > 0:
            cmd += ['-Y.v', '-Y.sv']

        # Icarus verilog does not have an option like "-v" that allows
        # individual files to be included, so the best we can do is gather a
        # list of unique library directories
        unq_lib_dirs = {}
        for lib in self.ext_libs:
            parent_dir = Path(lib).parent
            if parent_dir not in unq_lib_dirs:
                unq_lib_dirs[parent_dir] = None
        cmd += [f'-y{unq_lib_dir}' for unq_lib_dir in unq_lib_dirs]

        # include directory search path
        for dir_ in self.inc_dirs:
            cmd += [f'-I{dir_}']

        # define variables
        cmd += self.def_args(prefix='-D')

        # misc flags
        cmd += ['-g2012']

        # source files
        cmd += [f'{src}' for src in sources]

        # return arg list and binary file location
        return cmd, bin_file
