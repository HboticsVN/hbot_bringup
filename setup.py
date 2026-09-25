from glob import glob

from setuptools import find_packages, setup

package_name = 'hbot_bringup'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/hbot_bringup.launch.py', 'launch/base_bringup.launch.py', 'launch/web_bringup.launch.py']),
        ('share/' + package_name + '/config', ['config/nav2_params.yaml',
                                               'config/twist_mux.yaml']),
        ('share/' + package_name + '/config', ['config/slam_params.yaml']),
        ('share/' + package_name + '/config', ['config/slam_params_localize.yaml']),
        ('share/' + package_name + '/config', ['config/yahboom_driver_params.yaml']),
        ('share/' + package_name + '/config', ['config/ekf.yaml']),
        ('share/' + package_name + '/config', ['config/hbot.rviz']),
        ('share/' + package_name + '/config', ['config/carto_mapping.lua']),
        # Pre-built sample maps (used by slam:=False localization mode; the
        # hbot_house_sim map is built from the Gazebo world - see
        # scripts/dev_sim_build_map.sh).
        ('share/' + package_name + '/maps', glob('maps/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='huyhust13@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
        ],
    },
)
