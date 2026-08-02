"""Build hook for the spacemit_vad CMake extension."""

import os
import sys
import subprocess
import shutil
from pathlib import Path

from setuptools import setup, Extension, find_packages
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    """CMake extension for pybind11 module"""

    def __init__(self, name, source_dir=""):
        super().__init__(name, sources=[])
        self.source_dir = os.path.abspath(source_dir)


class CMakeBuild(build_ext):
    """Build extension using CMake"""

    def build_extension(self, ext):
        ext_dir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))
        prebuilt_extension = os.environ.get("SPACEMIT_PREBUILT_EXTENSION")
        if prebuilt_extension:
            prebuilt_path = Path(prebuilt_extension)
            if not prebuilt_path.exists():
                raise FileNotFoundError(f"Prebuilt extension not found: {prebuilt_extension}")
            os.makedirs(ext_dir, exist_ok=True)
            shutil.copy2(prebuilt_path, os.path.join(ext_dir, prebuilt_path.name))
            return

        build_dir = os.environ.get(
            "SPACEMIT_CMAKE_BUILD_DIR",
            os.path.join(self.build_temp, ext.name.replace(".", "_"), "cmake"),
        )
        build_dir = os.path.abspath(build_dir)

        # Create build directory
        os.makedirs(build_dir, exist_ok=True)

        # Clean CMakeCache.txt if source directory changed (avoid cache conflicts)
        cache_file = os.path.join(build_dir, "CMakeCache.txt")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                content = f.read()
                if ext.source_dir not in content:
                    shutil.rmtree(build_dir)
                    os.makedirs(build_dir, exist_ok=True)

        # CMake arguments
        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={ext_dir}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
            f"-DPython3_EXECUTABLE={sys.executable}",
            "-DBUILD_VAD_PYTHON=ON",
        ]

        # Build type
        build_type = os.environ.get("CMAKE_BUILD_TYPE", "Release")
        cmake_args.append(f"-DCMAKE_BUILD_TYPE={build_type}")

        # Build arguments
        build_args = ["--config", build_type, "--target", "_spacemit_vad"]

        # Parallel build
        if hasattr(os, "cpu_count"):
            build_args.extend(["--", f"-j{os.cpu_count()}"])

        # Configure
        subprocess.check_call(
            ["cmake", ext.source_dir] + cmake_args,
            cwd=build_dir
        )

        # Build
        subprocess.check_call(
            ["cmake", "--build", "."] + build_args,
            cwd=build_dir
        )

        # Only copy into the source package for explicit in-place workflows.
        pkg_dir = os.path.join(os.path.dirname(__file__), "spacemit_vad")
        if self.inplace and os.path.exists(pkg_dir):
            for suffix in [".so", ".dylib", ".pyd"]:
                pattern = f"_spacemit_vad*{suffix}"
                for path in Path(ext_dir).glob(pattern):
                    pkg_dest = os.path.join(pkg_dir, path.name)
                    shutil.copy2(path, pkg_dest)
                    break


setup(
    packages=find_packages(),
    ext_modules=[CMakeExtension("spacemit_vad._spacemit_vad", source_dir="..")],
    cmdclass={"build_ext": CMakeBuild},
)
