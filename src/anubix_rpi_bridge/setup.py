from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'anubix_rpi_bridge'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ANUBIX Team',
    maintainer_email='anubix@example.com',
    description='ANUBIX RPi Bridge — cross-machine link monitor, traffic logger, and safety watchdog',
    license='MIT',
    entry_points={
        'console_scripts': [
            'rpi_bridge_node = anubix_rpi_bridge.rpi_bridge_node:main',
        ],
    },
)
