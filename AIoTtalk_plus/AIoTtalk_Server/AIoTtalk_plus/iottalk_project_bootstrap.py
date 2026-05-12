import html
import json
import re
import time
from dataclasses import dataclass

import requests
from requests import HTTPError

from config import IoTtalk_info, IoTtalk_project_connections, IoTtalk_project_devices


class BootstrapError(RuntimeError):
    pass


@dataclass
class DeviceObjectRef:
    key: str
    dm_name: str
    in_do_id: int
    out_do_id: int
    idfo_ids: dict
    odfo_ids: dict


@dataclass
class ProjectBootstrapResult:
    p_id: str
    p_name: str
    devices: dict


class IoTtalkProjectBootstrap:
    def __init__(self):
        self.project_name = IoTtalk_info["ProjectName"]
        self.project_password = IoTtalk_info["ProjectPassword"]
        self.base_url = "http://{}:{}".format(
            IoTtalk_info["IoTtalkServer"],
            IoTtalk_info["ProjectServerPort"],
        )
        self.http = requests.Session()

    def _post(self, path, data):
        response = self.http.post(self.base_url + path, data=data, timeout=20)
        response.raise_for_status()
        return response

    def _post_json(self, path, data):
        response = self._post(path, data)
        try:
            return response.json()
        except ValueError as error:
            raise BootstrapError("Invalid JSON from {}: {}".format(path, response.text[:300])) from error

    def list_projects(self):
        response = self.http.get(self.base_url + "/connection", timeout=20)
        response.raise_for_status()
        pattern = re.compile(r'<li class="project-list" ><a name=([0-9]+)>(.*?)</a></li>')
        projects = {}
        for project_id, project_name in pattern.findall(response.text):
            name = html.unescape(project_name.strip())
            if name == "add project":
                continue
            projects[name] = project_id
        return projects

    def ensure_project(self):
        projects = self.list_projects()
        project_id = projects.get(self.project_name)
        if project_id is None:
            result = self._post_json("/check_project_name_is_exist", {"project_name": self.project_name})
            if result.get("is_exist"):
                projects = self.list_projects()
                project_id = projects.get(self.project_name)
            else:
                response = self._post("/new_project", {"p_name": self.project_name, "p_pwd": self.project_password})
                project_id = response.text.strip()
        if not project_id:
            raise BootstrapError("Cannot resolve IoTtalk project ID for {}".format(self.project_name))

        auth_result = self._post_json(
            "/connection_with_p_id_p_pwd",
            {"p_id": project_id, "p_pwd": self.project_password},
        )
        if not auth_result.get("result"):
            raise BootstrapError(
                "IoTtalk project {} exists but password verification failed".format(self.project_name)
            )
        return str(project_id)

    def delete_project(self, project_id):
        self._post("/delete_project", {"p_id": project_id})

    def recreate_project(self):
        projects = self.list_projects()
        project_id = projects.get(self.project_name)
        if project_id is not None:
            self.delete_project(project_id)
            time.sleep(1)
        response = self._post("/new_project", {"p_name": self.project_name, "p_pwd": self.project_password})
        project_id = response.text.strip()
        auth_result = self._post_json(
            "/connection_with_p_id_p_pwd",
            {"p_id": project_id, "p_pwd": self.project_password},
        )
        if not auth_result.get("result"):
            raise BootstrapError(
                "IoTtalk project {} recreate succeeded but password verification failed".format(
                    self.project_name
                )
            )
        return str(project_id)

    def reload_data(self, project_id):
        return self._post_json("/reload_data", {"p_id": project_id})

    def reload_connect_line(self, project_id):
        return self._post_json("/reload_connect_line", {"p_id": project_id})

    def restart_project(self, project_id):
        self._post("/restart_project", {"p_id": project_id})

    def _match_device_object(self, reload_data_result, device_key, spec):
        in_match = None
        out_match = None

        for item in reload_data_result["in_device"]:
            idf_names = [feature[0] for feature in item["p_idf_list"]]
            if item["p_dm_name"][0] == spec["dm_name"] and idf_names == spec["idf_list"]:
                in_match = item
                break

        for item in reload_data_result["out_device"]:
            odf_names = [feature[0] for feature in item["p_odf_list"]]
            if item["p_dm_name"][0] == spec["dm_name"] and odf_names == spec["odf_list"]:
                out_match = item
                break

        if in_match and out_match:
            return DeviceObjectRef(
                key=device_key,
                dm_name=spec["dm_name"],
                in_do_id=in_match["in_do_id"],
                out_do_id=out_match["out_do_id"],
                idfo_ids={feature[0]: feature[1] for feature in in_match["p_idf_list"]},
                odfo_ids={feature[0]: feature[1] for feature in out_match["p_odf_list"]},
            )
        if in_match or out_match:
            raise BootstrapError(
                "IoTtalk project {} has partial device object state for {}".format(self.project_name, device_key)
            )
        return None

    def ensure_device_object(self, project_id, device_key, spec, reload_data_result):
        existing = self._match_device_object(reload_data_result, device_key, spec)
        if existing is not None:
            return existing

        response = self._post_json(
            "/create_device_object",
            {
                "dm_info": json.dumps(
                    {
                        "p_id": project_id,
                        "dm_name": spec["dm_name"],
                        "idf_list": spec["idf_list"],
                        "odf_list": spec["odf_list"],
                    }
                )
            },
        )
        return DeviceObjectRef(
            key=device_key,
            dm_name=spec["dm_name"],
            in_do_id=response["ido_id"],
            out_do_id=response["odo_id"],
            idfo_ids=dict(zip(spec["idf_list"], response["idfo_id_list"])),
            odfo_ids=dict(zip(spec["odf_list"], response["odfo_id_list"])),
        )

    def ensure_devices(self, project_id):
        reload_data_result = self.reload_data(project_id)
        devices = {}
        for device_key, spec in IoTtalk_project_devices.items():
            device = self.ensure_device_object(project_id, device_key, spec, reload_data_result)
            devices[device_key] = device
            reload_data_result = self.reload_data(project_id)
        return devices

    def ensure_connections(self, project_id, devices):
        connection_segments = self.reload_connect_line(project_id)
        join_to_features = {}
        for join_id, feature_id, _color in connection_segments:
            join_to_features.setdefault(int(join_id), set()).add(int(feature_id))

        for connection in IoTtalk_project_connections:
            idfo_id = devices[connection["from_device"]].idfo_ids[connection["from_feature"]]
            odfo_id = devices[connection["to_device"]].odfo_ids[connection["to_feature"]]

            exists = any(
                int(idfo_id) in features and int(odfo_id) in features
                for features in join_to_features.values()
            )
            if exists:
                continue

            response = self._post_json(
                "/save_connection_line",
                {
                    "setting_info": json.dumps(
                        {
                            "connect_info": [connection["name"], 0, idfo_id, odfo_id],
                            "p_id": project_id,
                        }
                    )
                },
            )
            join_to_features[int(response["na_id"])] = {int(idfo_id), int(odfo_id)}

    def validate_topology(self, project_id):
        reload_data_result = self.reload_data(project_id)
        for device_key, spec in IoTtalk_project_devices.items():
            self._match_device_object(reload_data_result, device_key, spec)

        connection_segments = self.reload_connect_line(project_id)
        join_to_features = {}
        for join_id, feature_id, _color in connection_segments:
            join_to_features.setdefault(int(join_id), set()).add(int(feature_id))

        devices = {
            key: self._match_device_object(reload_data_result, key, spec)
            for key, spec in IoTtalk_project_devices.items()
        }

        for connection in IoTtalk_project_connections:
            idfo_id = devices[connection["from_device"]].idfo_ids[connection["from_feature"]]
            odfo_id = devices[connection["to_device"]].odfo_ids[connection["to_feature"]]
            exists = any(
                int(idfo_id) in features and int(odfo_id) in features
                for features in join_to_features.values()
            )
            if not exists:
                raise BootstrapError(
                    "IoTtalk project {} is missing connection {} -> {}".format(
                        self.project_name,
                        connection["from_feature"],
                        connection["to_feature"],
                    )
                )
        return devices

    def _bootstrap_project(self, project_id):
        devices = self.ensure_devices(project_id)
        self.ensure_connections(project_id, devices)
        self.restart_project(project_id)
        time.sleep(1)
        devices = self.validate_topology(project_id)
        return ProjectBootstrapResult(
            p_id=project_id,
            p_name=self.project_name,
            devices=devices,
        )

    def ensure(self):
        project_id = self.ensure_project()
        try:
            return self._bootstrap_project(project_id)
        except (BootstrapError, HTTPError) as error:
            print(
                "IoTtalk bootstrap detected inconsistent project {} ({}), recreating".format(
                    self.project_name,
                    error,
                )
            )
            project_id = self.recreate_project()
            return self._bootstrap_project(project_id)


def ensure_iottalk_project():
    return IoTtalkProjectBootstrap().ensure()
