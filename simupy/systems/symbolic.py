import numpy as np
import sympy as sp
from sympy.physics.mechanics import dynamicsymbols
from sympy.physics.mechanics.functions import find_dynamicsymbols
from sympy.tensor.array import Array
from simupy.utils.symbolic import lambdify_with_vector_args, grad
from simupy.array import empty_array

from simupy.systems import DynamicalSystem as DynamicalSystemBase

DEFAULT_CODE_GENERATOR = lambdify_with_vector_args
DEFAULT_CODE_GENERATOR_ARGS = {
    'modules': "numpy"
}


class DynamicalSystem(DynamicalSystemBase):
    def __init__(self, state_equation=None, state=None, input_=None,
                 output_equation=None, constants_values={}, dt=0,
                 initial_condition=None, code_generator=None,
                 code_generator_args={}):
        """
        DynamicalSystem constructor, used to create systems from symbolic
        expressions.

        Parameters
        ----------
        state_equation : Array or Matrix (1D) of sympy Expressions (optional)
            Vector valued expression for the derivative of the state.
        state : Array or Matrix (1D) of sympy symbols (optional)
            Vector of symbols representing the components of the state, in the
            desired order, matching state_equation.
        input_ : Array or Matrix (1D) of sympy symbols (optional)
            Vector of symbols representing the components of the input, in the
            desired order. state_equation may depend on the system input. If
            the system has no state, the output_equation may depend on the
            system input.
        output_equation : Array or Matrix (1D) of sympy Expressions
            Vector valued expression for the output of the system.
        constants_values : dict
            Dictionary of constants substitutions.
        dt : float
            Sampling rate of system. Use 0 for continuous time systems.
        initial_condition : Array or Matrix (1D) of numerical values
            Array or Matrix used as the initial condition of the sytsem.
        code_generator : callable (optional)
            Function to be used as code generator.
        code_generator_args : dict (optional)
            Dictionary of keyword args to pass to the code generator.


        By default, the code generator uses a wrapper for ``sympy.lambdify``.
        You can change it by passing the system initialization arguments
        ``code_generator`` (the function) and additional key-word arguments to
        the generator in a dictionary ``code_generator_args``. You can change
        the defaults for future systems by changing the module values. See the
        readme or docs for an example.

        """
        self.constants_values = constants_values
        self.state = state
        self.initial_condition = initial_condition
        self.input = input_

        self.code_generator = code_generator or DEFAULT_CODE_GENERATOR

        code_gen_args_to_set = DEFAULT_CODE_GENERATOR_ARGS.copy()
        code_gen_args_to_set.update(code_generator_args)
        self.code_generator_args = code_gen_args_to_set

        self.state_equation = state_equation
        self.output_equation = output_equation

        self.dt = dt

        self.n_events = 0

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, state):
        if state is None:  # or other checks?
            state = empty_array()
        if isinstance(state, sp.Expr):
            state = Array([state])
        self.dim_state = len(state)
        self._state = state

    @property
    def input(self):
        return self._inputs

    @input.setter
    def input(self, input_):
        if input_ is None:  # or other checks?
            input_ = empty_array()
        if isinstance(input_, sp.Expr):  # check it's a single dynamicsymbol?
            input_ = Array([input_])
        self.dim_input = len(input_)
        self._inputs = input_

    @property
    def state_equation(self):
        return self._state_equation

    @state_equation.setter
    def state_equation(self, state_equation):
        if state_equation is None:  # or other checks?
            state_equation = empty_array()
        else:
            assert len(state_equation) == len(self.state)
            assert find_dynamicsymbols(state_equation) <= (
                    set(self.state) | set(self.input)
                )
            assert state_equation.atoms(sp.Symbol) <= (
                    set(self.constants_values.keys())
                    | set([dynamicsymbols._t])
                )

        self._state_equation = state_equation
        self.update_state_equation_function()

        self.state_jacobian_equation = grad(self.state_equation, self.state)
        self.update_state_jacobian_function()

        self.input_jacobian_equation = grad(self.state_equation, self.input)
        self.update_input_jacobian_function()

    @property
    def output_equation(self):
        return self._output_equation

    @output_equation.setter
    def output_equation(self, output_equation):
        if output_equation is None:  # or other checks?
            output_equation = self.state
        try:
            self.dim_output = len(output_equation)
        except TypeError:
            self.dim_output = 1
        assert output_equation.atoms(sp.Symbol) <= (
                set(self.constants_values.keys()) | set([dynamicsymbols._t])
               )
        if self.dim_state:
            assert find_dynamicsymbols(output_equation) <= set(self.state)
        else:
            assert find_dynamicsymbols(output_equation) <= set(self.input)
        self._output_equation = output_equation
        self.update_output_equation_function()

    def update_state_equation_function(self):
        if not self.dim_state:
            return
        self.state_equation_function = self.code_generator(
            [dynamicsymbols._t] + sp.flatten(self.state) +
            sp.flatten(self.input),
            self.state_equation.subs(self.constants_values),
            **self.code_generator_args
        )

    def update_state_jacobian_function(self):
        if not self.dim_state:
            return
        self.state_jacobian_equation_function = self.code_generator(
            [dynamicsymbols._t] + sp.flatten(self.state) +
            sp.flatten(self.input),
            self.state_jacobian_equation.subs(self.constants_values),
            **self.code_generator_args
        )

    def update_input_jacobian_function(self):
        # TODO: state-less systems should have an input/output jacobian
        if not self.dim_state:
            return
        self.input_jacobian_equation_function = self.code_generator(
            [dynamicsymbols._t] + sp.flatten(self.state) +
            sp.flatten(self.input),
            self.input_jacobian_equation.subs(self.constants_values),
            **self.code_generator_args
        )

    def update_output_equation_function(self):
        if not self.dim_output:
            return
        if self.dim_state:
            self.output_equation_function = self.code_generator(
                [dynamicsymbols._t] + sp.flatten(self.state),
                self.output_equation.subs(self.constants_values),
                **self.code_generator_args
            )
        else:
            self.output_equation_function = self.code_generator(
                [dynamicsymbols._t] + sp.flatten(self.input),
                self.output_equation.subs(self.constants_values),
                **self.code_generator_args
            )

    @property
    def initial_condition(self):
        return self._initial_condition

    @initial_condition.setter
    def initial_condition(self, initial_condition):
        if initial_condition is not None:
            assert len(initial_condition) == self.dim_state
            self._initial_condition = initial_condition
        else:
            self._initial_condition = np.zeros(self.dim_state)

    def prepare_to_integrate(self):
        pass

    def copy(self):
        copy = self.__class__(
            state_equation=self.state_equation,
            state=self.state,
            input_=self.input,
            output_equation=self.output_equation,
            constants_values=self.constants_values,
            dt=self.dt
        )
        copy.output_equation_function = self.output_equation_function
        copy.state_equation_function = self.state_equation_function
        return copy

    def equilibrium_points(self, input_=None):
        return sp.solve(self.state_equation, self.state, dict=True)


class MemorylessSystem(DynamicalSystem):
    """
    A system with no state.

    With no input, can represent a signal (function of time only). For example,
    a stochastic signal could interpolate points and use prepare_to_integrate
    to re-seed the data.
    """
    def __init__(self, input_=None, output_equation=None, **kwargs):
        """
        DynamicalSystem constructor

        Parameters
        ----------
        input_ : Array or Matrix (1D) of sympy symbols
            Vector of symbols representing the components of the input, in the
            desired order. The output_equation may depend on the system input.
        output_equation : Array or Matrix (1D) of sympy Expressions
            Vector valued expression for the output of the system.
        """
        super().__init__(
              input_=input_, output_equation=output_equation, **kwargs)

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, state):
        if state is None:  # or other checks?
            state = empty_array()
        else:
            raise ValueError("Memoryless system should not have state or " +
                             "state_equation")
        self.dim_state = len(state)
        self._state = state
