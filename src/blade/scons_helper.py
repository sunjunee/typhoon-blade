# Copyright (c) 2011 Tencent Inc.
# All rights reserved.
#
# Author: Huan Yu <huanyu@tencent.com>
#         Feng Chen <phongchen@tencent.com>
#         Yi Wang <yiwang@tencent.com>
#         Chong Peng <michaelpeng@tencent.com>
# Date:   October 20, 2011


"""
 This is the scons rules helper module which should be
 imported by Scons script

"""


import os
import py_compile
import shutil
import signal
import socket
import stat
import string
import subprocess
import sys
import tempfile
import time
import zipfile

import SCons
import SCons.Action
import SCons.Builder
import SCons.Scanner
import SCons.Scanner.Prog

import blade_util
import console

from console import colors

# option_verbose to indicate print verbose or not
option_verbose = False


# linking tmp dir
linking_tmp_dir = ''


def generate_python_egg(target, source, env):
    setup_file = ''
    if not str(source[0]).endswith('setup.py'):
        console.warning('setup.py not existed to generate target %s, '
                        'blade will generate a default one for you' %
                        str(target[0]))
    else:
        setup_file = str(source[0])
    init_file = ''
    source_index = 2
    if not setup_file:
        source_index = 1
        init_file = str(source[0])
    else:
        init_file = str(source[1])

    init_file_dir = os.path.dirname(init_file)

    dep_source_list = []
    for s in source[source_index:]:
        dep_source_list.append(str(s))

    target_file = str(target[0])
    target_file_dir_list = target_file.split('/')
    target_profile = target_file_dir_list[0]
    target_dir = '/'.join(target_file_dir_list[0:-1])

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    if setup_file:
        shutil.copyfile(setup_file, os.path.join(target_dir, 'setup.py'))
    else:
        target_name = os.path.basename(init_file_dir)
        if not target_name:
            console.error_exit('invalid package for target %s' % str(target[0]))
        # generate default setup.py for user
        setup_str = """
#!/usr/bin/env python
# This file was generated by blade

from setuptools import find_packages, setup


setup(
      name='%s',
      version='0.1.0',
      packages=find_packages(),
      zip_safe=True
)
""" % target_name
        default_setup_file = open(os.path.join(target_dir, 'setup.py'), 'w')
        default_setup_file.write(setup_str)
        default_setup_file.close()

    package_dir = os.path.join(target_profile, init_file_dir)
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir, ignore_errors=True)

    cmd = 'cp -r %s %s' % (init_file_dir, target_dir)
    p = subprocess.Popen(
            cmd,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True)
    std_out, std_err = p.communicate()
    if p.returncode:
        console.info(std_out)
        console.info(std_err)
        console.error_exit('failed to copy source files from %s to %s' % (
                   init_file_dir, target_dir))
        return p.returncode

    # copy file to package_dir
    for f in dep_source_list:
        dep_file_basename = os.path.basename(f)
        dep_file_dir = os.path.dirname(f)
        sub_dir = ''
        sub_dir_list = dep_file_dir.split('/')
        if len(sub_dir_list) > 1:
            sub_dir = '/'.join(dep_file_dir.split('/')[1:])
        if sub_dir:
            package_sub_dir = os.path.join(package_dir, sub_dir)
            if not os.path.exists(package_sub_dir):
                os.makedirs(package_sub_dir)
            sub_init_file = os.path.join(package_sub_dir, '__init__.py')
            if not os.path.exists(sub_init_file):
                sub_f = open(sub_init_file, 'w')
                sub_f.close()
            shutil.copyfile(f, os.path.join(package_sub_dir, dep_file_basename))

    make_egg_cmd = 'python setup.py bdist_egg'
    p = subprocess.Popen(
            make_egg_cmd,
            env={},
            cwd=target_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True)
    std_out, std_err = p.communicate()
    if p.returncode:
        console.info(std_out)
        console.info(std_err)
        console.error_exit('failed to generate python egg in %s' % target_dir)
        return p.returncode
    return 0


def _compile_python(src, build_dir):
    if src.startswith(build_dir):
        pyc = src + 'c'
    else:
        pyc = os.path.join(build_dir, src) + 'c'
    py_compile.compile(src, pyc)
    return pyc


def generate_python_library(target, source, env):
    target_file = open(str(target[0]), 'w')
    data = dict()
    data['base_dir'] = env.get('BASE_DIR', '')
    build_dir = env['BUILD_DIR']
    srcs = []
    for s in source:
        src = str(s)
        _compile_python(src, build_dir)
        srcs.append(src)
    data['srcs'] = srcs
    target_file.write(str(data))
    target_file.close()


def _update_init_py_dirs(arcname, dirs, dirs_with_init_py):
    dir = os.path.dirname(arcname)
    if os.path.basename(arcname) == '__init__.py':
        dirs_with_init_py.add(dir)
    while dir:
        dirs.add(dir)
        dir = os.path.dirname(dir)


def generate_python_binary(target, source, env):
    """The action for generate python executable file"""
    target_name = str(target[0])
    build_dir = env['BUILD_DIR']
    target_file = zipfile.ZipFile(target_name, 'w', zipfile.ZIP_DEFLATED)
    dirs = set()
    dirs_with_init_py = set()
    for s in source:
        src = str(s)
        if src.endswith('.pylib'):
            libfile = open(src)
            data = eval(libfile.read())
            libfile.close()
            base_dir = data['base_dir']
            for libsrc in data['srcs']:
                arcname = os.path.relpath(libsrc, base_dir)
                _update_init_py_dirs(arcname, dirs, dirs_with_init_py)
                target_file.write(libsrc, arcname)
        else:
            _compile_python(src, build_dir)
            _update_init_py_dirs(src, dirs, dirs_with_init_py)
            target_file.write(src)

    # insert __init__.py into each dir if missing
    dirs_missing_init_py = dirs - dirs_with_init_py
    for dir in dirs_missing_init_py:
        target_file.writestr(os.path.join(dir, '__init__.py'), '')
    target_file.writestr('__init__.py', '')
    target_file.close()

    target_file = open(target_name, 'rb')
    zip_content = target_file.read()
    target_file.close()

    # Insert bootstrap before zip, it is also a valid zip file.
    # unzip will seek actually start until meet the zip magic number.
    entry = env['ENTRY']
    bootstrap = (
        '#!/bin/sh\n'
        '\n'
        'PYTHONPATH="$0:$PYTHONPATH" exec python -m "%s" "$@"\n') % entry
    target_file = open(target_name, 'wb')
    target_file.write(bootstrap)
    target_file.write(zip_content)
    target_file.close()
    os.chmod(target_name, 0775)


def generate_resource_index(target, source, env):
    res_source_path = str(target[0])
    res_header_path = str(target[1])

    if not os.path.exists(os.path.dirname(res_header_path)):
        os.mkdir(os.path.dirname(res_header_path))
    h = open(res_header_path, 'w')
    c = open(res_source_path, 'w')

    source_path = env["SOURCE_PATH"]
    full_name = blade_util.regular_variable_name("%s/%s" % (source_path, env["TARGET_NAME"]))
    guard_name = 'BLADE_RESOURCE_%s_H' % full_name.upper()
    print >>h, '#ifndef %s\n#define %s' % (guard_name, guard_name)
    print >>h, '''
// This file was automatically generated by blade

#ifdef __cplusplus
extern "C" {
#endif

#ifndef BLADE_RESOURCE_TYPE_DEFINED
#define BLADE_RESOURCE_TYPE_DEFINED
struct BladeResourceEntry {
    const char* name;
    const char* data;
    unsigned int size;
};
#endif
'''
    res_index_name = 'RESOURCE_INDEX_%s' % full_name
    print >>c, '// This file was automatically generated by blade\n'
    print >>c, '#include "%s"\n' % res_header_path
    print >>c, 'const struct BladeResourceEntry %s[] = {' % res_index_name
    for s in source:
        src = str(s)
        var_name = blade_util.regular_variable_name(src)
        org_src = blade_util.relative_path(src, source_path)
        print >>h, '// %s' % org_src
        print >>h, 'extern const char RESOURCE_%s[%d];' % (var_name, s.get_size())
        print >>h, 'extern const unsigned RESOURCE_%s_len;\n' % var_name
        print >>c, '    { "%s", RESOURCE_%s, %s },' % (org_src, var_name, s.get_size())
    print >>c, '};'
    print >>c, 'const unsigned %s_len = %s;' % (res_index_name, len(source))
    print >>h, '// Resource index'
    print >>h, 'extern const struct BladeResourceEntry %s[];' % res_index_name
    print >>h, 'extern const unsigned %s_len;' % res_index_name
    print >>h, '\n#ifdef __cplusplus\n} // extern "C"\n#endif\n'
    print >>h, '\n#endif // %s' % guard_name
    c.close()
    h.close()


def generate_resource_file(target, source, env):
    src_path = str(source[0])
    new_src_path = str(target[0])
    cmd = ('xxd -i %s | sed -e "s/^unsigned char /const char RESOURCE_/g" '
           '-e "s/^unsigned int /const unsigned int RESOURCE_/g"> %s') % (
           src_path, new_src_path)
    p = subprocess.Popen(
            cmd,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True)
    stdout, stderr = p.communicate()
    if p.returncode or stderr:
        error = 'failed to generate resource file'
        if stderr:
            error = error + ': ' + stderr
        console.error_exit(error)
    return p.returncode


def MakeAction(cmd, cmdstr):
    global option_verbose
    if option_verbose:
        return SCons.Action.Action(cmd)
    else:
        return SCons.Action.Action(cmd, cmdstr)


_ERRORS = [': error:', ': fatal error:', ': undefined reference to',
           ': cannot find ', ': ld returned 1 exit status',
           ' is not defined'
           ]
_WARNINGS = [': warning:', ': note: ', '] Warning: ']


def error_colorize(message):
    colored_message = []
    for line in message.splitlines(True): # keepends
        color = 'cyan'

        # For clang column indicator, such as '^~~~~~'
        if line.strip().startswith('^'):
            color = 'green'
        else:
            for w in _WARNINGS:
                if w in line:
                    color = 'yellow'
                    break
            for w in _ERRORS:
                if w in line:
                    color = 'red'
                    break

        colored_message.append(console.colors(color))
        colored_message.append(line)
        colored_message.append(console.colors('end'))
    return console.inerasable(''.join(colored_message))


def _colored_echo(stdout, stderr):
    """Echo error colored message"""
    if stdout:
        sys.stdout.write(error_colorize(stdout))
    if stderr:
        sys.stderr.write(error_colorize(stderr))


def echospawn(sh, escape, cmd, args, env):
    # convert env from unicode strings
    asciienv = {}
    for key, value in env.iteritems():
        asciienv[key] = str(value)

    cmdline = ' '.join(args)
    p = subprocess.Popen(
        cmdline,
        env=asciienv,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        shell=True,
        universal_newlines=True)
    (stdout, stderr) = p.communicate()

    if p.returncode:
        if p.returncode != -signal.SIGINT:
            # Error
            _colored_echo(stdout, stderr)
    else:
        # Only warnings
        _colored_echo(stdout, stderr)

    return p.returncode


def _blade_action_postfunc(closing_message):
    """To do post jobs if blade's own actions failed to build. """
    console.info(closing_message)
    # Remember to write the dblite incase of re-linking once fail to
    # build last time. We should elaborate a way to avoid rebuilding
    # after failure of our own builders or actions.
    SCons.SConsign.write()


def _fast_link_helper(target, source, env, link_com):
    """fast link helper function. """
    target_file = str(target[0])
    prefix_str = 'blade_%s' % target_file.replace('/', '_').replace('.', '_')
    fd, temporary_file = tempfile.mkstemp(suffix='xianxian',
                                          prefix=prefix_str,
                                          dir=linking_tmp_dir)
    os.close(fd)

    sources = []
    for s in source:
        sources.append(str(s))

    link_com_str = link_com.substitute(
                   FL_TARGET=temporary_file,
                   FL_SOURCE=' '.join(sources))
    p = subprocess.Popen(
                        link_com_str,
                        env=os.environ,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True,
                        universal_newlines=True)
    std_out, std_err = p.communicate()
    if std_out:
        print std_out
    if std_err:
        print std_err
    if p.returncode == 0:
        shutil.move(temporary_file, target_file)
        if not os.path.exists(target_file):
            console.warning('failed to genreate %s in link on tmpfs mode' % target_file)
    else:
        _blade_action_postfunc('failed while fast linking')
        return p.returncode


def fast_link_sharelib_action(target, source, env):
    # $SHLINK -o $TARGET $SHLINKFLAGS $__RPATH $SOURCES $_LIBDIRFLAGS $_LIBFLAGS
    link_com = string.Template('%s -o $FL_TARGET %s %s $FL_SOURCE %s %s' % (
                env.subst('$SHLINK'),
                env.subst('$SHLINKFLAGS'),
                env.subst('$__RPATH'),
                env.subst('$_LIBDIRFLAGS'),
                env.subst('$_LIBFLAGS')))
    return _fast_link_helper(target, source, env, link_com)


def fast_link_prog_action(target, source, env):
    # $LINK -o $TARGET $LINKFLAGS $__RPATH $SOURCES $_LIBDIRFLAGS $_LIBFLAGS
    link_com = string.Template('%s -o $FL_TARGET %s %s $FL_SOURCE %s %s' % (
                env.subst('$LINK'),
                env.subst('$LINKFLAGS'),
                env.subst('$__RPATH'),
                env.subst('$_LIBDIRFLAGS'),
                env.subst('$_LIBFLAGS')))
    return _fast_link_helper(target, source, env, link_com)


def setup_fast_link_prog_builder(top_env):
    """
       This is the function to setup blade fast link
       program builder. It will overwrite the program
       builder of top level env if user specifies an
       option to apply fast link method that they want
       to place the blade output to distributed file
       system to advoid the random read write of linker
       largely degrades building performance.
    """
    new_link_action = MakeAction(fast_link_prog_action, '$LINKCOMSTR')
    program = SCons.Builder.Builder(action=new_link_action,
                                    emitter='$PROGEMITTER',
                                    prefix='$PROGPREFIX',
                                    suffix='$PROGSUFFIX',
                                    src_suffix='$OBJSUFFIX',
                                    src_builder='Object',
                                    target_scanner=SCons.Scanner.Prog.ProgramScanner())
    top_env['BUILDERS']['Program'] = program


def setup_fast_link_sharelib_builder(top_env):
    """
       This is the function to setup blade fast link
       sharelib builder. It will overwrite the sharelib
       builder of top level env if user specifies an
       option to apply fast link method that they want
       to place the blade output to distributed file
       system to advoid the random read write of linker
       largely degrades building performance.
    """
    new_link_actions = []
    new_link_actions.append(SCons.Defaults.SharedCheck)
    new_link_actions.append(MakeAction(fast_link_sharelib_action, '$SHLINKCOMSTR'))

    sharedlib = SCons.Builder.Builder(action=new_link_actions,
                                      emitter='$SHLIBEMITTER',
                                      prefix='$SHLIBPREFIX',
                                      suffix='$SHLIBSUFFIX',
                                      target_scanner=SCons.Scanner.Prog.ProgramScanner(),
                                      src_suffix='$SHOBJSUFFIX',
                                      src_builder='SharedObject')
    top_env['BUILDERS']['SharedLibrary'] = sharedlib


def setup_fast_link_builders(top_env):
    """Creates fast link builders - Program and  SharedLibrary. """
    # Check requirement
    acquire_temp_place = "df | grep tmpfs | awk '{print $5, $6}'"
    p = subprocess.Popen(
                        acquire_temp_place,
                        env=os.environ,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True,
                        universal_newlines=True)
    stdout, stderr = p.communicate()

    # Do not try to overwrite builder with error
    if p.returncode:
        console.warning('you have link on tmp enabled, but it is not fullfilled to make it.')
        return

    # No tmpfs to do fastlink, will not overwrite the builder
    if not stdout:
        console.warning('you have link on tmp enabled, but there is no tmpfs to make it.')
        return

    # Use the first one
    global linking_tmp_dir
    usage, linking_tmp_dir = tuple(stdout.splitlines(False)[0].split())

    # Do not try to do that if there is no memory space left
    usage = int(usage.replace('%', ''))
    if usage > 90:
        console.warning('you have link on tmp enabled, '
                        'but there is not enough space on %s to make it.' %
                        linking_tmp_dir)
        return

    console.info('building in link on tmpfs mode')

    setup_fast_link_sharelib_builder(top_env)
    setup_fast_link_prog_builder(top_env)


def make_top_env(build_dir):
    """Make the top level scons envrionment object"""
    os.environ['LC_ALL'] = 'C'
    top_env = SCons.Environment.Environment(ENV=os.environ)
    # Optimization options, see http://www.scons.org/wiki/GoFastButton
    top_env.Decider('MD5-timestamp')
    top_env.SetOption('implicit_cache', 1)
    top_env.SetOption('max_drift', 1)
    top_env.VariantDir(build_dir, '.', duplicate=0)
    return top_env


def get_compile_source_message():
    return console.erasable('%sCompiling %s$SOURCE%s%s' % (
        colors('cyan'), colors('purple'), colors('cyan'), colors('end')))


def get_link_program_message():
    return console.inerasable('%sLinking Program %s$TARGET%s%s' % (
        colors('green'), colors('purple'), colors('green'), colors('end')))


def setup_compliation_verbose(top_env, color_enabled, verbose):
    """Generates color and verbose message. """
    console.color_enabled = color_enabled

    if not verbose:
        top_env["SPAWN"] = echospawn

    compile_source_message = get_compile_source_message()
    link_program_message = get_link_program_message()
    assembling_source_message = console.erasable('%sAssembling %s$SOURCE%s%s' % (
        colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    link_library_message = console.inerasable('%sCreating Static Library %s$TARGET%s%s' % (
        colors('green'), colors('purple'), colors('green'), colors('end')))
    ranlib_library_message = console.inerasable('%sRanlib Library %s$TARGET%s%s' % (
        colors('green'), colors('purple'), colors('green'), colors('end')))
    link_shared_library_message = console.inerasable('%sLinking Shared Library %s$TARGET%s%s' % (
        colors('green'), colors('purple'), colors('green'), colors('end')))
    jar_message = console.inerasable('%sCreating Jar %s$TARGET%s%s' % (
        colors('green'), colors('purple'), colors('green'), colors('end')))

    if not verbose:
        top_env.Append(
                CXXCOMSTR = compile_source_message,
                CCCOMSTR = compile_source_message,
                ASCOMSTR = assembling_source_message,
                SHCCCOMSTR = compile_source_message,
                SHCXXCOMSTR = compile_source_message,
                ARCOMSTR = link_library_message,
                RANLIBCOMSTR = ranlib_library_message,
                SHLINKCOMSTR = link_shared_library_message,
                LINKCOMSTR = link_program_message,
                JAVACCOMSTR = compile_source_message,
                JARCOMSTR = jar_message,
                LEXCOMSTR = compile_source_message)


def setup_proto_builders(top_env, build_dir, protoc_bin, protobuf_path,
                         protobuf_incs_str,
                         protoc_php_plugin, protobuf_php_path):
    compile_proto_cc_message = console.erasable('%sCompiling %s$SOURCE%s to cc source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_proto_java_message = console.erasable('%sCompiling %s$SOURCE%s to java source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_proto_php_message = console.erasable('%sCompiling %s$SOURCE%s to php source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_proto_python_message = console.erasable('%sCompiling %s$SOURCE%s to python source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    proto_bld = SCons.Builder.Builder(action = MakeAction(
        "%s --proto_path=. -I. %s -I=`dirname $SOURCE` --cpp_out=%s $SOURCE" % (
            protoc_bin, protobuf_incs_str, build_dir),
        compile_proto_cc_message))
    top_env.Append(BUILDERS = {"Proto" : proto_bld})

    proto_java_bld = SCons.Builder.Builder(action = MakeAction(
        "%s --proto_path=. --proto_path=%s --java_out=%s/`dirname $SOURCE` $SOURCE" % (
            protoc_bin, protobuf_path, build_dir),
        compile_proto_java_message))
    top_env.Append(BUILDERS = {"ProtoJava" : proto_java_bld})

    proto_php_bld = SCons.Builder.Builder(action = MakeAction(
        "%s --proto_path=. --plugin=protoc-gen-php=%s -I. %s -I%s -I=`dirname $SOURCE` --php_out=%s/`dirname $SOURCE` $SOURCE" % (
            protoc_bin, protoc_php_plugin, protobuf_incs_str, protobuf_php_path, build_dir),
        compile_proto_php_message))
    top_env.Append(BUILDERS = {"ProtoPhp" : proto_php_bld})

    proto_python_bld = SCons.Builder.Builder(action = MakeAction(
        "%s --proto_path=. -I. %s -I=`dirname $SOURCE` --python_out=%s $SOURCE" % (
            protoc_bin, protobuf_incs_str, build_dir),
        compile_proto_python_message))
    top_env.Append(BUILDERS = {"ProtoPython" : proto_python_bld})


def setup_thrift_builders(top_env, build_dir, thrift_bin, thrift_incs_str):
    compile_thrift_cc_message = console.erasable('%sCompiling %s$SOURCE%s to cc source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_thrift_java_message = console.erasable('%sCompiling %s$SOURCE%s to java source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_thrift_python_message = console.erasable( '%sCompiling %s$SOURCE%s to python source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    thrift_bld = SCons.Builder.Builder(action = MakeAction(
        '%s --gen cpp:include_prefix,pure_enums -I . %s -I `dirname $SOURCE`'
        ' -out %s/`dirname $SOURCE` $SOURCE' % (
            thrift_bin, thrift_incs_str, build_dir),
        compile_thrift_cc_message))
    top_env.Append(BUILDERS = {"Thrift" : thrift_bld})

    thrift_java_bld = SCons.Builder.Builder(action = MakeAction(
    "%s --gen java -I . %s -I `dirname $SOURCE` -out %s/`dirname $SOURCE` $SOURCE" % (
        thrift_bin, thrift_incs_str, build_dir),
    compile_thrift_java_message))
    top_env.Append(BUILDERS = {"ThriftJava" : thrift_java_bld})

    thrift_python_bld = SCons.Builder.Builder(action = MakeAction(
        "%s --gen py -I . %s -I `dirname $SOURCE` -out %s/`dirname $SOURCE` $SOURCE" % (
            thrift_bin, thrift_incs_str, build_dir),
        compile_thrift_python_message))
    top_env.Append(BUILDERS = {"ThriftPython" : thrift_python_bld})


def setup_fbthrift_builders(top_env, build_dir, fbthrift1_bin, fbthrift2_bin, fbthrift_incs_str):
    compile_fbthrift_cpp_message = console.erasable('%sCompiling %s$SOURCE%s to cpp source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    compile_fbthrift_cpp2_message = console.erasable('%sCompiling %s$SOURCE%s to cpp2 source%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    fbthrift1_bld = SCons.Builder.Builder(action = MakeAction(
        '%s --gen cpp:templates,cob_style,include_prefix,enum_strict -I . %s -I `dirname $SOURCE`'
        ' -o %s/`dirname $SOURCE` $SOURCE' % (
            fbthrift1_bin, fbthrift_incs_str, build_dir),
        compile_fbthrift_cpp_message))
    top_env.Append(BUILDERS = {"FBThrift1" : fbthrift1_bld})

    fbthrift2_bld = SCons.Builder.Builder(action = MakeAction(
        '%s --gen=cpp2:cob_style,include_prefix,future -I . %s -I `dirname $SOURCE` '
        '-o %s/`dirname $SOURCE` $SOURCE' % (
            fbthrift2_bin, fbthrift_incs_str, build_dir),
        compile_fbthrift_cpp2_message))
    top_env.Append(BUILDERS = {"FBThrift2" : fbthrift2_bld})


def setup_cuda_builders(top_env, nvcc_str, cuda_incs_str):
    nvcc_object_bld = SCons.Builder.Builder(action = MakeAction(
        "%s -ccbin g++ %s $NVCCFLAGS -o $TARGET -c $SOURCE" % (nvcc_str, cuda_incs_str),
        get_compile_source_message()))
    top_env.Append(BUILDERS = {"NvccObject" : nvcc_object_bld})

    nvcc_binary_bld = SCons.Builder.Builder(action = MakeAction(
        "%s %s $NVCCFLAGS -o $TARGET" % (nvcc_str, cuda_incs_str),
        get_link_program_message()))
    top_env.Append(NVCC=nvcc_str)
    top_env.Append(BUILDERS = {"NvccBinary" : nvcc_binary_bld})


def setup_jar_builders(top_env):
    compile_java_jar_message = console.inerasable('%sGenerating java jar %s$TARGET%s%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    blade_jar_bld = SCons.Builder.Builder(action = MakeAction(
        'jar cf $TARGET -C `dirname $SOURCE` .',
        compile_java_jar_message))
    top_env.Append(BUILDERS = {"BladeJar" : blade_jar_bld})


def setup_yacc_builders(top_env):
    compile_yacc_message = console.erasable('%sYacc %s$SOURCE%s to $TARGET%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    yacc_bld = SCons.Builder.Builder(action = MakeAction(
        'bison $YACCFLAGS -d -o $TARGET $SOURCE',
        compile_yacc_message))
    top_env.Append(BUILDERS = {"Yacc" : yacc_bld})


def setup_resource_builders(top_env):
    compile_resource_index_message = console.erasable('%sGenerating resource index for %s$SOURCE_PATH/$TARGET_NAME%s%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    compile_resource_message = console.erasable('%sCompiling %s$SOURCE%s as resource file%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    resource_index_bld = SCons.Builder.Builder(action = MakeAction(generate_resource_index,
        compile_resource_index_message))
    resource_file_bld = SCons.Builder.Builder(action = MakeAction(generate_resource_file,
        compile_resource_message))
    top_env.Append(BUILDERS = {"ResourceIndex" : resource_index_bld})
    top_env.Append(BUILDERS = {"ResourceFile" : resource_file_bld})


def setup_python_builders(top_env):
    compile_python_egg_message = console.erasable('%sGenerating python egg %s$TARGET%s%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    compile_python_library_message = console.erasable('%sGenerating python library %s$TARGET%s%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))
    compile_python_binary_message = console.inerasable('%sGenerating python binary %s$TARGET%s%s' % \
        (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    python_egg_bld = SCons.Builder.Builder(action = MakeAction(generate_python_egg,
        compile_python_egg_message))
    python_library_bld = SCons.Builder.Builder(action = MakeAction(generate_python_library,
        compile_python_library_message))
    python_binary_bld = SCons.Builder.Builder(action = MakeAction(generate_python_binary,
        compile_python_binary_message))
    top_env.Append(BUILDERS = {"PythonEgg" : python_egg_bld})
    top_env.Append(BUILDERS = {"PythonLibrary" : python_library_bld})
    top_env.Append(BUILDERS = {"PythonBinary" : python_binary_bld})


def setup_other_builders(top_env):
    setup_jar_builders(top_env)
    setup_yacc_builders(top_env)
    setup_resource_builders(top_env)
    setup_python_builders(top_env)


def setup_swig_builders(top_env, build_dir):
    compile_swig_python_message = console.erasable('%sCompiling %s$SOURCE%s to python source%s' % \
            (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_swig_java_message = console.erasable('%sCompiling %s$SOURCE%s to java source%s' % \
            (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    compile_swig_php_message = console.erasable('%sCompiling %s$SOURCE%s to php source%s' % \
            (colors('cyan'), colors('purple'), colors('cyan'), colors('end')))

    # Python
    swig_py_bld = SCons.Builder.Builder(action=MakeAction(
        'swig -python -threads $SWIGPYTHONFLAGS -c++ -I%s -o $TARGET $SOURCE' % (build_dir),
        compile_swig_python_message))
    top_env.Append(BUILDERS={"SwigPython" : swig_py_bld})

    # Java
    swig_java_bld = SCons.Builder.Builder(action=MakeAction(
        'swig -java $SWIGJAVAFLAGS -c++ -I%s -o $TARGET $SOURCE' % (build_dir),
        compile_swig_java_message))
    top_env.Append(BUILDERS={'SwigJava' : swig_java_bld})

    swig_php_bld = SCons.Builder.Builder(action=MakeAction(
        'swig -php $SWIGPHPFLAGS -c++ -I%s -o $TARGET $SOURCE' % (build_dir),
        compile_swig_php_message))
    top_env.Append(BUILDERS={"SwigPhp" : swig_php_bld})


def _exec_get_version_info(cmd, cwd, dirname):
    lc_all_env = os.environ
    lc_all_env['LC_ALL'] = 'POSIX'
    p = subprocess.Popen(cmd,
                         env=lc_all_env,
                         cwd=cwd,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         shell=True)
    stdout, stderr = p.communicate()
    if p.returncode:
        return None
    else:
        return stdout.replace('\n', '\\n\\\n')


def _get_version_info(blade_root_dir, svn_roots):
    """Gets svn root dir info. """
    svn_info_map = {}
    if os.path.exists("%s/.git" % blade_root_dir):
        cmd = "git log -n 1"
        dirname = os.path.dirname(blade_root_dir)
        version_info = _exec_get_version_info(cmd, None, dirname)
        if version_info:
            svn_info_map[dirname] = version_info
        return svn_info_map

    for root_dir in svn_roots:
        root_dir_realpath = os.path.realpath(root_dir)
        svn_working_dir = os.path.dirname(root_dir_realpath)
        svn_dir = os.path.basename(root_dir_realpath)

        cmd = 'svn info %s' % svn_dir
        cwd = svn_working_dir
        version_info = _exec_get_version_info(cmd, cwd, root_dir)
        if not version_info:
            cmd = 'git ls-remote --get-url && git branch | grep "*" && git log -n 1'
            cwd = root_dir_realpath
            version_info = _exec_get_version_info(cmd, cwd, root_dir)
            if not version_info:
                console.warning('failed to get version control info in %s' % root_dir)
                continue
            svn_info_map[root_dir] = version_info

    return svn_info_map

def generate_version_file(top_env, blade_root_dir, build_dir,
                          profile, gcc_version, svn_roots):
    """Generate version information files. """
    svn_info_map = _get_version_info(blade_root_dir, svn_roots)
    svn_info_len = len(svn_info_map)

    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    filename = '%s/version.cpp' % build_dir
    version_cpp = open(filename, 'w')

    print >>version_cpp, '/* This file was generated by blade */'
    print >>version_cpp, 'extern "C" {'
    print >>version_cpp, 'namespace binary_version {'
    print >>version_cpp, 'extern const int kSvnInfoCount = %d;' % svn_info_len

    svn_info_array = '{'
    for idx in range(svn_info_len):
        key_with_idx = svn_info_map.keys()[idx]
        svn_info_line = '"%s"' % svn_info_map[key_with_idx]
        svn_info_array += svn_info_line
        if idx != (svn_info_len - 1):
            svn_info_array += ','
    svn_info_array += '}'

    print >>version_cpp, 'extern const char* const kSvnInfo[%d] = %s;' % (
            svn_info_len, svn_info_array)
    print >>version_cpp, 'extern const char kBuildType[] = "%s";' % profile
    print >>version_cpp, 'extern const char kBuildTime[] = "%s";' % time.asctime()
    print >>version_cpp, 'extern const char kBuilderName[] = "%s";' % os.getenv('USER')
    print >>version_cpp, (
            'extern const char kHostName[] = "%s";' % socket.gethostname())
    compiler = 'GCC %s' % gcc_version
    print >>version_cpp, 'extern const char kCompiler[] = "%s";' % compiler
    print >>version_cpp, '}}'

    version_cpp.close()

    env_version = top_env.Clone()
    env_version.Replace(SHCXXCOMSTR=console.erasable(
        '%sUpdating version information%s' % (
            colors('cyan'), colors('end'))))
    return env_version.SharedObject(filename)
