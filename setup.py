import distutils
import glob
import os
import shlex
import setuptools
import setuptools.command.build_ext
import setuptools.command.develop
import setuptools.command.install
import setuptools.dist
import sys
import setuptools.command.install
import cellprofiler.utilities.version

setuptools.dist.Distribution({
    "setup_requires": [
        "clint",
        "javabridge",
        "matplotlib",
        "numpy",
        "pytest",
        "requests",
        "scipy",
        "pyzmq"
    ]
})

try:
    import matplotlib
    import numpy # for proper discovery of its libraries by distutils
    import scipy.sparse.csgraph._validation
    import zmq   # for proper discovery of its libraries by distutils
    import zmq.libzmq
except ImportError:
    pass

if sys.platform.startswith("win"):
    import _winreg
    try:
        import py2exe
        has_py2exe = True
    except:
        has_py2exe = False
else:
    has_py2exe = False    

# Recipe needed to get real distutils if virtualenv.
# Error message is "ImportError: cannot import name dist"
# when running app.
# See http://sourceforge.net/p/py2exe/mailman/attachment/47C45804.9030206@free.fr/1/
#
if hasattr(sys, 'real_prefix'):
    # Running from a virtualenv
    assert hasattr(distutils, 'distutils_path'), \
           "Can't get real distutils path"
    libdir = os.path.dirname(distutils.distutils_path)
    sys.path.insert(0, libdir)
    #
    # Get the system "site" package, not the virtualenv one. This prevents
    # site.virtual_install_main_packages from being called, resulting in
    # "IOError: [Errno 2] No such file or directory: 'orig-prefix.txt'
    #
    del sys.modules["site"]
    import site
    assert not hasattr(site, "virtual_install_main_packages")

#
# Recipe for ZMQ
#
if sys.platform.startswith("win"):
    #
    # See http://www.py2exe.org/index.cgi/Py2exeAndzmq
    # Recipe needed for py2exe to package libzmq.dll
    os.environ["PATH"] += os.path.pathsep + os.path.split(zmq.__file__)[0]

class Install(setuptools.command.install.install):
    def run(self):
        self.run_command("build_version")
        self.run_command("build_java_dependencies")
        setuptools.command.install.install.run(self)

class Develop(setuptools.command.develop.develop):
    def install_for_development(self):
        self.reinitialize_command("build_version", inplace=1)
        self.reinitialize_command("build_java_dependencies", inplace=1)
        setuptools.command.develop.develop.install_for_development(self)

class BuildVersion(setuptools.Command):
    user_options = [
        ("version", None, "CellProfiler semantic version"),
        ("inplace", None, "Ignore build lib and write in-place")]

    def initialize_options(self):
        self.build_lib = None
        self.version = None
        self.inplace = None

    def finalize_options(self):
        self.set_undefined_options(
            'build', ('build_lib', 'build_lib'))
        if self.version is None:
            self.version = self.distribution.metadata.version

    def run(self):
        directory = "." if self.inplace else self.build_lib
        with open(os.path.join(directory, "cellprofiler", "frozen_version.py"),
                  "w") as fd:
            fd.write("version_string='%s'\n" % 
                     cellprofiler.utilities.version.version_string)
            fd.write("dotted_version='%s'\n" % self.version)

class BuildJavaDependencies(setuptools.Command):
    user_options = [
        ("prokaryote-version=", None, "Version # of prokaryote to fetch"),
        ("inplace", None, "Put dependencies in-place in the source tree")]

    def initialize_options(self):
        self.build_lib = None
        self.prokaryote_version = None
        self.inplace = None

    def finalize_options(self):
        self.set_undefined_options(
            'build', ('build_lib', 'build_lib'))
        if self.prokaryote_version is None:
            raise distutils.errors.DistutilsSetupError(
                "The version of the prokaryote jar must be specified using the "
                "--prokaryote-version switch")

    def run(self):
        try:
            import clint.textui
            import requests
        except ImportError:
            raise ImportError

        root = os.path.dirname(__file__) if self.inplace else self.build_lib
        directory = os.path.join(root, "imagej", "jars")

        if not os.path.exists(directory):
            os.makedirs(directory)

        prokaryote = "{}/prokaryote-{}.jar".format(
            os.path.abspath(directory), self.prokaryote_version)

        resource = "https://github.com/CellProfiler/prokaryote/" + \
            "releases/download/{tag}/prokaryote-{tag}.jar".format(
                tag=self.prokaryote_version)

        request = requests.get(resource, stream=True)

        if not os.path.isfile(prokaryote):
            with open(prokaryote, "wb") as f:
                total_length = int(request.headers.get("content-length"))

                chunks = clint.textui.progress.bar(request.iter_content(chunk_size=32768), expected_size=(total_length / 32768) + 1, hide=not self.verbose)

                for chunk in chunks:
                    if chunk:
                        f.write(chunk)

                        f.flush()

        dependencies = os.path.abspath(os.path.join(
            root, 'imagej', 'jars', 
            'cellprofiler-java-dependencies-classpath.txt'))

        if not os.path.isfile(dependencies):
            dependency = open(dependencies, "w")

            dependency.write(prokaryote)

            dependency.close()

class Test(setuptools.Command):
    user_options = [
        ("pytest-args=", "a", "arguments to pass to py.test")
    ]

    def initialize_options(self):
        self.pytest_args = []

    def finalize_options(self):
        pass

    def run(self):
        try:
            import pytest
            import unittest
        except ImportError:
            raise ImportError

        import cellprofiler.__main__
        import cellprofiler.utilities.cpjvm

        #
        # Monkey-patch pytest.Function
        # See https://github.com/pytest-dev/pytest/issues/1169
        #
        try:
            from _pytest.unittest import TestCaseFunction

            def runtest(self):
                setattr(self._testcase, "__name__", self.name)
                self._testcase(result=self)

            TestCaseFunction.runtest = runtest
        except:
            pass

        try:
            import ilastik.core.jobMachine

            ilastik.core.jobMachine.GLOBAL_WM.set_thread_count(1)
        except ImportError:
            pass

        cellprofiler.utilities.cpjvm.cp_start_vm()

        errno = pytest.main(self.pytest_args)

        cellprofiler.__main__.stop_cellprofiler()

        sys.exit(errno)

if has_py2exe:        
    class CPPy2Exe(py2exe.build_exe.py2exe):
        user_options = py2exe.build_exe.py2exe.user_options + [
            ("msvcrt-redist=", None, 
             "Directory containing the MSVC redistributables"),
            ("with-ilastik", None,
             "Build CellProfiler with Ilastik dependencies")]
        def initialize_options(self):
            py2exe.build_exe.py2exe.initialize_options(self)
            self.msvcrt_redist = None
            self.with_ilastik = None
            
        def finalize_options(self):
            py2exe.build_exe.py2exe.finalize_options(self)
            if self.msvcrt_redist is None:
                try:
                    key = _winreg.OpenKey(
                        _winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Wow6432Node\Microsoft\VisualStudio\9.0"+
                        r"\Setup\VC")
                    product_dir = _winreg.QueryValueEx(key, "ProductDir")[0]
                    self.msvcrt_redist = os.path.join(
                        product_dir, "redist", "amd64", "Microsoft.VC90.CRT")
                except WindowsError:
                    self.announce(
                        "Package will not include MSVCRT redistributables", 3)
            
        def run(self):
            self.reinitialize_command("build_version", inplace=1)
            self.run_command("build_version")
            self.reinitialize_command("build_java_dependencies", inplace=1)
            self.run_command("build_java_dependencies")
            #
            # py2exe runs install_data a second time. We want to inject some
            # data files into the dist but we do it here so that if the user
            # does a straight "install", they won't end up dumped into their
            # Python directory.
            #
            # py2exe doesn't have its own data_files or resources options.
            #
            import javabridge
            from cellprofiler.utilities.cpjvm import get_path_to_jars
            
            if self.distribution.data_files is None:
                self.distribution.data_files = []
            self.distribution.data_files.append(
                ("artwork", glob.glob("artwork/*")))
            #
            # py2exe recipe for matplotlib
            #
            self.distribution.data_files += matplotlib.get_py2exe_datafiles()
            #
            # Collect the javabridge and imagej JAR files
            #
            self.distribution.data_files.append(
                ("javabridge/jars", javabridge.JARS))
            self.distribution.data_files.append(
                ("imagej/jars", 
                 glob.glob(os.path.join(get_path_to_jars(), "prokaryote*.jar")) +
                 [os.path.join(get_path_to_jars(), 
                               "cellprofiler-java-dependencies-classpath.txt")]))
            #
            # Support for zmq-14.0.0+
            #
            zmq_version = tuple([int(_) for _ in zmq.__version__.split(".")])
            if zmq_version >= (14, 0, 0):
                # Backends are new in 14.x
                self.includes += [
                    "zmq.backend", "zmq.backend.cython", "zmq.backend.cython.*",
                    "zmq.backend.cffi", "zmq.backend.cffi.*"]
                #
                # Must include libzmq.pyd without renaming because it's
                # linked against. The problem is that py2exe renames it
                # to "zmq.libzmq.pyd" and then the linking fails. So we
                # include it as a data file and exclude it as a dll.
                #
                if zmq_version >= (14, 0, 0):
                    self.distribution.data_files.append(
                        (".", [zmq.libzmq.__file__]))
                    self.dll_excludes.append("libzmq.pyd")
            #
            # Add ilastik UI files
            #
            if self.with_ilastik:
                import ilastik
                ilastik_root = os.path.dirname(ilastik.__file__)
                for root, directories, filenames in os.walk(ilastik_root):
                    relpath = root[len(os.path.dirname(ilastik_root))+1:]
                    ui_filenames = [
                        os.path.join(root, f) for f in filenames
                        if any([f.lower().endswith(ext) 
                                for ext in ".ui", ".png"])]
                    if len(ui_filenames) > 0:
                        self.distribution.data_files.append(
                            (relpath, ui_filenames))
                
                #
                # Prevent rename of vigranumpycore similarly to libzmq
                #
                import vigra.vigranumpycore
                self.distribution.data_files.append(
                    (".", [vigra.vigranumpycore.__file__]))
            
            if self.msvcrt_redist is not None:
                sources = [
                    os.path.join(self.msvcrt_redist, filename)
                    for filename in os.listdir(self.msvcrt_redist)]
                self.distribution.data_files.append(
                    ("./Microsoft.VC90.CRT", sources))

            py2exe.build_exe.py2exe.run(self)
        
    class CellProfilerMSI(distutils.core.Command):
        description = \
            "Make CellProfiler.msi using the CellProfiler.iss InnoSetup compiler"
        user_options = [("with-ilastik", None, 
                         "Include a start menu entry for Ilastik"),
                        ("output-dir=", None,
                         "Output directory for MSI file"),
                        ("msi-name=", None,
                         "Name of MSI file to generate (w/o extension)")]
        
        def initialize_options(self):
            self.with_ilastik = None
            self.py2exe_dist_dir = None
            self.output_dir = None
            self.msi_name = None
        
        def finalize_options(self):
            self.set_undefined_options(
                "py2exe", ("dist_dir", "py2exe_dist_dir"))
            if self.output_dir is None:
                self.output_dir = ".\\output"
            if self.msi_name is None:
                self.msi_name = \
                    "CellProfiler-" + self.distribution.metadata.version
        
        def run(self):
            if not os.path.isdir(self.output_dir):
                os.makedirs(self.output_dir)
            with open("version.iss", "w") as fd:
                fd.write("""
    AppVerName=CellProfiler %s
    OutputBaseFilename=%s
    OutputDir=%s
    """ % (self.distribution.metadata.version, 
           self.msi_name,
           self.output_dir))
            with open("ilastik.iss", "w") as fd:
                if self.with_ilastik:
                    fd.write(
                        'Name: "{group}\Ilastik"; '
                        'Filename: "{app}\CellProfiler.exe"; '
                        'Parameters:"--ilastik"; WorkingDir: "{app}"\n')
            if numpy.log(sys.maxsize) / numpy.log(2) > 32:
                cell_profiler_iss = "CellProfiler64.iss"
            else:
                cell_profiler_iss = "CellProfiler.iss"
            required_files = [
                os.path.join(self.py2exe_dist_dir, "CellProfiler.exe"), 
                cell_profiler_iss]
            compile_command = self.__compile_command()
            compile_command = compile_command.replace("%1", cell_profiler_iss)
            compile_command = shlex.split(compile_command)
            self.make_file(
                required_files, 
                os.path.join(self.output_dir, self.msi_name + ".msi"), 
                self.spawn, [compile_command],
                "Compiling %s" % cell_profiler_iss)
            os.remove("version.iss")
            os.remove("ilastik.iss")

        def __compile_command(self):
            """Return the command to use to compile an .iss file
            """
            try:
                key = _winreg.OpenKey(
                    _winreg.HKEY_CLASSES_ROOT, 
                    "InnoSetupScriptFile\\shell\\Compile\\command")
                result = _winreg.QueryValueEx(key,None)[0]
                key.Close()
                return result
            except WindowsError:
                if key:
                    key.Close()
                raise distutils.errors.DistutilsFileError, \
                      "Inno Setup does not seem to be installed properly. " + \
                      "Specifically, there is no entry in the " +\
                      "HKEY_CLASSES_ROOT for InnoSetupScriptFile\\shell\\" + \
                      "Compile\\command"

cmdclass = {
        "build_java_dependencies": BuildJavaDependencies,
        "build_version": BuildVersion,
        "develop": Develop,
        "install": Install,
        "test": Test
    }

if has_py2exe:
    cmdclass["py2exe"] = CPPy2Exe
    cmdclass["py2exe_ilastik"] = CPPy2Exe
    cmdclass["msi"] = CellProfilerMSI

setuptools.setup(
    app=[
        "CellProfiler.py"
    ],
    author="cellprofiler-dev",
    author_email="cellprofiler-dev@broadinstitute.org",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: C",
        "Programming Language :: C++",
        "Programming Language :: Cython",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Topic :: Scientific/Engineering :: Image Recognition",
        "Topic :: Scientific/Engineering"
    ],
    cmdclass = cmdclass,
    console = [ 
        {
        "icon_resources": [
            (1, "artwork/CellProfilerIcon.ico")
            ],
        "script" : "CellProfiler.py"
        },
        {
            "icon_resources": [
                (1, "artwork/CellProfilerIcon.ico")
                ],
            "script" : "cellprofiler/analysis_worker.py"
            }],
    description="",
    entry_points={
        "console_scripts": [
            "cellprofiler=cellprofiler.__main__:main"
        ]
    },
    include_package_data=True,
    install_requires=[
        "cellh5",
        "centrosome",
        "h5py",
        "javabridge",
        "libtiff",
        "matplotlib",
        "MySQL-python",
        "numpy",
        "pytest",
        "python-bioformats",
        "pyzmq",
        "scipy"
    ],
    keywords="",
    license="BSD",
    long_description="",
    name="CellProfiler",
    package_data={
        "artwork": glob.glob(os.path.join("artwork", "*"))
    },
    packages=setuptools.find_packages(exclude=[
        "*.tests",
        "*.tests.*",
        "tests.*",
        "tests",
        "tutorial"
    ]),
    setup_requires=[
        "clint",
        "pytest",
        "requests"
    ],
    url="https://github.com/CellProfiler/CellProfiler",
    version="2.2.0rc1"
)
