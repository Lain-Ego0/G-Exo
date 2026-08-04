"""Dual-mode setup: works with both `colcon build` (ament_python) and
`pip install -e .` on a machine without ROS 2 (e.g. Windows dev box).

rclpy is intentionally NOT in install_requires: it is an exec_depend in
package.xml and is imported lazily only when the ros2 transport is selected.
"""
from setuptools import find_packages, setup

package_name = "gexo_web_agent"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/gexo_web_agent.launch.py"]),
        (f"share/{package_name}/config", ["config/default.yaml"]),
    ],
    install_requires=[
        "fastapi>=0.100",
        "uvicorn>=0.23",
        "pydantic>=2.0",
        "pydantic-settings>=2.0",
        "httpx>=0.24",
        "jieba>=0.42",
        "pypdf>=3.0",
        "PyYAML>=6.0",
    ],
    zip_safe=True,
    maintainer="G-Exo Team",
    maintainer_email="dev@g-exo.local",
    description="G-Exo web agent: local LLM chat + web UI + ROS 2 control bridge",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "gexo-web-agent = gexo_web_agent.main:main",
            "gexo-mock-controller = gexo_web_agent.mock_controller_node:main",
        ],
    },
    include_package_data=True,
    package_data={package_name: ["../static/*", "../config/*.yaml"]},
)
