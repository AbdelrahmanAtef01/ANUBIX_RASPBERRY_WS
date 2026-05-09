from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'anubix_perception'

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
    description='ANUBIX Perception Stack — camera-based crop detection and pose estimation',
    license='MIT',
    entry_points={
        'console_scripts': [
            'perception_node = anubix_perception.perception_node:main',
        ],
    },
)
