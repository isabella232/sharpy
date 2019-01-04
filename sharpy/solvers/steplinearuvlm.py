"""
Time domain solver to integrate the linear UVLM aerodynamic system developed by S. Maraniello
N Goizueta
Nov 18
"""
import os
import sys
from sharpy.utils.solver_interface import BaseSolver, solver
import numpy as np
import sharpy.utils.settings as settings
import sharpy.utils.generator_interface as gen_interface
import sharpy.linear.src.linuvlm as linuvlm  


@solver
class StepLinearUVLM(BaseSolver):
    r"""
    Warnings:
        Under development.

    Time domain aerodynamic solver that uses a linear UVLM formulation to be used with the :func:`DynamicCoupled`
    solver.

    To use this solver, the ``solver_id = StepLinearUVLM`` must be given as the aerodynamic settings value for the
    aeroelastic solver.

    To Do:
        - Add option for impulsive/non impulsive start start?

    Attributes:
        settings (dict): Contains the solver's ``settings``. See below for acceptable values:

            ============================  =========  ===============================================    ==========
            Name                          Type       Description                                        Default
            ============================  =========  ===============================================    ==========
            ``dt``                        ``float``  Time increment                                     ``0.1``
            ``integr_order``              ``int``    Finite difference order for bound circulation      ``2``
            ``ScalingDict``               ``dict``   Dictionary with scaling gains. See Notes.
            ``remove_predictor``          ``bool``   Remove predictor term from UVLM system assembly    ``True``
            ``use_sparse``                ``bool``   Use sparse form of A and B state space matrices    ``True``
            ``velocity_field_generator``  ``str``    Selected velocity generator                        ``None``
            ``velocity_filed_input``      ``dict``   Settings for the velocity generator                ``None``
            ============================  =========  ===============================================    ==========

        lin_uvlm_system (linuvlm.Dynamic): Linearised UVLM dynamic system
        velocity_generator (utils.generator_interface.BaseGenerator): velocity field generator class of desired type

    Notes:
        The ``integr_order`` variable refers to the finite differencing scheme used to calculate the bound circulation
        derivative with respect to time :math:`\dot{\mathbf{\Gamma}}`. A first order scheme is used when
        ``integr_order == 1``

        .. math:: \dot{\mathbf{\Gamma}}^{n+1} = \frac{\mathbf{\Gamma}^{n+1}-\mathbf{\Gamma}^n}{\Delta t}

        If ``integr_order == 2`` a higher order scheme is used (but it isn't exactly second order accurate [1]).

        .. math:: \dot{\mathbf{\Gamma}}^{n+1} = \frac{3\mathbf{\Gamma}^{n+1}-4\mathbf{\Gamma}^n + \mathbf{\Gamma}^{n-1}}
            {2\Delta t}

        The ``ScalingDict`` dictionary contains the gains by which to scale the
        linear system in ``length``, ``speed`` and ``density``.

    See Also:
        :func:`sharpy.linear.src.linuvlm`

    References:
        [1] S. Maraniello, R. Palacios. Linearisation and state-space realisation of UVLM with arbitrary kinematics

    """
    solver_id = 'StepLinearUVLM'

    def __init__(self):
        """
        Create default settings
        """

        self.settings_types = dict()
        self.settings_default = dict()

        self.settings_types['dt'] = 'float'
        self.settings_default['dt'] = 0.1

        self.settings_types['integr_order'] = 'int'
        self.settings_default['integr_order'] = 2

        self.settings_types['density'] = 'float'
        self.settings_default['density'] = 1.225

        self.settings_types['ScalingDict'] = 'dict'
        self.settings_default['ScalingDict'] = {'length': 1.0,
                                                'speed': 1.0,
                                                'density': 1.0}

        self.settings_types['remove_predictor'] = 'bool'
        self.settings_default['remove_predictor'] = True

        self.settings_types['use_sparse'] = 'bool'
        self.settings_default['use_sparse'] = True

        self.settings_types['physical_model'] = 'bool'
        self.settings_default['physical_model'] = True

        self.data = None
        self.settings = None
        self.lin_uvlm_system = None
        self.velocity_generator = None

    def initialise(self, data, custom_settings=None):
        r"""
        Initialises the Linear UVLM aerodynamic solver and the chosen velocity generator.

        Settings are parsed into the standard SHARPy settings format for solvers. It then checks whether there is
        any previous information about the linearised system (in order for a solution to be restarted without
        overwriting the linearisation).

        If a linearised system does not exist, a linear UVLM system is created linearising about the current time step.

        The reference values for the input and output are transformed into column vectors :math:`\mathbf{u}`
        and :math:`\mathbf{y}`, respectively.

        The information pertaining to the linear system is stored in a dictionary ``self.data.aero.linear`` within
        the main ``data`` variable.

        Args:
            data (PreSharpy): class containing the problem information
            custom_settings (dict): custom settings dictionary

        """

        self.data = data

        if custom_settings is None:
            self.settings = data.settings[self.solver_id]
        else:
            self.settings = custom_settings
        settings.to_custom_types(self.settings, self.settings_types, self.settings_default)

        # Check whether linear UVLM has been initialised
        try:
            self.data.aero.linear
        except AttributeError:
            self.data.aero.linear = dict()
            aero_tstep = self.data.aero.timestep_info[-1]

            # TODO: verify of a better way to implement rho
            self.data.aero.timestep_info[-1].rho = self.settings['density'].value

            # Generate instance of linuvlm.Dynamic()
            lin_uvlm_system = linuvlm.Dynamic(aero_tstep,
                                              dt=self.settings['dt'].value,
                                              integr_order=self.settings['integr_order'].value,
                                              ScalingDict=self.settings['ScalingDict'],
                                              RemovePredictor=self.settings['remove_predictor'],
                                              UseSparse=self.settings['use_sparse'].value)

            # Save reference values
            # System Inputs
            u_0 = self.pack_input_vector(aero_tstep)

            # Linearised state
            dt = self.settings['dt'].value
            x_0 = self.pack_state_vector(aero_tstep, None, dt, self.settings['integr_order'].value)

            # Reference forces
            f_0 = np.concatenate([aero_tstep.forces[ss][0:3].reshape(-1, order='C')
                                  for ss in range(aero_tstep.n_surf)])

            # Assemble the state space system
            lin_uvlm_system.assemble_ss()
            self.data.aero.linear['System'] = lin_uvlm_system
            self.data.aero.linear['SS'] = lin_uvlm_system.SS
            self.data.aero.linear['x_0'] = x_0
            self.data.aero.linear['u_0'] = u_0
            self.data.aero.linear['y_0'] = f_0
            self.data.aero.linear['gamma_0'] = gamma
            self.data.aero.linear['gamma_star_0'] = gamma_star
            self.data.aero.linear['gamma_dot_0'] = gamma_dot

            # TODO: Implement in AeroTimeStepInfo a way to store the state vectors
            # aero_tstep.linear.x = x_0
            # aero_tstep.linear.u = u_0
            # aero_tstep.linear.y = f_0

        # Initialise velocity generator
        velocity_generator_type = gen_interface.generator_from_string(self.settings['velocity_field_generator'])
        self.velocity_generator = velocity_generator_type()
        self.velocity_generator.initialise(self.settings['velocity_field_input'])


    def run(self,
            aero_tstep,
            structure_tstep,
            convect_wake=False,
            dt=None,
            t=None,
            unsteady_contribution=False):
        r"""
        Solve the linear aerodynamic UVLM model at the current time step ``n``. The step increment is solved as:

        .. math::
            \mathbf{x}^n &= \mathbf{A\,x}^{n-1} + \mathbf{B\,u}^n \\
            \mathbf{y}^n &= \mathbf{C\,x}^n + \mathbf{D\,u}^n

        A change of state is possible in order to solve the system without the predictor term. In which case the system
        is solved by:

        .. math::
            \mathbf{h}^n &= \mathbf{A\,h}^{n-1} + \mathbf{B\,u}^{n-1} \\
            \mathbf{y}^n &= \mathbf{C\,h}^n + \mathbf{D\,u}^n


        Variations are taken with respect to initial reference state. The state and input vectors for the linear
        UVLM system are of the form:

                If ``integr_order==1``:
                    .. math:: \mathbf{x}_n = [\delta\mathbf{\Gamma}^T_n,\,
                        \delta\mathbf{\Gamma_w}_n^T,\,
                        \Delta t \,\delta\mathbf{\dot{\Gamma}}_n^T]^T

                Else, if ``integr_order==2``:
                    .. math:: \mathbf{x}_n = [\delta\mathbf{\Gamma}_n^T,\,
                        \delta\mathbf{\Gamma_w}_n^T,\,
                        \Delta t \,\delta\mathbf{\dot{\Gamma}}_n^T,\,
                        \delta\mathbf{\Gamma}_{n-1}^T]^T

                And the input vector:
                    .. math:: \mathbf{u}_n = [\delta\mathbf{\zeta}_n^T,\,
                        \delta\dot{\mathbf{\zeta}}_n^T,\,\delta\mathbf{u_{ext}}^T_n]^T

        where the subscript ``n`` refers to the time step.

        The linear UVLM system is then solved as detailed in :func:`sharpy.linear.src.linuvlm.Dynamic.solve_step`.
        The output is a column vector containing the aerodynamic forces at the panel vertices.

        To Do:
            Option for impulsive start?

        Args:
            aero_tstep (AeroTimeStepInfo): object containing the aerodynamic data at the current time step
            structure_tstep (StructTimeStepInfo): object containing the structural data at the current time step
            convect_wake (bool): for backward compatibility only. The linear UVLM assumes a frozen wake geometry
            dt (float): time increment
            t (float): current time
            unsteady_contribution (bool): (backward compatibily). Unsteady aerodynamic effects are always included

        Returns:
            PreSharpy: updated ``self.data`` class with the new forces and circulation terms of the system

        """

        if aero_tstep is None:
            aero_tstep = self.data.aero.timestep_info[-1]
        if structure_tstep is None:
            structure_tstep = self.data.structure.timestep_info[-1]
        if dt is None:
            dt = self.settings['dt'].value
        if t is None:
            t = self.data.ts*dt

        integr_order = self.settings['integr_order'].value

        ### Define Input

        # Generate external velocity field u_ext
        self.velocity_generator.generate({'zeta': aero_tstep.zeta,
                                          'override': True,
                                          't': t,
                                          'ts': self.data.ts,
                                          'dt': dt,
                                          'for_pos': structure_tstep.for_pos},
                                         aero_tstep.u_ext)


        # Column vector that will be the input to the linearised UVLM system
        # Input is at time step n, since it is updated in the aeroelastic solver prior to aerodynamic solver
        u_n = self.pack_input_vector(aero_tstep)
        du_n = u_n - self.data.aero.linear['u_0']

        if self.settings['remove_predictor']:
            u_m1 = self.pack_input_vector(self.data.aero.timestep_info[-1])
            du_m1 = u_m1 - self.data.aero.linear['u_0']
        else:
            du_m1 = None

        # Retrieve State vector at time n-1
        if len(self.data.aero.timestep_info) < 2:
            x_m1 = self.pack_state_vector(aero_tstep, None, dt, integr_order)
        else:
            x_m1 = self.pack_state_vector(aero_tstep, self.data.aero.timestep_info[-2], dt, integr_order)

        # dx is at timestep n-1
        dx_m1 = x_m1 - self.data.aero.linear['x_0']

        ### Solve system - output is the variation in force
        dx_n, dy_n = self.data.aero.linear['System'].solve_step(dx_m1, du_m1, du_n, transform_state=True)

        x_n = self.data.aero.linear['x_0'] + dx_n
        y_n = self.data.aero.linear['y_0'] + dy_n

        # if self.settings['physical_model']:
        forces, gamma, gamma_dot, gamma_star = self.unpack_ss_vectors(y_n, x_n, u_n, aero_tstep)
        aero_tstep.forces = forces
        aero_tstep.gamma = gamma
        aero_tstep.gamma_dot = gamma_dot
        aero_tstep.gamma_star = gamma_star

        return self.data

    def add_step(self):
        self.data.aero.add_timestep()

    def update_grid(self, beam):
        self.data.aero.generate_zeta(beam, self.data.aero.aero_settings, -1, beam_ts=-1)

    def update_custom_grid(self, structure_tstep, aero_tstep):
        self.data.aero.generate_zeta_timestep_info(structure_tstep, aero_tstep, self.data.structure, self.data.aero.aero_settings)

    def unpack_ss_vectors(self, y_n, x_n, u_n, aero_tstep):
        r"""
        Transform column vectors used in the state space formulation into SHARPy format

        The column vectors are transformed into lists with one entry per aerodynamic surface. Each entry contains a
        matrix with the quantities at each grid vertex.

        .. math::
            \mathbf{y}_n \longrightarrow \mathbf{f}_{aero}

        .. math:: \mathbf{x}_n \longrightarrow \mathbf{\Gamma}_n,\,
            \mathbf{\Gamma_w}_n,\,
            \mathbf{\dot{\Gamma}}_n

        Args:
            y_n (np.ndarray): Column output vector of linear UVLM system
            x_n (np.ndarray): Column state vector of linear UVLM system
            u_n (np.ndarray): Column input vector of linear UVLM system
            aero_tstep (AeroTimeStepInfo): aerodynamic timestep information class instance

        Returns:
            tuple: Tuple containing:

                forces (list):
                    Aerodynamic forces in a list with ``n_surf`` entries.
                    Each entry is a ``(6, M+1, N+1)`` matrix, where the first 3
                    indices correspond to the components in ``x``, ``y`` and ``z``. The latter 3 are zero.

                gamma (list):
                    Bound circulation list with ``n_surf`` entries. Circulation is stored in an ``(M+1, N+1)``
                    matrix, corresponding to the panel vertices.

                gamma_dot (list):
                    Bound circulation derivative list with ``n_surf`` entries.
                    Circulation derivative is stored in an ``(M+1, N+1)`` matrix, corresponding to the panel
                    vertices.

                gamma_star (list):
                    Wake (free) circulation list with ``n_surf`` entries. Wake circulation is stored in an
                    ``(M_star+1, N+1)`` matrix, corresponding to the panel vertices of the wake.

        """

        f_aero = y_n
        
        gamma_vec, gamma_star_vec, gamma_dot_vec = self.data.aero.linear['System'].unpack_state(x_n, u_n)
        # gamma_vec = self.data.aero.linear['gamma_0'] + dgamma_vec
        # gamma_star_vec = self.data.aero.linear['gamma_star_0'] + dgamma_star_vec
        # gamma_dot_vec = self.data.aero.linear['gamma_dot_0'] + dgamma_dot_vec

        # Reshape output into forces[i_surface] where forces[i_surface] is a (6,M+1,N+1) matrix and circulation terms
        # where gamma is a [i_surf](M+1, N+1) matrix
        forces = []
        gamma = []
        gamma_star = []
        gamma_dot = []

        worked_points = 0
        worked_panels = 0
        worked_wake_panels = 0

        for i_surf in range(aero_tstep.n_surf):
            # Tuple with dimensions of the aerogrid zeta, which is the same shape for forces
            dimensions = aero_tstep.zeta[i_surf].shape
            dimensions_gamma = self.data.aero.aero_dimensions[i_surf]
            dimensions_wake = self.data.aero.aero_dimensions_star[i_surf]

            # Number of entries in zeta
            points_in_surface = aero_tstep.zeta[i_surf].size
            panels_in_surface = aero_tstep.gamma[i_surf].size
            panels_in_wake = aero_tstep.gamma_star[i_surf].size

            # Append reshaped forces to each entry in list (one for each surface)
            forces.append(f_aero[worked_points:worked_points+points_in_surface].reshape(dimensions, order='C'))

            # Add the null bottom 3 rows to to the forces entry
            forces[i_surf] = np.concatenate((forces[i_surf], np.zeros(dimensions)))

            # Reshape bound circulation terms
            gamma.append(gamma_vec[worked_panels:worked_panels+panels_in_surface].reshape(
                dimensions_gamma, order='C'))
            gamma_dot.append(gamma_dot_vec[worked_panels:worked_panels+panels_in_surface].reshape(
                dimensions_gamma, order='C'))

            # Reshape wake circulation terms
            gamma_star.append(gamma_star_vec[worked_wake_panels:worked_wake_panels+panels_in_wake].reshape(
                dimensions_wake, order='C'))

            worked_points += points_in_surface
            worked_panels += panels_in_surface
            worked_wake_panels += panels_in_wake

        return forces, gamma, gamma_dot, gamma_star

    @staticmethod
    def pack_input_vector(aero_tstep):
        r"""
        Transform a SHARPy AeroTimestep instance into a column vector containing the input to the linear UVLM system.

        .. math:: [\zeta,\, \dot{\zeta}, u_{ext}] \longrightarrow \\mathbf{u}
        
        Returns:
            np.ndarray: Input vector

        """
        
        zeta = np.concatenate([aero_tstep.zeta[i_surf].reshape(-1, order='C')
                               for i_surf in range(aero_tstep.n_surf)])
        zeta_dot = np.concatenate([aero_tstep.zeta_dot[i_surf].reshape(-1, order='C')
                                   for i_surf in range(aero_tstep.n_surf)])
        u_ext = np.concatenate([aero_tstep.u_ext[i_surf].reshape(-1, order='C')
                               for i_surf in range(aero_tstep.n_surf)])

        u = np.concatenate((zeta, zeta_dot, u_ext)) 

        return u

    @staticmethod
    def pack_state_vector(aero_tstep, aero_tstep_m1, dt, integr_order):
        r"""
        Transform SHARPy Aerotimestep format into column vector containing the state information.

        The state vector is of a different form depending on the order of integration chosen. If a second order
        scheme is chosen, the state includes the bound circulation at the previous timestep,
        hence the timestep information for the previous timestep shall be parsed.

        The transformation is of the form:

        - If ``integr_order==1``:

                .. math:: \mathbf{x}_n = [\mathbf{\Gamma}^T_n,\,
                    \mathbf{\Gamma_w}_n^T,\,
                    \Delta t \,\mathbf{\dot{\Gamma}}_n^T]^T

        - Else, if ``integr_order==2``:

                .. math:: \mathbf{x}_n = [\mathbf{\Gamma}_n^T,\,
                    \mathbf{\Gamma_w}_n^T,\,
                    \Delta t \,\mathbf{\dot{\Gamma}}_n^T,\,
                    \mathbf{\Gamma}_{n-1}^T]^T

        For the second order integration scheme, if the previous timestep information is not parsed, a first order
        stencil is employed to estimate the bound circulation at the previous timestep:

            .. math:: \mathbf{\Gamma}^{n-1} = \mathbf{\Gamma}^n - \Delta t \mathbf{\dot{\Gamma}}^n

        Args:
            aero_tstep (AeroTimeStepInfo): Aerodynamic timestep information at the current timestep ``n``.
            aero_tstep_m1 (AeroTimeStepInfo) Aerodynamic timestep information at the previous timestep ``n-1``.

        Returns:
            np.ndarray: State vector

        """

        # Extract current state...
        gamma = np.concatenate([aero_tstep.gamma[ss].reshape(-1, order='C')
                                for ss in range(aero_tstep.n_surf)])
        gamma_star = np.concatenate([aero_tstep.gamma_star[ss].reshape(-1, order='C')
                                    for ss in range(aero_tstep.n_surf)])
        gamma_dot = np.concatenate([aero_tstep.gamma_dot[ss].reshape(-1, order='C')
                                    for ss in range(aero_tstep.n_surf)])

        if integr_order == 1:
            gamma_m1 = []

        else:
            if aero_tstep_m1:
                gamma_m1 = np.concatenate([aero_tstep_m1.gamma[ss].reshape(-1, order='C')
                                    for ss in range(aero_tstep.n_surf)])
            else:
                gamma_m1 = gamma - dt * gamma_dot

        x = np.concatenate((gamma, gamma_star, dt * gamma_dot, gamma_m1))

        return x