# How hbot_bringup gets the robot description

`hbot_bringup` no longer carries or reads a URDF of its own. The robot model
lives in `hbot_description` (one xacro + `config/hbot_geometry.yaml`, see
[`hbot_description/docs/robot_description.md`](../../hbot_description/docs/robot_description.md));
bringup includes its launch file, and the driver parameters are kept in sync
with its geometry.

Branch: `feat/standard-description` in `hbot_bringup` (and in `hbot_description`).

---

## Step 1: Real robot, `robot_state_publisher` via `description.launch.py`

Before, `launch/hbot_bringup.launch.py` opened
`hbot_description/urdf/hbot.urdf` and started its own
`robot_state_publisher` with the file's text. Now the real-robot group
(`hardware_nodes`, active when `simulation_mode:=False`) includes
`hbot_description`'s launch file, which expands the xacro at launch:

```python
robot_description_launch = IncludeLaunchDescription(
  PythonLaunchDescriptionSource(os.path.join(
    get_package_share_directory('hbot_description'),
    'launch', 'description.launch.py')),
  launch_arguments={'use_sim': 'false',
                    'use_sim_time': use_sim_time}.items(),
)
...
hardware_actions.append(robot_description_launch)
```

Why:

- The xacro, not a generated copy, is the source: the Pi publishes exactly what
  `config/hbot_geometry.yaml` says after a plain rebuild of `hbot_description`.
- Arguments of the description (e.g. `driver_joint_states:=true` once the
  driver publishes `/joint_states`) are passed through here in one place.
- The real robot now publishes the **full model** (chassis, wheels, caster,
  lidar), so RViz shows the robot, not just frames. The wheels are fixed
  joints, so no `/joint_states` is needed.

Simulation is unchanged: with `simulation_mode:=True`, `hbot_simulation`'s
`hbot_house.launch.py` starts `robot_state_publisher` with the Gazebo model
(`use_sim:=true` variant) and spawns the robot from it.

Run-time requirement on the Pi: `ros-humble-xacro`. It is an `exec_depend` of
`hbot_description`, so `rosdep install --from-paths src` (docs/dev_guide.md)
installs it; check with `ros2 pkg prefix xacro`.

## Step 2: Driver wheels = the model's wheels

`config/yahboom_driver_params.yaml`:

```yaml
wheel_track: 0.19      # measured; must match hbot_description config/hbot_geometry.yaml wheels.track
```

`hbot_driver_yahboom_node.cpp` uses `wheel_track` twice: to split `/cmd_vel`
into wheel speeds (`v ± ω·track/2`) and to integrate odometry
(`Δθ = (Δs_r − Δs_l) / track`). With the old 0.2 on a 0.190 m robot, every turn
was under-reported by ~5 % and the robot turned ~5 % more than commanded.

The wheel diameter follows the same rule. `hbot_geometry.yaml` now has the
measured `wheels.radius: 0.03375`, so the driver has

```yaml
wheel_diameter: 0.0675  # measured; = 2 x hbot_description config/hbot_geometry.yaml wheels.radius
```

(was the nominal 0.065; the CAD tyre is 0.0674). The driver uses it both to
turn `/cmd_vel` into wheel rpm and to turn encoder ticks into distance, so
with 0.065 the robot drove ~3.8 % faster than commanded and odometry
under-reported distance by ~3.7 %.

`test_driver_wheels_match` in `hbot_description` checks both values: it fails
whenever `wheel_track` or `wheel_diameter` drifts from the geometry YAML.

## Step 3: Validate

```bash
cd ~/Documents/03.MyProjects/hbot_ws
./build_packages.sh hbot_description hbot_bringup
source install/setup.bash
colcon test --packages-select hbot_description --event-handlers console_direct+   # 9 passed

# real-robot launch path on a private domain (no hardware needed for the TF check)
ROS_DOMAIN_ID=42 ros2 launch hbot_bringup hbot_bringup.launch.py \
  simulation_mode:=False use_sim_time:=False slam:=True enable_navigation:=False run_rviz:=False
ROS_DOMAIN_ID=42 ros2 run tf2_ros tf2_echo base_footprint laser             # 0.043 0 0.137
ROS_DOMAIN_ID=42 ros2 run tf2_ros tf2_echo base_footprint right_wheel_link  # 0 -0.095 0.034
```

Results on 2026-09-26 (laptop, isolated build of both branches):
`robot_state_publisher` started from `description.launch.py` with segments
`base_link, imu_link, left_wheel_link, right_wheel_link, …`; TF as above;
Cartographer started. `nav2_bringup` isn't installed on that laptop, so it was
stubbed for this run (Nav2 disabled); the lidar driver wasn't connected.

Still to do on the robot: deploy (`deploy-to-pi`), check that `/scan` lines up
with the map in RViz (if it looks rotated 180°, set `laser.yaw` in
`hbot_geometry.yaml`), and drive a short teleop loop to confirm the rotation
odometry with the new track.
