from setuptools import setup
import os
from glob import glob

package_name = 'adaptive_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        # Step 1 hygiene: package real config assets from src/adaptive_bridge/config/
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='kaushalraj',
    maintainer_email='kaushalrajpuwar@gmail.com',
    description='Adaptive Bridge for mitigating slow subscriber issues in ROS 2.',
    license='BSD-3-Clause',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'proxy_node = adaptive_bridge.proxy_node:main',
            'classifier_node = adaptive_bridge.classifier_node:main',
            'diagnostics_node = adaptive_bridge.diagnostics:main'
        ],
    },
)
