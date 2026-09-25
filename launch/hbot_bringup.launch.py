from sys import executable
import os
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, GroupAction,
                            IncludeLaunchDescription, SetEnvironmentVariable)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node, SetRemap
from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch.conditions import IfCondition, UnlessCondition
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml

def generate_launch_description():
  package_name = 'hbot_bringup'
  nav2_launch_dir = os.path.join(get_package_share_directory('nav2_bringup'), 'launch')
  slam_toolbox_dir = get_package_share_directory('slam_toolbox')
  slam_launch_file = os.path.join(slam_toolbox_dir, 'launch', 'online_async_launch.py')
  controller_name = os.environ.get('CONTROLLER', 'yahboom')

  if controller_name not in ['yahboom']:
    raise RuntimeError('Unknown controller: ' + controller_name)

  # LIDAR selection: 'lds01' (default) is the Turtlebot3-compatible LDS-01
  # unit currently on the robot (driven by the apt-installed
  # hls_lfcd_lds_driver package); 'ydlidar_x3' is the newly added YDLidar
  # X3 Pro (driven by the ydlidar_ros2_driver package under src/lidars/,
  # which needs the YDLidar SDK under src/YDLidar-SDK-master built and
  # `sudo make install`-ed system-wide before it will colcon build).
  lidar_model = os.environ.get('LIDAR_MODEL', 'lds01')

  if lidar_model not in ['lds01', 'ydlidar_x3']:
    raise RuntimeError('Unknown lidar model: ' + lidar_model)

  # Launch arguments
  simulation_mode = LaunchConfiguration('simulation_mode')
  run_rviz = LaunchConfiguration('run_rviz')
  slam = LaunchConfiguration('slam')
  enable_navigation = LaunchConfiguration('enable_navigation')
  map_yaml_file = LaunchConfiguration('map')
  use_sim_time = LaunchConfiguration('use_sim_time')
  params_file = LaunchConfiguration('params_file')
  slam_params_file = LaunchConfiguration('slam_params_file')
  namespace = LaunchConfiguration('namespace')
  autostart = LaunchConfiguration('autostart')
  use_respawn = LaunchConfiguration('use_respawn')
  log_level = LaunchConfiguration('log_level')

  remappings = [('/tf', 'tf'),
                ('/tf_static', 'tf_static')]

  lifecycle_nodes = ['map_saver']

  param_substitutions = {
    'use_sim_time': use_sim_time,
    'yaml_filename': map_yaml_file
  }

  configured_params = ParameterFile(
    RewrittenYaml(
      source_file=params_file,
      param_rewrites=param_substitutions,
      convert_types=True),
    allow_substs=True)

  stdout_linebuf_envvar = SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1')

  declare_simulation_mode_cmd = DeclareLaunchArgument(
    'simulation_mode',
    default_value='False',
    description='When run as simulation mode'
  )

  declare_headless_cmd = DeclareLaunchArgument(
    'headless',
    default_value='False',
    description='In simulation mode, run gzserver only (no gzclient GUI)'
  )

  declare_run_rviz_cmd = DeclareLaunchArgument(
    'run_rviz',
    default_value='False',
    description='Run rviz'
  )

  declare_namespace_cmd = DeclareLaunchArgument(
    'namespace',
    default_value='',
    description='Top-level namespace'
  )

  declare_slam_cmd = DeclareLaunchArgument(
    'slam',
    default_value='True',
    description='Whether to run SLAM instead of map-based localization'
  )

  declare_enable_navigation_cmd = DeclareLaunchArgument(
    'enable_navigation',
    default_value='False',
    description='Whether to launch the Nav2 navigation stack'
  )

  declare_map_yaml_cmd = DeclareLaunchArgument(
    'map',
    default_value=os.path.join(get_package_share_directory('hbot_bringup'),
                               'maps', 'hbot_house_sim.yaml'),
    description='Full path to the map YAML for slam:=False localization mode. '
                'Defaults to the bundled hbot_house_sim map (built from the '
                'Gazebo world); pass map:=/abs/path/your_map.yaml on real '
                'hardware.'
  )

  declare_use_sim_time_cmd = DeclareLaunchArgument(
    'use_sim_time',
    default_value='False',
    description='Use simulation (Gazebo) clock if true'
  )

  declare_params_file_cmd = DeclareLaunchArgument(
    'params_file',
    default_value=os.path.join(get_package_share_directory('hbot_bringup'),'config', 'nav2_params.yaml'),
    description='Full path to the ROS2 parameters file to use for all launched nodes'
  )

  declare_slam_params_file_cmd = DeclareLaunchArgument(
    'slam_params_file',
    default_value=os.path.join(get_package_share_directory('hbot_bringup'),'config', 'slam_params.yaml'),
    description='Full path to the ROS2 parameters file to use for all launched nodes'
  )

  declare_autostart_cmd = DeclareLaunchArgument(
    'autostart',
    default_value='True',
    description='Automatically startup the nav2 stack'
  )

  declare_log_level_cmd = DeclareLaunchArgument(
    'log_level',
    default_value='info',
    description='log_level'
  )

  declare_use_respawn_cmd = DeclareLaunchArgument(
    'use_respawn',
    default_value='False',
    description='Whether to respawn if a node crashes. Applied when composition is disabled.'
  )

  # Real-robot description: TF frames only (base_footprint, base_link, laser,
  # imu_link), generated from hbot_description's hbot.urdf.xacro - the same
  # source as the Gazebo model (hbot_sim.urdf), so the laser pose can't drift.
  urdf_path = os.path.join(
    get_package_share_directory('hbot_description'),
    'urdf', 'hbot.urdf')
  with open(urdf_path, 'r') as infp:
    robot_description = infp.read()

  # Lidar node, picked by the LIDAR_MODEL env var (see declaration above).
  # It only ever runs on real hardware - it lives inside `hardware_nodes`,
  # which is gated UnlessCondition(simulation_mode). The whole block is wrapped
  # in try/except so a simulation-only host that never installed the physical
  # lidar driver package can still bring the stack up (Gazebo publishes /scan
  # itself in sim); get_package_share_directory() would otherwise raise here,
  # while the launch description is still being built, and abort everything.
  lidar_node = None
  try:
    if lidar_model == 'ydlidar_x3':
      # --- YDLidar X3 Pro
      # x3_ydlidar_launch.py declares its own 'params_file' launch argument
      # (defaulting to its own ydlidar_x3.yaml), but LaunchConfiguration names
      # aren't per-include-scoped - they're shared across the whole launch
      # tree unless reset by a scoped GroupAction (hardware_nodes below is
      # one, so this override doesn't leak into the Nav2 groups that need
      # their own 'params_file'). hbot_bringup.launch.py already declares a
      # top-level 'params_file' argument for Nav2 (default nav2_params.yaml)
      # earlier in this function, so by the time this include's own
      # DeclareLaunchArgument runs, 'params_file' is already set -
      # DeclareLaunchArgument never overwrites an existing value, so the
      # ydlidar node would silently receive nav2_params.yaml (no
      # ydlidar_ros2_driver_node: block in it) and fall back to the driver's
      # hardcoded C++ default port ('/dev/ydlidar'), ignoring ydlidar_x3.yaml
      # entirely. Passing params_file explicitly here forces the correct
      # value before x3_ydlidar_launch.py's own declare runs.
      lidar_node = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
          get_package_share_directory('ydlidar_ros2_driver'),
          'launch',
          'x3_ydlidar_launch.py'
        )),
        launch_arguments={
          'params_file': os.path.join(
            get_package_share_directory('ydlidar_ros2_driver'),
            'params', 'ydlidar_x3.yaml')
        }.items(),
      )
    else:
      # --- Lidar LDS01 from turtlebot 3 (default)
      # --- Lidar LDS-006 (bought from shopee) would be:
      #   get_package_share_directory('lds_006_driver'), 'launch', 'lds_006_driver.launch.py'
      lidar_node = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
          get_package_share_directory('hls_lfcd_lds_driver'),
            'launch',
            'hlds_laser.launch.py'
            )),
          launch_arguments={'port': '/dev/usbttl'}.items(),
      )
  except PackageNotFoundError:
    # Real-hardware lidar driver package not installed - fine on a sim-only
    # host, since hardware_nodes never activates when simulation_mode:=True.
    lidar_node = None

  # Nodes
  hardware_actions = []
  if lidar_node is not None:
    hardware_actions.append(lidar_node)
  hardware_actions.append(
    # Robot description
    Node(
      package='robot_state_publisher',
      executable='robot_state_publisher',
      name='robot_state_publisher',
      parameters=[{'use_sim_time': use_sim_time,
          'robot_description': robot_description}]
    )
  )
  hardware_nodes = GroupAction(
    condition=UnlessCondition(simulation_mode),
    actions=hardware_actions
  )


  # Simulation
  try:
    simulation_dir = get_package_share_directory('hbot_simulation')
    has_simulation = True
  except PackageNotFoundError:
    has_simulation = False

  if has_simulation:
    simulation_nodes = GroupAction(
      condition=IfCondition(simulation_mode),
      actions = [
        IncludeLaunchDescription(
          PythonLaunchDescriptionSource(os.path.join(
            simulation_dir,
            'launch',
            'hbot_house.launch.py')),
          launch_arguments={'use_sim_time': use_sim_time,
                            'headless': LaunchConfiguration('headless')}.items()
        )
      ]
    )
  else:
    simulation_nodes = None

  # Run SLAM
  # slam_cmd_group = GroupAction([
  #   IncludeLaunchDescription(
  #       PythonLaunchDescriptionSource(slam_launch_file),
  #       launch_arguments={'use_sim_time': use_sim_time,
  #                         'slam_params_file': slam_params_file}.items()),
  # ], condition=IfCondition(slam))

  # --- Cartographer
  config_dir = os.path.join(get_package_share_directory('hbot_bringup'), 'config')
  slam_cmd_group = GroupAction([
    Node(
      package = 'cartographer_ros',
      executable = 'cartographer_node',
      output='screen',
      parameters=[{'use_sim_time': use_sim_time}],
      arguments=['-configuration_directory', config_dir,
                 '-configuration_basename', 'carto_mapping.lua']
    ),
    Node(
      package='cartographer_ros',
      executable='cartographer_occupancy_grid_node',
      name='cartographer_occupancy_grid_node',
      output='screen',
      parameters=[{'use_sim_time': use_sim_time}],
      arguments=['-resolution','0.05','-publish_period_sec','1.0']
    )
  ], condition=IfCondition(slam))


  localization_cmd_group = GroupAction([
    IncludeLaunchDescription(
      PythonLaunchDescriptionSource(os.path.join(nav2_launch_dir, 'localization_launch.py')),
      launch_arguments={'namespace': namespace,
                        'map': map_yaml_file,
                        'use_sim_time': use_sim_time,
                        'autostart': autostart,
                        'params_file': params_file,
                        'use_composition': 'False',
                        'use_respawn': use_respawn,
                        'container_name': 'nav2_container'}.items()),
  ], condition=UnlessCondition(slam))


  # Run mapping, localization and navigation
  nav_launch_args = list({'namespace': namespace,
                          'use_sim_time': use_sim_time,
                          'autostart': autostart,
                          'params_file': params_file,
                          'use_composition': 'False',
                          'use_respawn': use_respawn,
                          'container_name': 'nav2_container'}.items())
  nav_launch_source = PythonLaunchDescriptionSource(os.path.join(
      get_package_share_directory('nav2_bringup'),
      'launch', 'navigation_launch.py'))

  # On real hardware, SetRemap renames velocity_smoother's output inside the
  # vendored navigation_launch.py (from the navigation2 submodule) from
  # 'cmd_vel' to 'cmd_vel_nav_smoothed', without editing that submodule
  # directly - it overrides the node's own hardcoded ('cmd_vel_smoothed',
  # 'cmd_vel') remap from outside since it's applied within the same
  # GroupAction/launch context as the include. base_bringup.launch.py's
  # twist_mux node then arbitrates this against the teleop smoother's output
  # to produce the single, final 'cmd_vel' the driver consumes.
  #
  # In simulation there is no base_bringup / twist_mux (and no teleop source
  # to arbitrate against), so Nav2's smoothed output must land straight on
  # 'cmd_vel', which is what the Gazebo diff-drive plugin subscribes to -
  # hence the sim branch omits the SetRemap.
  bringup_cmd_group_real = GroupAction([
    SetRemap(src='cmd_vel_smoothed', dst='cmd_vel_nav_smoothed'),
    IncludeLaunchDescription(nav_launch_source, launch_arguments=nav_launch_args),
  ], condition=IfCondition(PythonExpression([
    "'", enable_navigation, "'.lower() in ['true', '1'] and '",
    simulation_mode, "'.lower() not in ['true', '1']"])))

  bringup_cmd_group_sim = GroupAction([
    IncludeLaunchDescription(nav_launch_source, launch_arguments=nav_launch_args),
  ], condition=IfCondition(PythonExpression([
    "'", enable_navigation, "'.lower() in ['true', '1'] and '",
    simulation_mode, "'.lower() in ['true', '1']"])))

  # run rviz
  rviz_cmd = Node(
    condition=IfCondition(run_rviz),
    package='rviz2',
    executable='rviz2',
    name='rviz2',
    arguments=['-d', os.path.join(get_package_share_directory(package_name),
                                  'config', 'hbot.rviz')],
    parameters=[{'use_sim_time': use_sim_time}],
    output='screen'
  )


  ld = LaunchDescription()

  # Set environment variables
  ld.add_action(stdout_linebuf_envvar)

  # Declare launch options
  ld.add_action(declare_simulation_mode_cmd)
  ld.add_action(declare_headless_cmd)
  ld.add_action(declare_run_rviz_cmd)
  ld.add_action(declare_namespace_cmd)
  ld.add_action(declare_slam_cmd)
  ld.add_action(declare_enable_navigation_cmd)
  ld.add_action(declare_map_yaml_cmd)
  ld.add_action(declare_use_sim_time_cmd)
  ld.add_action(declare_params_file_cmd)
  ld.add_action(declare_slam_params_file_cmd)
  ld.add_action(declare_autostart_cmd)
  ld.add_action(declare_use_respawn_cmd)
  ld.add_action(declare_log_level_cmd)

  # Add the actions to launch all nodes
  ld.add_action(hardware_nodes)
  if simulation_nodes is not None:
    ld.add_action(simulation_nodes)
  ld.add_action(slam_cmd_group)
  ld.add_action(localization_cmd_group)
  ld.add_action(bringup_cmd_group_real)
  ld.add_action(bringup_cmd_group_sim)
  ld.add_action(rviz_cmd)

  return ld