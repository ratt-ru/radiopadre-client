import os, sys, subprocess, re, time, traceback, shlex, asyncio, signal
from dataclasses import dataclass
from typing import Optional, Any
import getpass, secrets, grp, pwd, json, yaml, uuid
import rich

import kubernetes
from kubernetes.client.api import core_v1_api
from kubernetes.client.rest import ApiException
from requests import ConnectionError
from urllib3.exceptions import HTTPError, ReadTimeoutError


from . import config

import iglesia
from iglesia.utils import DEVNULL, message, warning, error, debug, bye, find_unused_port, Poller, INPUT, find_which
from iglesia.helpers import NUM_PORTS

from radiopadre_client.server import run_browser

config.SESSION_ID = uuid.uuid4().hex
session_user = getpass.getuser()

resource_labels = dict(radiopadre_user=session_user,
                       radiopadre_session_id=config.SESSION_ID)


# borrows from stimela2
@dataclass 
class UserInfo(object):
    # user and group names and IDs -- if None, use local user
    name:           Optional[str] = None
    group:          Optional[str] = None
    uid:            Optional[int] = None
    gid:            Optional[int] = None
    gecos:          Optional[str] = None
    home:           Optional[str] = None     # home dir inside container, default is /home/{user}
    home_ramdisk:   bool = True              # home dir mounted as RAM disk, else local disk
    inject_nss:     bool = True              # inject user info for NSS_WRAPPER

_uid = os.getuid()
_gid = os.getgid()

# Find remote radiopadre script
def run_k8s_session(pvc_name, notebook_path, extra_arguments):

    kubectl = find_which("kubectl")
    if not kubectl:
        error("kubectl binary not found")
        return 1

    status = 0
    k8s_context = config.K8S_CONTEXT or None

    if k8s_context:
        message(f"loading k8s config for context '{k8s_context}'")
    else:
        message(f"loading k8s config for default context")

    kubernetes.config.load_kube_config(context=k8s_context)
    contexts = kubernetes.config.list_kube_config_contexts()
    all_contexts = {c['name']: c['context'] for c in contexts[0]} 
    if k8s_context:
        ctx = all_contexts[k8s_context]
    else:
        k8s_context = contexts[1]['name']
        ctx = contexts[1]['context']

    message(f"using k8s context '{k8s_context}': {' '.join(f'{key}={value}' for key, value in ctx.items())}")

    k8s_namespace = ctx.get('namespace', None) or config.K8S_NAMESPACE
    if not k8s_namespace:
        error(f"no default k8s namespace configured by the '{name}' context, and --k8s-namespace is not given")
        return 1
    
    # setup nodeSelector
    nodeSel = {}
    for keyval in config.K8S_NODE_SELECTOR.split(","):
        if keyval:
            if "=" in keyval:
                key, value = keyval.split("=")
                nodeSel[key] = value
            else:
                error(f"invalid --k8s-node-selector setting: {keyval}")
                return 1

    kube_api = core_v1_api.CoreV1Api()

    # setup user info
    uinfo = UserInfo(
        name=session_user,
        group=grp.getgrgid(_gid).gr_name,
        uid=_uid,
        gid=_gid,
        home=f"/home/{session_user}",
        gecos=pwd.getpwuid(_uid).pw_gecos
    )
    if config.K8S_UID >= 0:
        uinfo.uid = config.K8S_UID
    if config.K8S_GID >= 0:
        uinfo.gid = config.K8S_GID
    radiopadre_dir = os.path.join(uinfo.home, ".radiopadre")

    # check for pods to be cleaned up
    try:
        pods = kube_api.list_namespaced_pod(namespace=k8s_namespace, 
                                            label_selector=f"radiopadre_user={session_user}")
    except ApiException as exc:
        body = json.loads(exc.body)
        traceback.print_exc()
        error(f"k8s API error checking for pods: {body}")
        return 1
    
    running_pods = []
    for pod in pods.items:
        if pod.status.phase in ("Running", "Pending") and not pod.metadata.deletion_timestamp:
            running_pods.append(pod.metadata.name)

    if running_pods:
        warning(f"you have {len(running_pods)} radiopadre pod(s) pending or running")
        if config.K8S_AUTO_CLEANUP:
            for podname in running_pods:
                warning(f"deleting pod {podname}")
                try:
                    resp = kube_api.delete_namespaced_pod(name=podname, namespace=k8s_namespace)
                except ApiException as exc:
                    body = json.loads(exc.body)
                    traceback.print_exc()
                    error(f"k8s API error deleting pod: {body}")
                    return 1

    has_ext = os.path.split(notebook_path)[1]
    if has_ext:
        notebook_dir = os.path.dirname(notebook_path)
    else:
        notebook_dir = notebook_path
    notebook_path = "/mnt/" + notebook_path
    if not notebook_dir or notebook_dir == "/":
        notebook_dir = "."

    # allocate suggested ports 
    starting_port = 10000 + os.getuid() * 3
    ports = []
    for _ in range(NUM_PORTS):
        starting_port = find_unused_port(starting_port + 1, 10000)
        ports.append(starting_port)
    iglesia.set_userside_ports(ports)

    # propagate our config to command-line arguments
    runner_config = config.get_config_dict()
    for key in list(runner_config.keys()):
        if key.startswith("K8S"):
            del runner_config[key]

    runner_config['BROWSER'] = 'None'
    runner_config['SKIP_CHECKS'] = False
    runner_config['BACKEND'] = "venv"
    runner_config['VENV_REINSTALL'] = False
    runner_config['INSIDE_CONTAINER'] = ':'.join(map(str,list(ports) + list(ports)))
    del runner_config['REMOTE_HOP']
    del runner_config['REMOTE_PORT']

    # create pod spec
    podname = f"{session_user}-padre-server-{config.SESSION_ID}"
    pod_created = None
    urls = []
    aux_processes = {}
    _connected = True
    reported_events = set()

    # accumulate volume specs for 
    # - directory of interest
    # - home directory (needed by many tools)
    # - [optional] radiopadre cache directory
    volumes = [dict(name="data"), dict(name="home")]
    volumeMounts = [
        dict(name = "data",
            mountPath = os.path.join("/mnt", notebook_dir)),
        dict(name = "home",
            mountPath = uinfo.home)
    ]
    if notebook_dir != ".":
        volumeMounts[0]['subPath'] = notebook_dir.lstrip("/") 

    def _configure_volume(volume, pvc_name):
        # figure out dir of interest: could be hostpath, could be a PVC
        if pvc_name.startswith("/"):
            volume["hostPath"] = dict(path=pvc_name) 
        else:
            volume["persistentVolumeClaim"] = dict(claimName=pvc_name) 

    _configure_volume(volumes[0], pvc_name)
    # figure out home directory -- mounted from PVC, or an empty directory
    home_pvc = None
    if config.K8S_HOME_DIR:
        if ":" in config.K8S_HOME_DIR:
            home_pvc, home_subpath = config.K8S_HOME_DIR.split(":")
            _configure_volume(volumes[1], home_pvc)
            volumeMounts[1]["subPath"] = home_subpath.lstrip("/")
        elif config.K8S_HOME_DIR.upper() == "RAM":
            volumes[1]["emptyDir"] = dict(medium="Memory")
        else:
            error(f"invalid --k8s-home-dir setting: {config.K8S_HOME_DIR}")
            return 1
    else:
        volumes[1]["emptyDir"] = {}
    # figure out radiopadre directory (will use ~/.radiopadre by default)
    if config.K8S_RADIOPADRE_DIR:
        if ":" in config.K8S_RADIOPADRE_DIR:
            rp_pvc, rp_subpath = config.K8S_RADIOPADRE_DIR.split(":")
            if rp_pvc == home_pvc:
                name = "home"
            elif rp_pvc == pvc_name:
                name = "data"
            else:
                name = "radiopadre"
                volumes.append(dict(name=name))
                _configure_volume(volumes[-1], rp_pvc)
            volumeMounts.append(dict(name="radiopadre", mountPath=radiopadre_dir, subPath=rp_subpath))
        elif config.K8S_RADIOPADRE_DIR.upper() == "RAM":
            volumes.append(dict(name="radiopadre", emptyDir=dict(medium="Memory")))
            volumeMounts.append(dict(name="radiopadre", mountPath=radiopadre_dir))
        else:
            error(f"invalid --k8s-radiopadre-dir setting: {config.K8S_RADIOPADRE_DIR}")
            return 1
        
    # configure requests
    resource_reqs = {}
    if config.K8S_CPU_REQUEST:
        resource_reqs['cpu'] = config.K8S_CPU_REQUEST
    if config.K8S_RAM_REQUEST:
        resource_reqs['memory'] = config.K8S_RAM_REQUEST

    pod_manifest = dict(
        apiVersion  =  'v1',
        kind        =  'Pod',
        metadata    = dict(name=podname, labels=resource_labels),
        spec        = dict(
            containers = [dict(
                    image   = config.DOCKER_IMAGE,
                    imagePullPolicy = 'IfNotPresent',
                    name    = "padre",
                    args    = config.get_options_list(runner_config, quote=False) + [notebook_path] + extra_arguments,
                    env     = [
                        dict(name="USER", value=uinfo.name),
                        dict(name="GROUP", value=uinfo.group),
                        dict(name="HOME", value=uinfo.home),
                        dict(name="USER_UID", value=str(uinfo.uid)),
                        dict(name="USER_GID", value=str(uinfo.gid)),
                        dict(name="USER_GECOS", value=str(uinfo.gecos)),
                        dict(name="RADIOPADRE_DIR", value=radiopadre_dir),
                        dict(name="RADIOPADRE_SESSION_ID", value=config.SESSION_ID),
                        dict(name="RADIOPADRE_CONTAINER_NAME", value=podname)
                    ],
                    securityContext = dict(
                            runAsNonRoot = uinfo.uid != 0,
                            runAsUser = uinfo.uid,
                            runAsGroup = uinfo.gid,
                    ),
                    volumeMounts = volumeMounts,
                    resources = dict(requests = resource_reqs)
            )],
            volumes = volumes,
            restartPolicy = "Never",
            nodeSelector = nodeSel
        )
    )

    ## save pod def, just for debugging
    if config.VERBOSE > 0:
        rich.print(pod_manifest)
    # open("padre-pod.yaml", "wt").write(yaml.dump(pod_manifest))

    def disconnected():
        nonlocal _connected
        if _connected:
            warning("lost connection to k8s cluster")
            warning("this is not fatal if the connection eventually resumes")
            warning("use Ctrl+C if you want to give up")
            _connected = False
        time.sleep(1)

    def connected():
        nonlocal _connected
        if not _connected:
            message("k8s connection resumed")
            _connected = True

    def check_events():
        try:
            events = kube_api.list_namespaced_event(namespace=k8s_namespace, 
                            field_selector=f"involvedObject.kind=Pod,involvedObject.name={podname}",
                            _request_timeout=(1,1))
        except ApiException as exc:
            body = exc.body and json.loads(exc.body)
            traceback.print_exc()
            error(f"k8s API error checking for events: {body}")
            return 
        except (ConnectionError, HTTPError) as exc:
            disconnected()
            return 
        connected()

        for event in events.items:
            if event.metadata.uid not in reported_events:
                reported_events.add(event.metadata.uid)
                message(f"k8s event: {event.reason}: {event.message}")

    try:
        start_time = time.time()
        provisioning_deadline = start_time + 60
        message(f"starting radiopadre pod, arguments are: {' '.join(pod_manifest['spec']['containers'][0]['args'])}")
        resp = kube_api.create_namespaced_pod(body=pod_manifest, namespace=k8s_namespace)
        pod_created = True

        retcode = None
        phase = None

        # wait for startup
        while True:
            check_events()
            try:
                resp = kube_api.read_namespaced_pod_status(name=podname, namespace=k8s_namespace,
                                                            _request_timeout=(1, 1))
            except (ConnectionError, HTTPError) as exc:
                disconnected()
                continue
            phase = resp.status.phase
            connected()
            if phase == 'Running' or phase == 'Succeeded':
                message("radiopadre pod started")
                break
            elif phase == 'Failed':
                error("pod status is failed -- will proceed to collect logs below")
                break
            waiting_time = time.time() - start_time
            if time.time() >= provisioning_deadline:
                warning(f"Still waiting for pod to start ({round(waiting_time)}s). Messages above may contain more information.")
                warning("Press Ctrl+C to give up.")
                provisioning_deadline = time.time() + 60
                continue
            time.sleep(1)

        # start port forwarders
        for port in ports:
            aux_processes[f"kubectl port-forward {port}"] = \
                subprocess.Popen([kubectl, "port-forward", podname, f"{port}:{port}"])

        # read logs
        last_log_timestamp = None
        seen_logs = set()
        while retcode is None:
            try:
                check_events()
                try:
                    entries = kube_api.read_namespaced_pod_log(name=podname, namespace=k8s_namespace, container="padre",
                                follow=True, timestamps=True,
    #                            since_time=last_log_timestamp,
                                _preload_content=False, 
                                _request_timeout=(5, 5)
                            ).stream()
                    for entry in entries:
                        # log.info(f"got [blue]{entry.decode()}[/blue]")
                        for line in entry.decode().rstrip().split("\n"):
                            if " " in line:
                                timestamp, content = line.split(" ", 1)
                            else:
                                timestamp, content = line, ""
                            key = timestamp, hash(content)
                            last_log_timestamp = timestamp
                            if key in seen_logs:
                                continue
                            seen_logs.add(key)
                            message(f"# {content}")
                            # parse for reactions

                            # check for launch URL
                            match = re.match(".*Browse to URL: ([^\s\033]+)", content)
                            if match:
                                urls.append(match.group(1))
                                continue

                            if "jupyter notebook server is running" in content:
                                time.sleep(1)
                                if urls:
                                    iglesia.register_helpers(*run_browser(*urls))
                                message("The remote radiopadre session is now fully up")
                                message("Press Ctrl+C to kill the remote session")

                except ReadTimeoutError as exc:  # not fatal, just means no logs coming
                    continue
            
                # check for return code
                resp = kube_api.read_namespaced_pod_status(name=podname, namespace=k8s_namespace)
                connected()
                contstat = resp.status.container_statuses[0].state
                waiting = contstat.waiting
                running = contstat.running
                terminated = contstat.terminated
                if waiting:
                    pass 
                    # message("container state is 'waiting'")
                elif running:
                    pass
                # message(f"container state is 'running'")
                elif terminated:
                    retcode = terminated.exit_code
                    message(f"container state is 'terminated', exit code is {retcode}")
                    break
            except (ConnectionError, HTTPError) as exc:
                traceback.print_exc()
                disconnected()


    except KeyboardInterrupt:
        message("Ctrl+C caught, will shut down radiopadre pod and exit")
    except ApiException as exc:
        body = exc.body and json.loads(exc.body)
        traceback.print_exc()
        error(f"k8s API error: {body}")
        return 1
    except Exception as exc:
        traceback.print_exc()
        error(f"Exception raised: {exc}")
        return 1
    finally:
        try:
            # pod.initiate_cleanup()
            # clean up port forwarder subprocesses
            if aux_processes:
                # see who's died
                for desc, proc in list(aux_processes.items()):
                    retcode = proc.poll()
                    if retcode is not None:
                        message(f"{desc} process has died with code {retcode}")
                        proc.wait()
                    del aux_processes[desc]
                # terminate others
                for desc, proc in list(aux_processes.items()):
                    message(f"terminating {desc} process")
                    proc.terminate()
                for desc, proc in list(aux_processes.items()):
                    try:
                        retcode = proc.wait(1)
                    except subprocess.TimeoutExpired:
                        warning(f"{desc} process hasn't terminated -- killing it")
                        proc.kill()
                        try:
                            retcode = proc.wait(1)
                        except subprocess.TimeoutExpired:
                            warning(f"{desc} process refuses to die")
                    if retcode is not None:
                        message(f"{desc} process has exited with code {retcode}")

            if podname and pod_created: 
                try:
                    message(f"deleting pod {podname}")
                    resp = kube_api.delete_namespaced_pod(name=podname, namespace=k8s_namespace)
                    # debug(f"delete_namespaced_pod({podname}): {resp}")
                except ApiException as exc:
                    body = exc.body and json.loads(exc.body)
                    traceback.print_exc()
                    error(f"k8s API error: {body}")
                except Exception as exc:
                    traceback.print_exc()
                    error(f"execption raised during cleanup: {exc}")
                    return 1
        except KeyboardInterrupt:
            error(f"cleanup interrupted with Ctrl+C")
            return 1
        except Exception as exc:
            traceback.print_exc()
            error(f"exception raised during cleanup: {exc}")
            return 1

    return 0