# conda-bundler

This script creates Mac OS X apps from a pip- or conda-installable package.  The
resulting app includes a complete conda environment and is NOT frozen (as would
be created with something like [pyinstaller](http://www.pyinstaller.org/)).

The inspiration (and all of the credit) for this strategy comes from [this blog
post](https://dschreij.github.io/how-to/package-anaconda-environments-as-apps)
by Daniel Schreij, where he describes using this approach to bundle the
[OpenSesame](https://github.com/smathot/OpenSesame) app.  See also [his scripts
on github](https://github.com/dschreij/anaconda-env-to-osx-app).

The main difference between this package and
[Daniel's](https://github.com/dschreij/anaconda-env-to-osx-app) is that this one
has no project-specific code in it and does not depend on `biplist` or
`dmgbuild`.  It has been generalized so that it can bundle any package(s) that
can be pip installed.  For instance, the following will create a bundled version
of [napari](https://github.com/napari/napari), a fast n-dimensional image
viewer:

```bash
python bundle_osx.py napari
```

It is also fully self-contained, and requires no pre-existing conda environment.
As such, it  can be run on continuous integration platforms and will download
all necessary conda and pip resources to build a Mac app given the name of a pip
package.

## Pros & Cons of this approach

As Daniel points out in his [blog
post](https://dschreij.github.io/how-to/package-anaconda-environments-as-apps)
and [script
readme](https://github.com/dschreij/anaconda-env-to-osx-app/blob/master/README.md)
there are a few pros and cons to this approach:

### Pros

- The resulting app will not be frozen, making it easier to maintain, update,
  and extend (for instance, to add plugins or other packages after bundling)
- The bundled environment will behave much more like your development
  environment.  Whereas pyinstaller dynamically analyzes your program and
  includes *only* the compiled bytecode and libraries required to run the
  program, this approach literally copies a complete conda environment into the
  Mac `.app/Contents/Resources` folder.

### Cons

- This is a rather unconventional way of bundling an app, and probably would not
  comply with [Apple's
  guidelines](https://developer.apple.com/app-store/review/guidelines/) for app
  packges.  As such, it would likely be difficult to get an app like this into
  the app store, and your users will probably always see the scary  "This app
  cannot be opened because the developer cannot be verified" message.  To open
  the program, they will need to go into Preferences > Security and explicitly
  allow the app.
- This creates much larger apps than pyinstaller.

## Usage

### Examples

Basic usage:

```shell
python bundle_osx.py napari
```

Include an app icon:

```shell
python bundle_osx.py napari -i path/to/icon.icns
```

Bundle an app using something other than the main pip package, such as the
default branch of a git repository:

```shell
python bundle_osx.py napari --pip-install git+https://github.com/napari/napari.git
```

Bundle together multiple pip installable apps into a custom app package:

```shell
python bundle_osx.py myapp --pip-install numpy scipy matplotlib
```

> ⚠️ TODO: there still needs to be a main "entry point" script... so this particular
> example wouldn't be that useful.  Will need to add an `--entry-point` argument
> to `bundle_osx.py` in order for this type of thing to be useful.

### Help

```
$ python bundle_osx.py --help

usage: bundle_osx.py [-h] [-y] [-i] [--distpath] [--buildpath] [--py] [--nodmg]
    [--pip-install [[...]]] [--conda-include [[...]]] [--conda-exclude [[...]]]
    [--log-level] [--clean] app_name

positional arguments:
  app_name              Name of app to bundle. If '--pip-install' is not
                        specified, this name is also assumed to be a
                        pip-installable package.

optional arguments:
  -h, --help            show this help message and exit
  -y, --noconfirm       Replace existing app and resources without asking
                        for confirmation
  -i , --icon           Icon file (in .icns format) for the bundle.
  --distpath            Where to put the bundled app (default: ./dist)
  --buildpath           Where to put build resources (default: ./build)
  --py                  Python version to bundle. (default 3.8)
  --nodmg               Do not package app into .dmg file.  By default a
                        DMG will be created
  --pip-install         Install these pip packages. Multiple arguments
                        accepted as would be passed to pip install. If not
                        provided, will attempt to `pip install <app_name>`
                        using `app_name` argument. If '--pip-install' IS
                        provided, then 'app_name' will NOT be installed
                        unless explicitly included in this list.
  --conda-include       directories in conda environment to include when
                        bundling
  --conda-exclude       glob patterns (from base conda environment) to exclude
                        when bundling
  --log-level           Amount of detail in build-time console messages.
                        may be one of TRACE, DEBUG, INFO, WARN, ERROR,
                        CRITICAL (default: WARN)
  --clean               Delete all folders created by this bundler and exit.
```
