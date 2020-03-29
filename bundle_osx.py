#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import glob
import logging
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from os import chmod, environ, listdir, lstat, makedirs, path, remove, symlink
from time import time
from typing import List
from urllib.request import urlretrieve

MINICONDA_URL = "https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
CONDA_BASE = ""


def safe_conda_base(buildpath: str) -> str:
    """Return path to a 'safe' location (no spaces) for the base conda install.

    Parameters
    ----------
    buildpath : str
        The buildpath for the current bundle.  Will prefer putting stuff into the build
        path, unless there are spaces... in which case it will go in ``~/_temp_conda``

    Returns
    -------
    str
        path to a location where conda can be installed
    """
    buildpath = path.abspath(path.expanduser(buildpath))
    conda_dir = path.join(buildpath, "conda")
    if " " not in conda_dir:
        return conda_dir

    # TODO: is there a better way to handle spaces in the target dir?
    alt_dir = path.abspath(path.expanduser("~/_temp_conda"))
    logging.warning(
        f"SPACE found in target conda directory: {conda_dir}\n"
        f"\tusing alternative path: {alt_dir}"
    )
    return alt_dir


def install_conda(buildpath: str) -> str:
    global CONDA_BASE
    conda_dir = safe_conda_base(buildpath)
    CONDA_BASE = conda_dir

    if not path.exists(conda_dir):
        logging.info(f"Installing miniconda to {conda_dir}")
        miniconda_installer = path.join(buildpath, "miniconda_installer.sh")
        if not path.exists(miniconda_installer):
            urlretrieve(MINICONDA_URL, filename=miniconda_installer)
        subprocess.run(["bash", f"{miniconda_installer}", "-b", "-p", f'"{conda_dir}"'])
    else:
        logging.info(f"Using existing miniconda installation at {conda_dir}")
    return conda_dir


def conda_run(args: List[str], env_name: str = "base"):
    """Run a command from the conda base (or ``env_name``).

    This function puts the corresponding conda environment binaries and site-packages
    at the front of the PATH and PYTHONPATH environmental variables before running the
    command.

    Parameters
    ----------
    args : List[str]
        standard command string as would be provided to subprocess.run
    env_name : str, optional
        Optional name of a conda environment in which to run command, by default "base"
    """
    assert path.isdir(CONDA_BASE), f"Could not find conda environment at {CONDA_BASE}"
    env = environ.copy()
    env["PATH"] = f"{path.join(CONDA_BASE, 'bin')}:{environ.get('PATH')}"
    env["PYTHONPATH"] = ":".join(glob.glob(CONDA_BASE + "/lib/python*/site-packages"))
    if env_name != "base":
        env_dir = path.join(CONDA_BASE, "envs", env_name)
        env["PATH"] = f"{path.join(env_dir, 'bin')}:{env['PATH']}"
        env_pkgs = glob.glob(env_dir + "/lib/python*/site-packages")
        env["PYTHONPATH"] = ":".join(env_pkgs)
    logging.debug(f"ENV_RUN: {' '.join(args)}")
    subprocess.run(args, env=env)


def create_env(
    conda_base: str,
    app_name: str,
    pyversion: str = "3.8",
    pip_install: List[str] = [],
    confirm: bool = True,
) -> str:
    """Create a new conda environment in ``conda_base``/envs.

    Parameters
    ----------
    conda_base : str
        Directory of conda installation to use
    app_name : str
        Name of app.  This will be used as the name of the environment, *and* if the
        ``pip_install`` list is empty, will be installed as a package.
    pyversion : str, optional
        The python version to bundle, by default "3.8"
    pip_install : List[str], optional
        Explicit list of packages to install, as would be passed to pip install.
        If provided, ``app_name`` will NOT be installed unless it is a member of this
        list.  by default []
    confirm : bool, optional
        Whether to confirm deletion of an existing environment at the target location,
        by default True

    Returns
    -------
    env_dir : str
        The path to the newly created environment folder at ``conda/envs/app_name``
    """
    env_dir = path.join(conda_base, "envs", app_name)
    if (
        path.exists(env_dir)
        and confirm
        and not get_confirmation("Environment already exists, overwrite?")
    ):
        logging.info(f"Using existing conda environment: {env_dir}")
    else:
        if path.exists(env_dir):
            logging.info(f"Deleting existing conda environment: {env_dir}")
            shutil.rmtree(env_dir)
        logging.info(f"Creating conda environment: {env_dir}")
        conda_run(
            [
                "conda",
                "create",
                "-n",
                app_name,
                "-c",
                "conda-forge",
                "-y",
                f"python={pyversion}",
            ]
        )

    if not pip_install:
        logging.info(f"No pip packages specified... trying `pip install {app_name}`")
        pip_install = [app_name]
    logging.info("Installing packages with pip")
    # ignore-installed is important otherwise deps that are in the base environment
    # may not make it into the bundle
    conda_run(["pip", "install", "--ignore-installed"] + pip_install, app_name)

    # # here is how you would install using conda
    # logging.info("Installing packages with conda")
    # conda_run(["conda", "install", "-n", app_name, "-y", app_name])

    return env_dir


def bundle_conda_env(
    env_dir: str, app_path: str, include: List[str] = [], exclude: List[str] = [],
):
    """Copy the conda env at ``env_dir`` into the .app at ``app_path``

    Parameters
    ----------
    env_dir : str
        The source path to the conda environment to copy.
    app_path : str
        The destination path to the app_name.app bundle that is being packaged.
    include : list of str, optional
        directories in conda environment to include when bundling, by default []
    exclude : list of str, optional
        glob patterns (relative to the base conda environment) to exclude when bundling,
        by default []
    """
    app_resource_dir = path.join(app_path, "Contents", "Resources")
    if not include:
        include = listdir(env_dir)
    for item in include:
        fullpath = path.join(env_dir, item)
        dest = path.join(app_resource_dir, item)
        if path.exists(dest):
            shutil.rmtree(dest)
        logging.info(f"Copying {fullpath} to bundle")
        if path.isdir(fullpath):
            shutil.copytree(
                fullpath, dest, symlinks=True,
            )
        else:
            shutil.copy(fullpath, dest)

    for pattern in exclude:
        full_path = path.join(app_resource_dir, pattern)
        for item in glob.glob(full_path):
            try:
                if path.isdir(item):
                    logging.info(f"Removing folder: {item}")
                    shutil.rmtree(item)
                elif path.isfile(item):
                    logging.info(f"Removing file: {item}")
                    remove(item)
                else:
                    logging.error(f"File not found: {item}")
            except (IOError, OSError):
                logging.error(f"could not delete {item}")


def get_confirmation(question: str, default_yes: bool = True) -> bool:
    """Retrieve y/n answer from user, with default."""
    question = question + (" ([y]/n): " if default_yes else " (y/[n]): ")
    resp = input(question)
    while resp not in ["y", "n", ""]:
        resp = input(question)
    if (resp == "" and not default_yes) or resp == "n":
        return False
    return True


def create_app_folder(name: str, distpath: str, confirm: bool = True) -> str:
    """Create the (empty) structure of a MacOSX app directory.

    Parameters
    ----------
    name : str
        The name of the application.
    distpath : str
        The directory in which to create the app
    confirm : bool, optional
        Whether to confirm deletion of an existing app at the target location,
        by default True

    Returns
    -------
    app_path : str
        The full path to the newly created app folder: ``distpath/name.app``
    """
    app_name = f"{name}.app"
    distpath = path.abspath(path.expanduser(distpath))
    app_path = path.join(distpath, app_name)
    # Check if app already exists and ask user what to do if so.
    if path.exists(app_path):
        if confirm and not get_confirmation("App already exists, overwrite?"):
            logging.info("Skipping app creation")
            return app_path
        logging.info("Removing previous app")
        shutil.rmtree(app_path)

    for folder in ("MacOS", "Resources", "Frameworks"):
        makedirs(path.join(app_path, "Contents", folder))
    return app_path


def copy_icon(app_path: str, icon_path: str) -> str:
    """Copy icon into app_path/Contents/Resources.

    Parameters
    ----------
    app_path : str
        path to mac .app directory being bundled.
    icon_path : str, optional
        path to icon file to include in bundle.

    Returns
    -------
    icon_basename : str
        the basename of the icon included in Contents/Resources.  This can be passed as
        the ``icon_name`` argument in ``create_info_plist``.
    """
    if path.isfile(icon_path):
        logging.info(f"Copying icon from {icon_path} to bundle")
        icon_basename = path.basename(icon_path)
        shutil.copy(
            icon_path, path.join(app_path, "Contents", "Resources", icon_basename)
        )
    else:
        logging.warning(f"Could not find icon at {icon_path}")
        icon_basename = ""
    return icon_basename


def create_info_plist(
    app_path: str,
    app_name: str = "",
    icon_name: str = "",
    version: str = "0.1.0",
    app_author: str = "",
    copyright: str = "",
):
    """Create an Info.plist file and copy it to the /Contents folder of app_path.

    Parameters
    ----------
    app_path : str
        The path to the app_name.app bundle that is being packaged.
    app_name : str, optional
        The name that will be given to the app in the Info.plist file. by default, will
        use the basename of the app: ``app_path.rstrip(".app")``
    icon_name : str, optional
        Name of icon file.  File must be located in app_path, by default "" (no icon)
    version : str, optional
        Version string of the app being bundled, by default "0.1.0"
    app_author : str, optional
        App author to use in CFBundleIdentifier, by default will use ``app_name``.
    copyright : str, optional
        String to use for copyright attribution, by default ``{app_name} contributors``
    """
    if not app_name:
        app_name = path.basename(app_path).rstrip(".app")

    if icon_name:
        icon_path = path.join(app_path, "Contents", "Resources", icon_name)
        if not path.exists(icon_path):
            logging.warning(
                f"No icon file found at {icon_path} when creating Info.plist"
            )

    plist_template = path.join(path.dirname(__file__), "Info.template.plist")
    with open(plist_template, "r") as f:
        template = f.read()

    template = template.replace("{{ app_name }}", app_name)
    template = template.replace("{{ app_author }}", app_author or app_name)
    template = template.replace("{{ app_icon }}", icon_name)
    template = template.replace("{{ app_version }}", version)
    template = template.replace("{{ year }}", str(datetime.now().year))
    template = template.replace(
        "{{ copyright }}", copyright or f"{app_name} contributors"
    )

    with open(path.join(app_path, "Contents", "Info.plist"), "w") as f:
        logging.info("Writing Info.plist")
        f.write(template)


def create_exe(app_path: str, pyscript: str = ""):
    """Create runnable script in bundle.app/Contents/MacOS.

    This will create an executable bash script at ``app_path/Contents/MacOS/app_name``.
    The script will add ``app_path/Contents/Resources/bin`` to the environment PATH, and
    then execute a python script located at ``pyscript``, or, if pyscript is not
    provided, at ``Resources/bin/{app_name}``.

    Parameters
    ----------
    app_path : str
        Path to a mac .app bundle
    pyscript : str, optional.
        Path (relative to app_path) of a python script (i.e. "the real app") that should
        be run when the app is started.  By default, will point to a script at
        ``Resources/bin/{app_name}``.  (Assuming the package being installed has a
        ``console_scripts`` entry point in its setup.py file, setuptools will have
        created an executable script in the environment's ``/bin`` folder.)
    """
    app_name = path.basename(app_path).strip(".app")
    exe_path = path.join(app_path, "Contents", "MacOS", app_name)
    if not pyscript:
        pyscript = f"Resources/bin/{app_name}"
    if not path.exists(path.join(app_path, "Contents", pyscript)):
        logging.error(
            f"No python script found at {path.join(app_path, 'Contents', pyscript)}. "
            "This app may not run properly"
        )
    with open(exe_path, "w") as fp:
        try:
            fp.write(
                "#!/usr/bin/env bash\n"
                'contents_dir=$(dirname "$(dirname "$0")")\n'
                'export PATH=:"$contents_dir/Resources/bin/":$PATH\n'
                f'"$contents_dir/Resources/bin/python" "$contents_dir/{pyscript}" $@'
            )
        except IOError:
            logging.critical(f"Could not create Contents/MacOS/{app_name} script")
            sys.exit(1)

    # Set execution flags
    current_permissions = stat.S_IMODE(lstat(exe_path).st_mode)
    chmod(exe_path, current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_dmg(app_path: str, keep_app: bool = False) -> str:
    """Bundle app at ``app_path`` into a .dmg file for distribution.

    Will also include a symlink to ``/Applications``.

    Parameters
    ----------
    app_path : str
        path to mac .app directory being bundled.
    keep_app : bool, optional
        Whether to keep an unbundled copy of the app, outside of the .dmg file, or not.
        by default False
    """
    dmg_dir = path.join(path.dirname(app_path), "dmg")
    dmg_file = app_path.replace(".app", ".dmg")
    makedirs(dmg_dir, exist_ok=True)
    if not path.exists(path.join(dmg_dir, "Applications")):
        symlink("/Applications", path.join(dmg_dir, "Applications"))
    if keep_app:
        shutil.copytree(app_path, dmg_dir)
    else:
        shutil.move(app_path, dmg_dir)
    logging.info("Creating DMG archive...")
    result = subprocess.run(
        ["hdiutil", "create", f"{dmg_file}", "-srcfolder", f"{dmg_dir}"],
        capture_output=True,
    )
    if result.returncode == 0:
        logging.info("DMG successfully created")
        shutil.rmtree(dmg_dir)
        return dmg_file
    else:
        logging.error(f"DMG creation failed: {result.stderr.decode().strip()}")
        return ""


def sign_app(target: str, cert_name: str = "-"):
    try:
        if cert_name == "-":
            logging.info(f"No code certificate supplied, using ad-hoc signature")
        if cert_name:
            subprocess.check_call(
                ["codesign", "--force", "--deep", "-s", cert_name, target]
            )
        logging.info(f"Successfully signed {target}")
    except subprocess.CalledProcessError as e:
        logging.error(f"App code signing failed: {e}")


def main(
    name: str,
    distpath: str = "./dist",
    buildpath: str = "./build",
    noconfirm: bool = False,
    py: str = "3.8",
    pip_install: List[str] = [],
    conda_include: List[str] = [],
    conda_exclude: List[str] = [],
    icon: str = "",
    nodmg: bool = False,
    cert_name: str = "-",
):
    """Main program to bundle a conda env into a mac app.

    Will create an DMG-packaged app at ``distpath/name.dmg`` unless ``nodmg`` is
    ``True``, in which case will create an app at ``distpath/name.app``

    Parameters
    ----------
    name : str
        Name of the app being bundled
    distpath : str, optional
        Destination directory for the app, by default "./dist"
    buildpath : str, optional
        Directory to put build resources, by default "./build"
    noconfirm : bool, optional
        Replace existing directories without asking for confirmation, by default False
    py : str, optional
        The python version to bundle, by default "3.8", by default "3.8"
    pip_install : list of str, optional
        Explicit list of packages to install, as would be passed to pip install.
        If provided, ``name`` will NOT be installed unless it is a member of this
        list.  by default pip will try to install a package named ``name``.
    conda_include : list of str, optional
        directories in conda environment to include when bundling, by default []
    conda_exclude : list of str, optional
        glob patterns (relative to the base conda environment) to exclude when bundling,
        by default []
    icon : str, optional
        Path to an .icns file to use for this app.  By default, no icon will be used.
    nodmg : bool, optional
        Whether to skip putting the new app into a dmg file, by default a dmg WILL be
        created at ``distpath/name.dmg``
    cert_name : str, optional
        If provided, will be used to code-sign the app bundle using the (common) name of
        a certificate that must be in the keychain.  By default, ad-hoc code signing is
        used.
    """
    logging.info(f'Creating "{name}.app"')
    start_t = time()

    # create dist/appname.app/ and all subdirectories
    app_path = create_app_folder(name, distpath, not noconfirm)
    # download and install miniconda into buildpath
    makedirs(buildpath, exist_ok=True)
    conda_base = install_conda(buildpath)
    # create a new environment and install app named name
    env_dir = create_env(conda_base, name, py, pip_install, not noconfirm)
    # move newly-created environment into dist/appname.app/Contents/Resources
    bundle_conda_env(env_dir, app_path, conda_include, conda_exclude)
    # put icon into dist/appname.app/Contents/Resources
    if icon:
        icon_basename = copy_icon(app_path, path.abspath(path.expanduser(icon)))
    else:
        icon_basename = ""
    # create Info.plist in dist/appname.app/Contents
    create_info_plist(app_path, name, icon_basename)
    # create dist/appname.app/Contents/MacOS/appname script
    create_exe(app_path)
    if cert_name:
        sign_app(app_path, cert_name)

    # bundle into a dmg
    if not nodmg:
        make_dmg(app_path)
    logging.info(f"App created in {int(time() - start_t)} seconds")


if __name__ == "__main__":

    class CleanAction(argparse.Action):
        def __call__(self, parser, args, values, option_string=None):
            conda_base = safe_conda_base(args.buildpath)
            print(f"Deleting (local) conda installation: {conda_base}")
            shutil.rmtree(conda_base, ignore_errors=True)
            print(f"Deleting distpath folder: {args.distpath}")
            shutil.rmtree(args.distpath, ignore_errors=True)
            print(f"Deleting buildpath folder: {args.buildpath}")
            shutil.rmtree(args.buildpath, ignore_errors=True)
            sys.exit()

    class MakeDMG(argparse.Action):
        def __call__(self, parser, args, values, option_string=None):
            logging.basicConfig(level=args.log_level)
            make_dmg(values[0], keep_app=True)
            sys.exit()

    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument(
        "-y",
        "--noconfirm",
        help="Replace existing app and resources without asking for confirmation",
        action="store_true",
    )
    parser.add_argument(
        "name",
        help=(
            "Name of app to bundle. If '--pip-install' is not specified,\n"
            "this name is also assumed to be a pip-installable package."
        ),
        type=str,
        metavar="app_name",
    )
    parser.add_argument(
        "-i",
        "--icon",
        help=("Icon file (in .icns format) for the bundle."),
        metavar="",
        type=argparse.FileType("r"),
    )
    parser.add_argument(
        "--distpath",
        help="Where to put the bundled app (default: ./dist)",
        type=str,
        metavar="",
        default="./dist",
    )
    parser.add_argument(
        "--buildpath",
        help="Where to put build resources (default: ./build)",
        type=str,
        metavar="",
        default="./build",
    )
    parser.add_argument(
        "--py",
        help="Python version to bundle. (default 3.8)",
        type=str,
        metavar="",
        default="3.8",
        choices=["3.6", "3.7", "3.8"],
    )
    parser.add_argument(
        "--nodmg",
        help="Do not package app into .dmg file.  By default a DMG will be created",
        action="store_true",
    )
    parser.add_argument(
        "--pip-install",
        help=(
            "Install these pip packages. Multiple arguments accepted\n"
            "as would be passed to pip install. If not provided, will\n"
            "attempt to `pip install <app_name>` using `app_name` argument.\n"
            "If '--pip-install' IS provided, then 'app_name' will NOT be\n"
            "installed unless explicitly included in this list."
        ),
        nargs="*",
        metavar="",
        default=[],
    )
    parser.add_argument(
        "--conda-include",
        help="directories in conda environment to include when bundling",
        type=str,
        metavar="",
        nargs="*",
        default=[],
    )
    parser.add_argument(
        "--conda-exclude",
        help="glob patterns (from base conda environment) to exclude when bundling",
        type=str,
        metavar="",
        nargs="*",
        default=["bin/*-qt4*"],
    )
    parser.add_argument(
        "--cert-name",
        help=(
            "Optional name of certificate in keychain with which to sign app.\n"
            "By default, uses ad-hoc code signing"
        ),
        type=str,
        metavar="",
        default="-",
    )
    parser.add_argument(
        "--log-level",
        help=(
            "Amount of detail in build-time console messages."
            "\nmay be one of TRACE, DEBUG, INFO, WARN,"
            "ERROR, CRITICAL\n(default: WARN)"
        ),
        type=str,
        metavar="",
        default="WARN",
        choices=["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "--clean",
        help="Delete all folders created by this bundler and exit.",
        nargs=0,
        action=CleanAction,
    )
    parser.add_argument(
        "--make-dmg",
        help="Bundle prebuilt .app into a DMG, then exit.",
        action=MakeDMG,
        type=str,
        nargs=1
    )

    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)
    kwargs = vars(args)
    kwargs.pop("log_level")
    kwargs.pop("clean")
    kwargs.pop("make_dmg")
    icon = kwargs.pop("icon")
    kwargs["icon"] = icon.name if icon else None
    main(**kwargs)
