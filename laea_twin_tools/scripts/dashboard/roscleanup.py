"""Purge stale experiment node registrations from the ROS master."""

import rosgraph
import rosnode

from .common import EXPERIMENT_ROS_NODE_NAMES, EXPERIMENT_ROS_NODE_PREFIXES


def ros_nodes_online():
    try:
        publishers, subscribers, services = rosgraph.Master(
            "/laea_dashboard"
        ).getSystemState()
    except Exception:
        return set()

    nodes = set()
    for state_group in (publishers, subscribers, services):
        for _resource, resource_nodes in state_group:
            nodes.update(resource_nodes)
    return nodes


def registered_experiment_ros_nodes():
    return sorted(
        node
        for node in ros_nodes_online()
        if node in EXPERIMENT_ROS_NODE_NAMES
        or any(node.startswith(prefix) for prefix in EXPERIMENT_ROS_NODE_PREFIXES)
    )


def purge_experiment_ros_nodes():
    nodes = registered_experiment_ros_nodes()
    if not nodes:
        return [], []
    try:
        master = rosgraph.Master("/laea_dashboard_cleanup")
        rosnode.cleanup_master_blacklist(master, nodes)
    except Exception as exc:
        return [], [f"ROS cleanup failed: {exc}"]

    remaining = registered_experiment_ros_nodes()
    purged = sorted(set(nodes) - set(remaining))
    errors = []
    if remaining:
        errors.append(
            "ROS registrations remain after cleanup: " + ", ".join(remaining)
        )
    return purged, errors
