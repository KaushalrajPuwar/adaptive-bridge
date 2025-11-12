from setuptools import setup, find_packages

package_name = 'adaptive-bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(include=['adaptive_bridge', 'adaptive_bridge.*']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='kaushalraj',
    maintainer_email='kaushalrajpuwar@protonmail.com',
    description='Adaptive bridge for ROS 2 to isolate slow subscribers',
    license='BSD-3-Clause',
    entry_points={
        'console_scripts': [
            # leave empty for now
        ],
    },
)
