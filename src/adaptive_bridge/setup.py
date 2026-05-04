from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'adaptive_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    package_data={
        package_name: ['utils/*.yaml'],
    },
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Kaushalraj Puwar',
    maintainer_email='kaushalrajpuwar@gmail.com',
    description=(
        'Adaptive Bridge is a ROS 2 middleware-level proxy that mitigates '
        'the slow-subscriber backpressure coupling problem. It decouples '
        'critical and non-critical subscriber paths to prevent a degraded '
        'remote subscriber from degrading the publisher or affecting '
        'safety-critical local consumers.'
    ),
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'proxy_node = adaptive_bridge.proxy_node:main',
            'classifier_node = adaptive_bridge.classifier_node:main',
            'diagnostics_node = adaptive_bridge.diagnostics:main',
            'probe_responder = adaptive_bridge.utils.probes:_probe_responder_main',
        ],
    },
)
